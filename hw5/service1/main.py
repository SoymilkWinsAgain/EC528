import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from google.api_core.exceptions import NotFound
from google.cloud import logging as cloud_logging
from google.cloud import pubsub_v1, storage
from db_pool import RequestDatabase
from request_data import extract_request_data
from timing import measure


PROJECT_ID = os.environ["PROJECT_ID"]
BUCKET_NAME = os.environ["BUCKET_NAME"]
PORT = int(os.environ.get("PORT", "8080"))
RUN_ID = os.environ.get("RUN_ID", "manual")

storage_client = storage.Client(project=PROJECT_ID)
bucket = storage_client.bucket(BUCKET_NAME)
file_cache = {}
logging_client = cloud_logging.Client(project=PROJECT_ID)
cloud_logger = logging_client.logger("hw5-service1")
publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path(PROJECT_ID, os.environ.get("TOPIC_ID", "hw5-forbidden-requests"))


class Server(ThreadingHTTPServer):
    # Wait for active requests before closing the database pool.
    daemon_threads = False


class Handler(BaseHTTPRequestHandler):
    def begin_request(self):
        self.timings = {}
        with measure(self.timings, "headers_ns"):
            headers = getattr(self, "headers", {})
            raw_path = getattr(self, "path", "")
            try:
                filename = unquote(urlsplit(raw_path).path).lstrip("/")
            except ValueError:
                filename = raw_path
            run_id = headers.get("X-Run-ID", RUN_ID).strip() or RUN_ID
            self.request_data = extract_request_data(
                headers, filename, run_id
            )

    def log_event(self, severity, event_type, status, **fields):
        event = {
            "event_type": event_type,
            "http_method": self.command,
            "request_path": getattr(self, "path", ""),
            "filename": self.request_data["requested_file"],
            "status_code": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        print(json.dumps({"severity": severity, **event}), flush=True)
        try:
            cloud_logger.log_struct(event, severity=severity)
        except Exception as exc:
            print(json.dumps({
                "severity": "ERROR",
                "event_type": "cloud_logging_failed",
                "error": str(exc),
            }), flush=True)
        return event

    def send_http_response(self, status, body, content_type):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.wfile.flush()

    def respond(self, status, body, content_type="text/plain; charset=utf-8"):
        request_id = None
        db_logged = False
        response_sent = False

        try:
            with measure(self.timings, "database_ns"):
                request_id = self.server.database.write_request(
                    self.request_data, status
                )
            db_logged = True
        except Exception as exc:
            status = 503
            body = "Database unavailable\n"
            content_type = "text/plain; charset=utf-8"
            self.log_event(
                "ERROR", "database_write_failed", status,
                error=str(exc),
            )

        try:
            with measure(self.timings, "response_ns"):
                self.send_http_response(status, body, content_type)
            response_sent = True
        except OSError as exc:
            self.log_event(
                "WARNING", "response_send_failed", status,
                error=str(exc),
            )
        finally:
            print(json.dumps({
                "event_type": "request_timing",
                "request_id": request_id,
                "run_id": self.request_data["run_id"],
                "requested_file": self.request_data["requested_file"],
                "received_at": self.request_data["received_at"].isoformat(),
                "status_code": status,
                "db_logged": db_logged,
                "response_sent": response_sent,
                "timings_ns": {
                    name: self.timings.get(name)
                    for name in (
                        "headers_ns", "storage_ns",
                        "response_ns", "database_ns",
                    )
                },
            }), flush=True)

    def read_cloud_file(self, object_name):
        if object_name in file_cache:
            return file_cache[object_name]

        with measure(self.timings, "storage_ns"):
            contents = bucket.blob(object_name).download_as_bytes(timeout=20)

        file_cache[object_name] = contents
        return contents

    def serve_file(self, object_name):
        country = self.request_data["country"]
        if self.request_data["is_banned"]:
            event = self.log_event(
                "CRITICAL", "forbidden_country", 400,
                country=country,
                message=(
                    f"Permission denied: request from {country} "
                    f"for {object_name}"
                ),
            )
            try:
                publisher.publish(
                    topic_path, json.dumps(event).encode("utf-8")
                ).result(timeout=10)
            except Exception as exc:
                self.log_event(
                    "ERROR", "forbidden_event_publish_failed", 503,
                    error=str(exc),
                )
                self.respond(503, "Unable to report forbidden request\n")
                return
            self.respond(400, "Permission denied\n")
            return

        if not object_name.startswith("pages/"):
            self.log_event("WARNING", "file_not_found", 404)
            self.respond(404, "File not found\n")
            return

        try:
            contents = self.read_cloud_file(object_name)
        except NotFound:
            self.log_event("WARNING", "file_not_found", 404)
            self.respond(404, "File not found\n")
            return
        except Exception as exc:
            self.log_event(
                "ERROR", "storage_read_failed", 503, error=str(exc)
            )
            self.respond(503, "Unable to read file\n")
            return

        self.respond(200, contents, "text/html; charset=utf-8")

    def do_GET(self):
        self.begin_request()
        self.serve_file(self.request_data["requested_file"])

    def read_post_file(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 8192:
            raise ValueError("Invalid payload size")

        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a JSON object")

        filename = payload.get("file")
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("Missing file field")
        return filename.strip().lstrip("/")

    def do_POST(self):
        self.begin_request()
        try:
            with measure(self.timings, "headers_ns"):
                filename = self.read_post_file()
                self.request_data["requested_file"] = filename
        except (ValueError, UnicodeDecodeError):
            self.log_event("WARNING", "invalid_payload", 400)
            self.respond(400, 'Expected JSON: {"file": "pages/0.html"}\n')
            return
        self.serve_file(filename)

    def send_error(self, code, message=None, explain=None):
        if not hasattr(self, "request_data"):
            self.begin_request()

        description = message or self.responses.get(code, ("Error",))[0]
        self.log_event("ERROR", "http_error", code, message=description)
        self.respond(code, description + "\n")

    def log_message(self, fmt, *args):
        # Structured events already include request status and timing.
        pass


def main():
    database = RequestDatabase()
    try:
        with Server(("0.0.0.0", PORT), Handler) as server:
            server.database = database
            print(f"Listening on port {PORT}; run_id={RUN_ID}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    finally:
        database.close()


if __name__ == "__main__":
    main()