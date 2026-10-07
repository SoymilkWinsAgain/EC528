import shutil
import subprocess
from google.cloud import pubsub_v1, storage
from google.oauth2.credentials import Credentials
import json
from google.api_core.exceptions import NotFound, PreconditionFailed
from datetime import datetime, timedelta, timezone
from google.auth.transport.requests import Request

PROJECT_ID = "cs528-project-0-508215"
SERVICE_ACCOUNT = "hw3-service@cs528-project-0-508215.iam.gserviceaccount.com"
LOG_OBJECT = "forbidden-logs/requests.jsonl"


def get_credentials():
    gcloud = shutil.which("gcloud.cmd")
    if gcloud is None:
        raise RuntimeError("Cannot find gcloud.cmd")

    def refresh_access_token(request, scopes=None):
        # It is said that the token will be valid for 1 hour
        expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=50)
        result = subprocess.run(
            [
                gcloud,
                "auth",
                "print-access-token",
                f"--impersonate-service-account={SERVICE_ACCOUNT}",
                f"--project={PROJECT_ID}",
                "--lifetime=3600",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )

        token = result.stdout.strip()
        if not token:
            raise RuntimeError("No access token returned")

        print("Service account token refreshed", flush=True)
        return token, expiry

    credentials = Credentials(
        token=None,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
        refresh_handler=refresh_access_token,
    )
    credentials.refresh(Request())
    return credentials

credentials = get_credentials()

subscriber = pubsub_v1.SubscriberClient(credentials=credentials)
storage_client = storage.Client(project=PROJECT_ID, credentials=credentials)
subscription_path = subscriber.subscription_path(PROJECT_ID, "hw3-forbidden-requests-sub")
bucket = storage_client.bucket("ec528hw2")

print(f"Using service account: {SERVICE_ACCOUNT}", flush=True)


def append_event(message_id, event):
    for _ in range(5):
        blob = bucket.blob(LOG_OBJECT)
        try:
            try:
                blob.reload()
                generation = blob.generation
                existing = blob.download_as_text(encoding="utf-8", if_generation_match=generation)
            except NotFound:
                generation = 0
                existing = ""

            # Avoid duplicate entries if Pub/Sub redelivers a message
            for line in existing.splitlines():
                if json.loads(line).get("message_id") == message_id:
                    return

            record = {**event, "message_id": message_id}
            updated = existing + json.dumps(record) + "\n"

            blob.upload_from_string(
                updated,
                content_type="application/x-ndjson",
                if_generation_match=generation,
            )
            return
        except PreconditionFailed:
            continue
    raise RuntimeError("Log file changed repeatedly; retry later")


def callback(message):
    try:
        event = json.loads(message.data.decode("utf-8"))
        print(event["message"], flush=True)
        append_event(message.message_id, event)
    except Exception as exc:
        print(f"Failed to process message: {exc}", flush=True)
        message.nack()
        return
    message.ack()


streaming_future = subscriber.subscribe(
    subscription_path,
    callback=callback,
    flow_control=pubsub_v1.types.FlowControl(max_messages=1),
)

print(f"Listening on {subscription_path}", flush=True)

try:
    streaming_future.result()
except KeyboardInterrupt:
    streaming_future.cancel()
    streaming_future.result()
finally:
    subscriber.close()
    storage_client.close()