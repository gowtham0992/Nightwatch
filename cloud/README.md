# Cloud Run training job

This is the first deployable cloud slice: an isolated GPU trainer that can read only a curriculum object and write only a new adapter prefix. Do not grant its service account access to the hidden-eval bucket or production pointer.

Build and push the image to Artifact Registry, then deploy the job (substitute your project, region, repository, bucket, and service-account values):

```bash
gcloud auth configure-docker us-central1-docker.pkg.dev
docker build \
  --file containers/trainer.Dockerfile \
  --tag us-central1-docker.pkg.dev/PROJECT_ID/nightwatch/trainer:spike .
docker push us-central1-docker.pkg.dev/PROJECT_ID/nightwatch/trainer:spike

gcloud run jobs deploy nightwatch-trainer \
  --image us-central1-docker.pkg.dev/PROJECT_ID/nightwatch/trainer:spike \
  --region us-central1 \
  --service-account nightwatch-trainer@PROJECT_ID.iam.gserviceaccount.com \
  --cpu 4 \
  --memory 16Gi \
  --gpu 1 \
  --gpu-type nvidia-l4 \
  --no-gpu-zonal-redundancy \
  --tasks 1 \
  --parallelism 1 \
  --max-retries 1 \
  --task-timeout 3600s \
  --set-secrets HF_TOKEN=nightwatch-hf-token:latest \
  --args=--curriculum-uri=gs://CURRICULUM_BUCKET/cycles/001/train.jsonl,--adapter-uri=gs://ADAPTER_BUCKET/cycles/001/adapter

gcloud run jobs execute nightwatch-trainer --region us-central1 --wait
```

Cloud Run GPU jobs require non-zonal redundancy, at least 4 CPU and 16 GiB memory for an L4, and have a maximum one-hour task timeout. Capacity is not guaranteed, so the trainer writes the adapter only after training completes; the orchestrator must treat an absent adapter manifest as an incomplete attempt.
