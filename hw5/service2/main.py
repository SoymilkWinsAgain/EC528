import json
import os

from google.cloud import pubsub_v1


PROJECT_ID = os.environ["PROJECT_ID"]
SUBSCRIPTION_ID = os.environ.get(
    "SUBSCRIPTION_ID",
    "hw4-forbidden-requests-sub",
)


def callback(message):
    try:
        event = json.loads(message.data.decode("utf-8"))

        print(
            f"[FORBIDDEN] {event['message']} "
            f"(message_id={message.message_id})",
            flush=True,
        )

        print(
            json.dumps({
                **event,
                "message_id": message.message_id,
            }),
            flush=True,
        )
    except Exception as exc:
        print(f"Failed to process message: {exc}", flush=True)
        message.nack()
        return

    message.ack()


def main():
    with pubsub_v1.SubscriberClient() as subscriber:
        subscription_path = subscriber.subscription_path(
            PROJECT_ID,
            SUBSCRIPTION_ID,
        )

        future = subscriber.subscribe(
            subscription_path,
            callback=callback,
            flow_control=pubsub_v1.types.FlowControl(max_messages=1),
            await_callbacks_on_shutdown=True,
        )

        print(f"Listening on {subscription_path}", flush=True)

        try:
            future.result()
        except KeyboardInterrupt:
            print("Stopping subscriber...", flush=True)
        finally:
            future.cancel()
            future.result()


if __name__ == "__main__":
    main()