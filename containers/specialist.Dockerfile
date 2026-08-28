FROM python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[agent]" \
    && useradd --create-home --uid 10001 nightwatch

USER nightwatch
EXPOSE 8080
CMD ["python", "-m", "nightwatch.specialist_a2a"]
