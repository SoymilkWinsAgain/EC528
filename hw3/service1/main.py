import functions_framework
from google.cloud import storage
from google.api_core.exceptions import NotFound
import json


storage_client = storage.Client()
bucket = storage_client.bucket("ec528hw2")

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