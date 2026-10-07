# README.md

## Run the program

### Service 1: Deploy the cloud function

```bash
gcloud functions deploy hw3-service1 \
  --gen2 \
  --project=cs528-project-0-508215 \
  --region=us-east1 \
  --runtime=python312 \
  --source=hw3/service1 \
  --entry-point=serve_file \
  --trigger-http \
  --allow-unauthenticated \
  --service-account=hw3-service@cs528-project-0-508215.iam.gserviceaccount.com
```

### Service 2: Run locally on Windows

Requires Google Cloud CLI, uv, and the IAM permissions described in the report.

```bash
uv sync --locked
uv run python hw3/service2/main.py
```

### Send a forbidden-country request

In another terminal:

```bash
curl.exe -i \
  -H "X-country: Iran" \
  "https://hw3-service1-i4wbkbm4rq-ue.a.run.app/pages/0.html"
```

The request returns HTTP 400. Service 2 prints the error and appends it to `gs://ec528hw2/forbidden-logs/requests.jsonl`.