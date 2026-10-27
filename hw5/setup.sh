#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="cs528-project-0-508215"
BUCKET_NAME="ec528hw2"
SA_NAME="hw5-app"
SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"
TOPIC="hw5-forbidden-requests"
SUBSCRIPTION="hw5-forbidden-requests-sub"

cd "$(dirname "$0")"

# Enable required APIs.
gcloud services enable \
    compute.googleapis.com \
    sqladmin.googleapis.com \
    pubsub.googleapis.com \
    logging.googleapis.com \
    iam.googleapis.com \
    --project="$PROJECT_ID" --quiet

# Create the VM service account if it does not exist.
if ! gcloud iam service-accounts describe "$SA_EMAIL" \
    --project="$PROJECT_ID" >/dev/null 2>&1
then
    gcloud iam service-accounts create "$SA_NAME" \
        --display-name="HW5 application" \
        --project="$PROJECT_ID"
    sleep 60
fi

# Grant permissions needed by the two applications.
for role in \
    roles/cloudsql.client \
    roles/logging.logWriter \
    roles/pubsub.publisher \
    roles/pubsub.subscriber
do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:$SA_EMAIL" \
        --role="$role" \
        --condition=None \
        --quiet --format=none
done

# Allow the VM to read the existing homework files.
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_NAME" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/storage.objectViewer" \
    --condition=None \
    --quiet --format=none

# Create the Pub/Sub resources if they do not exist.
if ! gcloud pubsub topics describe "$TOPIC" \
    --project="$PROJECT_ID" >/dev/null 2>&1
then
    gcloud pubsub topics create "$TOPIC" \
        --project="$PROJECT_ID"
fi

if ! gcloud pubsub subscriptions describe "$SUBSCRIPTION" \
    --project="$PROJECT_ID" >/dev/null 2>&1
then
    gcloud pubsub subscriptions create "$SUBSCRIPTION" \
        --topic="$TOPIC" \
        --project="$PROJECT_ID"
fi

echo "HW5 permissions and Pub/Sub are ready."

REGION="us-east1"
ZONE="us-east1-b"
SQL_INSTANCE="hw5-db"
VM_NAME="hw5-server"

# Prepare Python for running setup_schema.py.
if [ -x "../.venv/Scripts/python.exe" ]; then
    PYTHON="../.venv/Scripts/python.exe"
    "$PYTHON" -m ensurepip
else
    python3 -m venv .venv
    PYTHON=".venv/bin/python"
fi
"$PYTHON" -m pip install -r requirements.txt

umask 077
export DB_USER="postgres" DB_NAME="hw5"
DB_PASSWORD=$("$PYTHON" -c 'import secrets; print(secrets.token_hex(24))')
export DB_PASSWORD
export INSTANCE_CONNECTION_NAME="$PROJECT_ID:$REGION:$SQL_INSTANCE"

setup_database() {
    if gcloud sql instances describe "$SQL_INSTANCE" \
        --project="$PROJECT_ID" >/dev/null 2>&1
    then
        gcloud sql instances patch "$SQL_INSTANCE" \
            --activation-policy=ALWAYS \
            --project="$PROJECT_ID" --quiet
    else
        gcloud sql instances create "$SQL_INSTANCE" \
            --database-version=POSTGRES_16 --edition=ENTERPRISE \
            --tier=db-g1-small --region="$REGION" \
            --availability-type=zonal \
            --storage-type=SSD --storage-size=10 \
            --no-storage-auto-increase --assign-ip --no-backup \
            --project="$PROJECT_ID" --quiet
    fi

    if ! gcloud sql databases describe "$DB_NAME" \
        --instance="$SQL_INSTANCE" \
        --project="$PROJECT_ID" >/dev/null 2>&1
    then
        gcloud sql databases create "$DB_NAME" \
            --instance="$SQL_INSTANCE" --project="$PROJECT_ID"
    fi

    gcloud sql users set-password "$DB_USER" \
        --instance="$SQL_INSTANCE" --password="$DB_PASSWORD" \
        --project="$PROJECT_ID" --quiet

    # Reuse the identity already authenticated with gcloud.
    GCP_ACCESS_TOKEN=$(gcloud auth print-access-token --project="$PROJECT_ID")
    export GCP_ACCESS_TOKEN
    "$PYTHON" setup_schema.py
    unset GCP_ACCESS_TOKEN
}

setup_database

# Generate the configuration passed to the VM.
cat > app.env <<EOF
PROJECT_ID=$PROJECT_ID
BUCKET_NAME=$BUCKET_NAME
TOPIC_ID=$TOPIC
SUBSCRIPTION_ID=$SUBSCRIPTION
INSTANCE_CONNECTION_NAME=$INSTANCE_CONNECTION_NAME
DB_USER=$DB_USER
DB_NAME=$DB_NAME
DB_PASSWORD=$DB_PASSWORD
RUN_ID=stress-01
PORT=8080
EOF

if ! gcloud compute firewall-rules describe hw5-allow-http \
    --project="$PROJECT_ID" >/dev/null 2>&1
then
    gcloud compute firewall-rules create hw5-allow-http \
        --network=default --allow=tcp:8080 \
        --source-ranges=0.0.0.0/0 --target-tags=hw5-server \
        --project="$PROJECT_ID"
fi

# Match the metadata names used by startup.sh.
METADATA="startup-script=startup.sh,app-env=app.env,requirements=requirements.txt"
METADATA+=",service2-main=service2/main.py"
for module in main database db_pool request_data timing; do
    METADATA+=",service1-$module=service1/$module.py"
done

if gcloud compute instances describe "$VM_NAME" \
    --zone="$ZONE" --project="$PROJECT_ID" >/dev/null 2>&1
then
    gcloud compute instances add-metadata "$VM_NAME" \
        --metadata-from-file="$METADATA" \
        --zone="$ZONE" --project="$PROJECT_ID"

    STATE=$(gcloud compute instances describe "$VM_NAME" \
        --zone="$ZONE" --project="$PROJECT_ID" --format='value(status)')

    if [ "$STATE" = "TERMINATED" ]; then
        gcloud compute instances start "$VM_NAME" \
            --zone="$ZONE" --project="$PROJECT_ID" --quiet
    else
        gcloud compute instances reset "$VM_NAME" \
            --zone="$ZONE" --project="$PROJECT_ID" --quiet
    fi
else
    gcloud compute instances create "$VM_NAME" \
        --zone="$ZONE" --machine-type=e2-small \
        --image-family=debian-12 --image-project=debian-cloud \
        --boot-disk-size=10GB --boot-disk-type=pd-standard \
        --network=default --tags=hw5-server \
        --service-account="$SA_EMAIL" --scopes=cloud-platform \
        --metadata-from-file="$METADATA" \
        --project="$PROJECT_ID" --quiet
fi

SERVER_IP=$(gcloud compute instances describe "$VM_NAME" \
    --zone="$ZONE" --project="$PROJECT_ID" \
    --format='value(networkInterfaces[0].accessConfigs[0].natIP)')
echo "Server URL: http://$SERVER_IP:8080/pages/0.html"
echo "The VM startup script may still be installing dependencies."