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
    NIGHTWATCH_PUBLIC_FOLLOWUPS_DIR=/app/public-followups \
    NIGHTWATCH_WEB_ROOT=/app/web-dist \
    PORT=8080

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN pip install --no-cache-dir uv==0.11.8 \
    && uv export --frozen --no-dev --extra service --no-emit-project --no-hashes --output-file /tmp/requirements.txt \
    && uv pip install --system --no-cache -r /tmp/requirements.txt \
    && uv pip install --system --no-cache --no-deps . \
    && useradd --create-home --uid 10001 nightwatch
COPY --from=web-builder /workspace/web/dist ./web-dist
COPY artifacts/public-mission-v2.json ./public-missions/nightwatch-v2-qualification.json
COPY artifacts/public-mission-cloud-20260811-001.json ./public-missions/nightwatch-cloud-20260811-001.json
COPY artifacts/public-mission-live-89e73407c43d525c4bc19272.json ./public-missions/nightwatch-live-89e73407c43d525c4bc19272.json
COPY artifacts/public-mission-live-fe8a4e9d756508004f9214de.json ./public-missions/nightwatch-live-fe8a4e9d756508004f9214de.json
COPY artifacts/public-mission-live-a786ae339253954371f524f8.json ./public-missions/nightwatch-live-a786ae339253954371f524f8.json
COPY artifacts/public-mission-live-ac7c9d317783b6af4e543b1d.json ./public-missions/nightwatch-live-ac7c9d317783b6af4e543b1d.json
COPY artifacts/public-followups ./public-followups
COPY containers/gunicorn.conf.py ./containers/gunicorn.conf.py

USER nightwatch
EXPOSE 8080
CMD ["gunicorn", "--config", "/app/containers/gunicorn.conf.py", "nightwatch.service:create_app()"]
