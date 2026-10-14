import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote, urlsplit
from datetime import datetime, timezone

from google.api_core.exceptions import NotFound
from google.cloud import logging as cloud_logging
from google.cloud import storage
from google.cloud import pubsub_v1


PROJECT_ID = os.environ["PROJECT_ID"]
BUCKET_NAME = os.environ["BUCKET_NAME"]
PORT = int(os.environ.get("PORT", "8080"))

storage_client = storage.Client(project=PROJECT_ID)
bucket = storage_client.bucket(BUCKET_NAME)

logging_client = cloud_logging.Client(project=PROJECT_ID)
cloud_logger = logging_client.logger("hw4-service1")
publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path(PROJECT_ID, os.environ.get("TOPIC_ID", "hw4-forbidden-requests"))
FORBIDDEN_COUNTRIES = {
    "north korea", "iran", "cuba", "myanmar", "iraq",
    "libya", "sudan", "zimbabwe", "syria",
    "kp", "ir", "cu", "mm", "iq", "ly", "sd", "zw", "sy",
}


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, body, content_type="text/plain; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()

        # Only send the headers
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_event(self, severity, event_type, status, filename=None, **fields):
        event = {
            "event_type": event_type,
            "http_method": self.command,
            "request_path": self.path,
            "filename": filename,
            "status_code": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        print(json.dumps({"severity": severity, **event}), flush=True)
        cloud_logger.log_struct(event, severity=severity)
        return event
        

    def serve_file(self, object_name):
        country = self.headers.get("X-country", "").strip()
        if country.casefold() in FORBIDDEN_COUNTRIES:
            event = self.log_event(
                "CRITICAL",
                "forbidden_country",
                400,
                object_name,
                country=country,
                message=f"Permission denied: request from {country} for {object_name}",
            )

            try:
                future = publisher.publish(
                    topic_path,
                    json.dumps(event).encode("utf-8"),
                )
                message_id = future.result(timeout=10)
            except Exception as exc:
                self.log_event(
                    "ERROR",
                    "forbidden_event_publish_failed",
                    503,
                    object_name,
                    error=str(exc),
                )
                self.respond(503, "Unable to report forbidden request\n")
                return

            print(f"Published forbidden event: {message_id}", flush=True)
            self.respond(400, "Permission denied\n")
            return
        if not object_name.startswith("pages/"):
            self.log_event("WARNING", "file_not_found", 404, object_name)
            self.respond(404, "File not found\n")
            return

        try:
            contents = bucket.blob(object_name).download_as_bytes(timeout=20)
        except NotFound:
            self.log_event("WARNING", "file_not_found", 404, object_name)
            self.respond(404, "File not found\n")
            return

        self.respond(200, contents, "text/html; charset=utf-8")

    def do_GET(self):
        path = urlsplit(self.path).path
        object_name = unquote(path).lstrip("/")
        self.serve_file(object_name)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                raise ValueError("Invalid payload size")

            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Payload must be a JSON object")

            filename = payload.get("file")
            if not isinstance(filename, str) or not filename.strip():
                raise ValueError("Missing file field")

        except (ValueError, UnicodeDecodeError):
            self.log_event("WARNING", "invalid_payload", 400)
            self.respond(400, 'Expected JSON: {"file": "pages/0.html"}\n')
            return

        self.serve_file(filename.strip().lstrip("/"))

    def unsupported_method(self):
        self.log_event("ERROR", "method_not_implemented", 501)
        self.respond(501, "Method not implemented\n")

    do_PUT = unsupported_method
    do_DELETE = unsupported_method
    do_HEAD = unsupported_method
    do_CONNECT = unsupported_method
    do_OPTIONS = unsupported_method
    do_TRACE = unsupported_method
    do_PATCH = unsupported_method


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Listening on port {PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()