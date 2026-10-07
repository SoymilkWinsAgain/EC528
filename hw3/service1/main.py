import functions_framework
from google.cloud import storage
from google.api_core.exceptions import NotFound
import json
from google.cloud import pubsub_v1
from datetime import datetime, timezone


storage_client = storage.Client()
bucket = storage_client.bucket("ec528hw2")
publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path(
    "cs528-project-0-508215",
    "hw3-forbidden-requests",
)

FORBIDDEN_COUNTRIES = {
    "north korea", "iran", "cuba", "myanmar", "iraq",
    "libya", "sudan", "zimbabwe", "syria",
    "kp", "ir", "cu", "mm", "iq", "ly", "sd", "zw", "sy",
}

def log_error(request, event_type, status_code, filename=None):
    # text log
    print(
        f"[ERROR {status_code}] "
        f"type={event_type}, method={request.method}, "
        f"path={request.path}, filename={filename}",
        flush=True,
    )
    
    # structured log
    print(
        json.dumps({
            "severity": "ERROR",
            "message": event_type,
            "event_type": event_type,
            "status_code": status_code,
            "http_method": request.method,
            "request_path": request.path,
            "filename": filename,
        }),
        flush=True,
    )

@functions_framework.http
def serve_file(request):
    print(f"Received: {request.method} {request.path}")

    match request.method:
        case "GET":
            object_name = request.path.lstrip("/")
        case "POST":
            payload = request.get_json(silent=True)
            file_name = payload.get("file")
            object_name = file_name.strip().lstrip("/")
        case _:
            log_error(request, "method_not_implemented", 501)
            return "Method not implemented\n", 501
        
    country = request.headers.get("X-country", "").strip()
    if country.casefold() in FORBIDDEN_COUNTRIES:
        event = {
            "severity": "ERROR",
            "event_type": "forbidden_country",
            "status_code": 400,
            "message": (
                f"Permission denied: request from {country} "
                f"for {object_name}"
            ),
            "country": country,
            "http_method": request.method,
            "request_path": request.path,
            "filename": object_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Ordinary text log and structured log
        print(event["message"], flush=True)
        print(json.dumps(event), flush=True)

        # Wait for Pub/Sub to confirm publication
        future = publisher.publish(
            topic_path,
            json.dumps(event).encode("utf-8"),
        )
        future.result(timeout=10)

        return "Permission denied\n", 400

    if not object_name.startswith("pages/"):
        log_error(request, "file_not_found", 404, object_name)
        return "File not found\n", 404

    blob = bucket.blob(object_name)

    try:
        contents = blob.download_as_bytes()
    except NotFound:
        print(f"File not found: {object_name}")
        log_error(request, "file_not_found", 404, object_name)
        return "File not found\n", 404

    return contents, 200, {
        "Content-Type": "text/html; charset=utf-8"
    }