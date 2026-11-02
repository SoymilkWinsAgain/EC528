#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="cs528-project-0-508215"
ZONE="us-east1-b"
SA_EMAIL="hw5-app@$PROJECT_ID.iam.gserviceaccount.com"

# Stop Cloud SQL and preserve its data.
gcloud sql instances patch hw5-db \
    --activation-policy=NEVER \
    --project="$PROJECT_ID" --quiet

# Delete the VM and its automatically deleted boot disk.
if gcloud compute instances describe hw5-server \
    --zone="$ZONE" --project="$PROJECT_ID" >/dev/null 2>&1
then
    gcloud compute instances delete hw5-server \
        --zone="$ZONE" --project="$PROJECT_ID" --quiet
fi

if gcloud compute firewall-rules describe hw5-allow-http \
    --project="$PROJECT_ID" >/dev/null 2>&1
then
    gcloud compute firewall-rules delete hw5-allow-http \
        --project="$PROJECT_ID" --quiet
fi

if gcloud pubsub subscriptions describe hw5-forbidden-requests-sub \
    --project="$PROJECT_ID" >/dev/null 2>&1
then
    gcloud pubsub subscriptions delete hw5-forbidden-requests-sub \
        --project="$PROJECT_ID" --quiet
fi

if gcloud pubsub topics describe hw5-forbidden-requests \
    --project="$PROJECT_ID" >/dev/null 2>&1
then
    gcloud pubsub topics delete hw5-forbidden-requests \
        --project="$PROJECT_ID" --quiet
fi

# Delete the hourly trigger and its function.
if gcloud scheduler jobs describe hw5-stop-sql-hourly \
    --location=us-east1 --project="$PROJECT_ID" >/dev/null 2>&1
then
    gcloud scheduler jobs delete hw5-stop-sql-hourly \
        --location=us-east1 --project="$PROJECT_ID" --quiet
fi

if gcloud functions describe hw5-stop-sql --gen2 \
    --region=us-east1 --project="$PROJECT_ID" >/dev/null 2>&1
then
    gcloud functions delete hw5-stop-sql \
        --region=us-east1 --project="$PROJECT_ID" --quiet
fi

# Remove permissions before deleting the service account.
if gcloud iam service-accounts describe "$SA_EMAIL" \
    --project="$PROJECT_ID" >/dev/null 2>&1
then
    BUCKET_POLICY=$(gcloud storage buckets get-iam-policy gs://ec528hw2 --format=json)
    if [[ "$BUCKET_POLICY" == *"serviceAccount:$SA_EMAIL"* ]]; then
        gcloud storage buckets remove-iam-policy-binding gs://ec528hw2 \
            --member="serviceAccount:$SA_EMAIL" \
            --role="roles/storage.objectViewer" \
            --condition=None --quiet --format=none
    fi

    ROLE_LIST=$(gcloud projects get-iam-policy "$PROJECT_ID" \
        --flatten="bindings[].members" \
        --filter="bindings.members=serviceAccount:$SA_EMAIL" \
        --format="value(bindings.role)" | tr -d '\r')

    for role in $ROLE_LIST; do
        gcloud projects remove-iam-policy-binding "$PROJECT_ID" \
            --member="serviceAccount:$SA_EMAIL" \
            --role="$role" \
            --condition=None --quiet --format=none
    done

    gcloud iam service-accounts delete "$SA_EMAIL" \
        --project="$PROJECT_ID" --quiet
fi

# ADC may already be absent in the grading environment.
gcloud auth application-default revoke --quiet || true

echo "HW5 cleanup completed."