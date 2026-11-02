import functions_framework
from googleapiclient.discovery import build


PROJECT_ID = "cs528-project-0-508215"
INSTANCE_ID = "hw5-db"


@functions_framework.http
def stop_database(request):
    sql = build("sqladmin", "v1beta4", cache_discovery=False)

    instance = sql.instances().get(
        project=PROJECT_ID,
        instance=INSTANCE_ID,
    ).execute()

    if (
        instance["state"] == "RUNNABLE"
        and instance["settings"]["activationPolicy"] == "ALWAYS"
    ):
        operation = sql.instances().patch(
            project=PROJECT_ID,
            instance=INSTANCE_ID,
            body={"settings": {"activationPolicy": "NEVER"}},
        ).execute()

        return {
            "message": "Stop requested",
            "operation": operation["name"],
        }, 200

    return {"message": "No action needed"}, 200