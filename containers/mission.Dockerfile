FROM python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[service,agent,experiment]" \
    && useradd --create-home --uid 10001 nightwatch

COPY artifacts/v0-curriculum.jsonl ./artifacts/v0-curriculum.jsonl
COPY artifacts/v0-dev.jsonl ./artifacts/v0-dev.jsonl
COPY artifacts/classifier-1395040c-1e98fdcf-74d932a468-dev-report.json ./artifacts/classifier-1395040c-1e98fdcf-74d932a468-dev-report.json
COPY artifacts/evidence-audit-v2/development.jsonl ./artifacts/evidence-audit-v2/development.jsonl
COPY artifacts/evidence-audit-v2/manifest.json ./artifacts/evidence-audit-v2/manifest.json
COPY data/eval/frozen.jsonl ./data/eval/frozen.jsonl
COPY containers/mission-gunicorn.conf.py ./containers/mission-gunicorn.conf.py

USER nightwatch
EXPOSE 8080
CMD ["gunicorn", "--config", "/app/containers/mission-gunicorn.conf.py", "nightwatch.mission_entrypoint:create_app()"]
