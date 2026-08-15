FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS web-builder

WORKDIR /workspace
COPY web/package.json web/package-lock.json ./web/
RUN cd web && npm ci
COPY web ./web
COPY artifacts/v0-curriculum.jsonl ./artifacts/v0-curriculum.jsonl
COPY artifacts/v0-18a33dfd5c54-seed-20260809-predictions.jsonl ./artifacts/v0-18a33dfd5c54-seed-20260809-predictions.jsonl
COPY artifacts/v0-18a33dfd5c54-seed-20260809-report.json ./artifacts/v0-18a33dfd5c54-seed-20260809-report.json
COPY data/eval/frozen.jsonl ./data/eval/frozen.jsonl
RUN cd web && npm run build

FROM python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NIGHTWATCH_PUBLIC_MISSIONS_DIR=/app/public-missions \
    NIGHTWATCH_WEB_ROOT=/app/web-dist \
    PORT=8080

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[service]" \
    && useradd --create-home --uid 10001 nightwatch
COPY --from=web-builder /workspace/web/dist ./web-dist
COPY artifacts/public-mission-v2.json ./public-missions/nightwatch-v2-qualification.json
COPY artifacts/public-mission-cloud-20260811-001.json ./public-missions/nightwatch-cloud-20260811-001.json
COPY artifacts/public-mission-live-89e73407c43d525c4bc19272.json ./public-missions/nightwatch-live-89e73407c43d525c4bc19272.json
COPY containers/gunicorn.conf.py ./containers/gunicorn.conf.py

USER nightwatch
EXPOSE 8080
CMD ["gunicorn", "--config", "/app/containers/gunicorn.conf.py", "nightwatch.service:create_app()"]
