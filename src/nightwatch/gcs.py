from __future__ import annotations

from pathlib import Path, PurePosixPath
from urllib.parse import urlparse


class GcsUriError(ValueError):
    pass


def parse_gs_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "gs" or not parsed.netloc or not parsed.path.strip("/"):
        raise GcsUriError("expected gs://bucket/object-or-prefix")
    if parsed.params or parsed.query or parsed.fragment:
        raise GcsUriError("GCS URI must not include params, query, or fragment")
    return parsed.netloc, parsed.path.lstrip("/")


def download_file(uri: str, destination: Path) -> None:
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise SystemExit("Cloud dependencies are missing. Run: uv sync --extra cloud") from exc
    bucket_name, object_name = parse_gs_uri(uri)
    destination.parent.mkdir(parents=True, exist_ok=True)
    storage.Client().bucket(bucket_name).blob(object_name).download_to_filename(destination)


def download_directory(uri: str, destination: Path) -> None:
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise SystemExit("Cloud dependencies are missing. Run: uv sync --extra cloud") from exc
    bucket_name, prefix = parse_gs_uri(uri)
    prefix = prefix.rstrip("/") + "/"
    blobs = list(storage.Client().list_blobs(bucket_name, prefix=prefix))
    if not blobs:
        raise GcsUriError(f"no objects found under {uri}")
    for blob in blobs:
        relative = PurePosixPath(blob.name.removeprefix(prefix))
        if not relative.parts or ".." in relative.parts:
            raise GcsUriError(f"unsafe object name under {uri}")
        local_path = destination.joinpath(*relative.parts)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(local_path)


def upload_directory(source: Path, uri: str) -> None:
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise SystemExit("Cloud dependencies are missing. Run: uv sync --extra cloud") from exc
    bucket_name, prefix = parse_gs_uri(uri)
    bucket = storage.Client().bucket(bucket_name)
    files = [path for path in source.rglob("*") if path.is_file() and not path.is_symlink()]
    if not files:
        raise GcsUriError(f"cannot upload empty directory {source}")
    for path in files:
        relative = path.relative_to(source).as_posix()
        object_name = str(PurePosixPath(prefix) / relative)
        bucket.blob(object_name).upload_from_filename(path)

