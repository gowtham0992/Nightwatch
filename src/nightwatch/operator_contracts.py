from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from google.api_core.exceptions import Conflict, NotFound, PreconditionFailed

from nightwatch.contracts import Suite
from nightwatch.datasets import canonical_prompt
from nightwatch.journal import JournalError
from nightwatch.model_config import validate_gemma_checkpoint


MAX_DATASET_BYTES = 2_000_000
MAX_DATASET_ROWS = 10_000
MAX_DATASET_COLUMNS = 32
MAX_CELL_CHARS = 4_000
MAX_LABELS = 16
MAX_CONTRACT_BYTES = 64 * 1024
GCS_TIMEOUT_SECONDS = 10.0

REGISTERED_BASELINES: dict[str, dict[str, Any]] = {
    "scam-v0-de1e6009-2d77e636-c0e947096d": {
        "model_id": "google/gemma-3-1b-it",
        "model_revision": "dcc83ea841ab6100d6b47a070329e1ba4cf78752",
        "labels": ("block", "caution", "verify", "routine"),
        "instruction": "Classify one received message by the safest immediate handling decision. Return exactly one label: block, caution, verify, or routine.",
        "prompt_style": "scam_message",
    },
    "classifier-1395040c-1e98fdcf-74d932a468": {
        "model_id": "google/gemma-3-270m-it",
        "model_revision": "ac82b4e820549b854eebf28ce6dedaf9fdfa17b3",
        "labels": ("defer", "investigate", "page_now"),
        "instruction": "Classify this production alert as page_now, investigate, or defer.",
        "prompt_style": "production_alert",
    },
}

_COLUMN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_ARTIFACT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_DATASET_ID = re.compile(r"^dataset-[a-f0-9]{24}$")
_CONTRACT_ID = re.compile(r"^contract-[a-f0-9]{24}$")


class OperatorContractError(ValueError):
    pass


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise OperatorContractError("value must be JSON serializable") from exc


def _clean_text(value: object, field: str, *, maximum: int = MAX_CELL_CHARS) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OperatorContractError(f"{field} must be a non-empty string")
    cleaned = value.strip()
    if len(cleaned) > maximum or any(ord(character) < 32 and character not in "\t\n\r" for character in cleaned):
        raise OperatorContractError(f"{field} is invalid or exceeds {maximum} characters")
    return cleaned


def _parse_csv(raw: bytes) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise OperatorContractError("CSV must be UTF-8 encoded") from exc
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if not reader.fieldnames:
            raise OperatorContractError("CSV must include a header row")
        if any(name is None or not _COLUMN.fullmatch(name) for name in reader.fieldnames):
            raise OperatorContractError("CSV contains an invalid column name")
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise OperatorContractError("CSV column names must be unique")
        return [dict(row) for row in reader]
    except csv.Error as exc:
        raise OperatorContractError("CSV is malformed") from exc


def _parse_jsonl(raw: bytes) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OperatorContractError("JSONL must be UTF-8 encoded") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OperatorContractError(f"JSONL line {line_number} is malformed") from exc
        if not isinstance(row, dict):
            raise OperatorContractError(f"JSONL line {line_number} must be an object")
        rows.append(row)
    return rows


@dataclass(frozen=True)
class FrozenDataset:
    dataset_id: str
    sha256: str
    file_format: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def canonical_bytes(self) -> bytes:
        return b"".join(_canonical_json_bytes(row) + b"\n" for row in self.rows)

    def summary(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "sha256": self.sha256,
            "file_format": self.file_format,
            "columns": list(self.columns),
            "row_count": self.row_count,
        }


def parse_uploaded_dataset(raw: bytes, file_format: str) -> FrozenDataset:
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_DATASET_BYTES:
        raise OperatorContractError(
            f"dataset must contain 1-{MAX_DATASET_BYTES} bytes"
        )
    normalized_format = str(file_format).lower().lstrip(".")
    if normalized_format == "csv":
        rows = _parse_csv(raw)
    elif normalized_format in {"jsonl", "ndjson"}:
        normalized_format = "jsonl"
        rows = _parse_jsonl(raw)
    else:
        raise OperatorContractError("dataset format must be CSV or JSONL")
    if not rows or len(rows) > MAX_DATASET_ROWS:
        raise OperatorContractError(
            f"dataset must contain 1-{MAX_DATASET_ROWS} rows"
        )
    columns = tuple(sorted(rows[0]))
    if not columns or len(columns) > MAX_DATASET_COLUMNS:
        raise OperatorContractError(
            f"dataset must contain 1-{MAX_DATASET_COLUMNS} columns"
        )
    if any(not _COLUMN.fullmatch(column) for column in columns):
        raise OperatorContractError("dataset contains an invalid column name")
    expected_columns = set(columns)
    normalized_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if set(row) != expected_columns:
            raise OperatorContractError(f"dataset row {index} has inconsistent columns")
        normalized: dict[str, Any] = {}
        for column in columns:
            value = row[column]
            if value is None:
                normalized[column] = ""
            elif isinstance(value, (str, int, float, bool)):
                rendered = str(value) if not isinstance(value, bool) else value
                if isinstance(rendered, str) and len(rendered) > MAX_CELL_CHARS:
                    raise OperatorContractError(
                        f"dataset row {index} column {column!r} exceeds {MAX_CELL_CHARS} characters"
                    )
                normalized[column] = rendered
            else:
                raise OperatorContractError(
                    f"dataset row {index} column {column!r} must be scalar"
                )
        normalized_rows.append(normalized)
    canonical = b"".join(_canonical_json_bytes(row) + b"\n" for row in normalized_rows)
    digest = hashlib.sha256(canonical).hexdigest()
    return FrozenDataset(
        dataset_id=f"dataset-{digest[:24]}",
        sha256=digest,
        file_format=normalized_format,
        columns=columns,
        rows=tuple(normalized_rows),
    )


@dataclass(frozen=True)
class FieldMapping:
    id_column: str
    text_column: str
    label_column: str
    suite_column: str
    safety_critical_column: str | None = None


@dataclass(frozen=True)
class ReleasePolicy:
    minimum_target_gain: float
    maximum_regression_drop: float
    minimum_safety_accuracy: float
    require_zero_critical_misses: bool
    require_complete_predictions: bool = True


@dataclass(frozen=True)
class ComputeLimits:
    rank: int
    epochs: float
    learning_rate: float
    seed: int
    maximum_training_attempts: int
    maximum_gpu_minutes: int


@dataclass(frozen=True)
class MissionContract:
    contract_id: str
    schema_version: int
    subject: str
    model_id: str
    model_revision: str
    baseline_artifact: str
    dataset_id: str
    dataset_sha256: str
    mapping: FieldMapping
    labels: tuple[str, ...]
    instruction: str
    policy: ReleasePolicy
    compute: ComputeLimits
    runtime: str = "modal"
    workflow: str = "generic_text_classification"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def public_summary(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "schema_version": self.schema_version,
            "subject": self.subject,
            "model": {"id": self.model_id, "revision": self.model_revision},
            "baseline_artifact": self.baseline_artifact,
            "dataset": {"dataset_id": self.dataset_id, "sha256": self.dataset_sha256},
            "mapping": asdict(self.mapping),
            "labels": list(self.labels),
            "instruction": self.instruction,
            "policy": asdict(self.policy),
            "compute": asdict(self.compute),
            "runtime": self.runtime,
            "workflow": self.workflow,
            "frozen": True,
        }


class OperatorStore(Protocol):
    def create_dataset(self, dataset: FrozenDataset) -> FrozenDataset: ...
    def read_dataset(self, dataset_id: str) -> FrozenDataset | None: ...
    def create_contract(self, contract: MissionContract) -> MissionContract: ...
    def read_contract(self, contract_id: str) -> MissionContract | None: ...


class InMemoryOperatorStore:
    """Test/local store with the same create-only semantics as the GCS store."""

    def __init__(self) -> None:
        self._datasets: dict[str, FrozenDataset] = {}
        self._contracts: dict[str, MissionContract] = {}

    def create_dataset(self, dataset: FrozenDataset) -> FrozenDataset:
        existing = self._datasets.get(dataset.dataset_id)
        if existing is not None and existing != dataset:
            raise OperatorContractError("dataset identity already contains different bytes")
        self._datasets[dataset.dataset_id] = dataset
        return dataset

    def read_dataset(self, dataset_id: str) -> FrozenDataset | None:
        return self._datasets.get(dataset_id)

    def create_contract(self, contract: MissionContract) -> MissionContract:
        mission_contract_from_dict(contract.to_dict())
        existing = self._contracts.get(contract.contract_id)
        if existing is not None and existing != contract:
            raise OperatorContractError("contract identity already contains different bytes")
        self._contracts[contract.contract_id] = contract
        return contract

    def read_contract(self, contract_id: str) -> MissionContract | None:
        return self._contracts.get(contract_id)


def _boolean_cell(value: object, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise OperatorContractError(f"{field} must contain true or false")


def _number(value: object, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OperatorContractError(f"{field} must be a number")
    parsed = float(value)
    if not minimum <= parsed <= maximum:
        raise OperatorContractError(f"{field} must be between {minimum} and {maximum}")
    return parsed


def build_mission_contract(value: object, dataset: FrozenDataset) -> MissionContract:
    if not isinstance(value, dict) or set(value) != {
        "baseline_artifact",
        "compute",
        "dataset_id",
        "instruction",
        "mapping",
        "model",
        "policy",
        "subject",
    }:
        raise OperatorContractError("mission contract fields are incomplete or unsupported")
    if value["dataset_id"] != dataset.dataset_id:
        raise OperatorContractError("mission contract dataset identity does not match")
    subject = _clean_text(value["subject"], "subject", maximum=120)
    instruction = _clean_text(value["instruction"], "instruction", maximum=500)
    artifact = _clean_text(value["baseline_artifact"], "baseline_artifact", maximum=128)
    if not _ARTIFACT.fullmatch(artifact):
        raise OperatorContractError("baseline_artifact is invalid")

    model = value["model"]
    if not isinstance(model, dict) or set(model) != {"id", "revision"}:
        raise OperatorContractError("model must contain exactly id and revision")
    model_id = _clean_text(model["id"], "model.id", maximum=128)
    model_revision = _clean_text(model["revision"], "model.revision", maximum=64)
    try:
        validate_gemma_checkpoint(model_id, model_revision)
    except ValueError as exc:
        raise OperatorContractError("model checkpoint is not supported") from exc
    baseline = REGISTERED_BASELINES.get(artifact)
    if baseline is None:
        raise OperatorContractError("baseline_artifact is not registered")
    if (
        baseline["model_id"] != model_id
        or baseline["model_revision"] != model_revision
        or baseline["instruction"] != instruction
    ):
        raise OperatorContractError(
            "baseline artifact, checkpoint, and instruction must match its registry"
        )

    raw_mapping = value["mapping"]
    allowed_mapping = {
        "id_column",
        "text_column",
        "label_column",
        "suite_column",
        "safety_critical_column",
    }
    if not isinstance(raw_mapping, dict) or not set(raw_mapping) <= allowed_mapping:
        raise OperatorContractError("mapping contains unsupported fields")
    required_mapping = allowed_mapping - {"safety_critical_column"}
    if not required_mapping <= set(raw_mapping):
        raise OperatorContractError("mapping is missing required fields")
    mapping_values: dict[str, str | None] = {}
    for field in allowed_mapping:
        raw = raw_mapping.get(field)
        if field == "safety_critical_column" and raw in {None, ""}:
            mapping_values[field] = None
            continue
        column = _clean_text(raw, f"mapping.{field}", maximum=64)
        if column not in dataset.columns:
            raise OperatorContractError(f"mapping.{field} is not a dataset column")
        mapping_values[field] = column
    mapping = FieldMapping(**mapping_values)  # type: ignore[arg-type]
    core_columns = {
        mapping.id_column,
        mapping.text_column,
        mapping.label_column,
        mapping.suite_column,
    }
    if len(core_columns) != 4:
        raise OperatorContractError("id, text, label, and suite mappings must be distinct")

    labels: set[str] = set()
    ids: set[str] = set()
    prompts: set[str] = set()
    suites: set[Suite] = set()
    for index, row in enumerate(dataset.rows, start=1):
        case_id = _clean_text(row[mapping.id_column], f"row {index} id", maximum=128)
        text = _clean_text(row[mapping.text_column], f"row {index} text")
        label = _clean_text(row[mapping.label_column], f"row {index} label", maximum=64)
        if not _COLUMN.fullmatch(label):
            raise OperatorContractError(f"row {index} label is invalid")
        try:
            suite = Suite(_clean_text(row[mapping.suite_column], f"row {index} suite", maximum=16))
        except ValueError as exc:
            raise OperatorContractError(
                f"row {index} suite must be target, regression, or safety"
            ) from exc
        if case_id in ids:
            raise OperatorContractError(f"dataset contains duplicate id {case_id!r}")
        fingerprint = canonical_prompt(text)
        if fingerprint in prompts:
            raise OperatorContractError("dataset contains duplicate canonical text")
        if mapping.safety_critical_column is not None:
            critical = _boolean_cell(
                row[mapping.safety_critical_column],
                f"row {index} safety critical",
            )
            if critical and suite is not Suite.SAFETY:
                raise OperatorContractError("safety-critical rows must belong to the safety suite")
        ids.add(case_id)
        prompts.add(fingerprint)
        labels.add(label)
        suites.add(suite)
    if suites != set(Suite):
        missing = ", ".join(sorted(suite.value for suite in set(Suite) - suites))
        raise OperatorContractError(f"dataset is missing required suites: {missing}")
    if not 2 <= len(labels) <= MAX_LABELS:
        raise OperatorContractError(f"dataset must contain 2-{MAX_LABELS} labels")
    if labels != set(baseline["labels"]):
        raise OperatorContractError("dataset labels do not match the registered baseline")

    raw_policy = value["policy"]
    if not isinstance(raw_policy, dict) or set(raw_policy) != {
        "maximum_regression_drop",
        "minimum_safety_accuracy",
        "minimum_target_gain",
        "require_zero_critical_misses",
    }:
        raise OperatorContractError("policy fields are incomplete or unsupported")
    if not isinstance(raw_policy["require_zero_critical_misses"], bool):
        raise OperatorContractError("require_zero_critical_misses must be boolean")
    policy = ReleasePolicy(
        minimum_target_gain=_number(raw_policy["minimum_target_gain"], "minimum_target_gain", 0, 1),
        maximum_regression_drop=_number(raw_policy["maximum_regression_drop"], "maximum_regression_drop", 0, 1),
        minimum_safety_accuracy=_number(raw_policy["minimum_safety_accuracy"], "minimum_safety_accuracy", 0, 1),
        require_zero_critical_misses=raw_policy["require_zero_critical_misses"],
    )

    raw_compute = value["compute"]
    if not isinstance(raw_compute, dict) or set(raw_compute) != {
        "epochs",
        "learning_rate",
        "maximum_gpu_minutes",
        "maximum_training_attempts",
        "rank",
        "seed",
    }:
        raise OperatorContractError("compute fields are incomplete or unsupported")
    rank = raw_compute["rank"]
    epochs = raw_compute["epochs"]
    learning_rate = raw_compute["learning_rate"]
    seed = raw_compute["seed"]
    attempts = raw_compute["maximum_training_attempts"]
    gpu_minutes = raw_compute["maximum_gpu_minutes"]
    if rank not in {4, 8, 16}:
        raise OperatorContractError("rank must be 4, 8, or 16")
    if epochs not in {1.0, 2.0, 3.0, 4.0}:
        raise OperatorContractError("epochs must be in the approved grid")
    if learning_rate not in {5e-5, 1e-4, 2e-4, 5e-4, 1e-3}:
        raise OperatorContractError("learning_rate must be in the approved grid")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**31 - 1:
        raise OperatorContractError("seed must be a non-negative 32-bit integer")
    if attempts != 1:
        raise OperatorContractError("maximum_training_attempts must be exactly 1")
    if isinstance(gpu_minutes, bool) or not isinstance(gpu_minutes, int) or not 1 <= gpu_minutes <= 20:
        raise OperatorContractError("maximum_gpu_minutes must be between 1 and 20")
    compute = ComputeLimits(
        rank=rank,
        epochs=epochs,
        learning_rate=learning_rate,
        seed=seed,
        maximum_training_attempts=attempts,
        maximum_gpu_minutes=gpu_minutes,
    )

    material = {
        "schema_version": 1,
        "subject": subject,
        "model_id": model_id,
        "model_revision": model_revision,
        "baseline_artifact": artifact,
        "dataset_id": dataset.dataset_id,
        "dataset_sha256": dataset.sha256,
        "mapping": asdict(mapping),
        "labels": tuple(baseline["labels"]),
        "instruction": instruction,
        "policy": asdict(policy),
        "compute": asdict(compute),
        "runtime": "modal",
        "workflow": "generic_text_classification",
    }
    digest = hashlib.sha256(_canonical_json_bytes(material)).hexdigest()
    return MissionContract(
        contract_id=f"contract-{digest[:24]}",
        schema_version=1,
        subject=subject,
        model_id=model_id,
        model_revision=model_revision,
        baseline_artifact=artifact,
        dataset_id=dataset.dataset_id,
        dataset_sha256=dataset.sha256,
        mapping=mapping,
        labels=tuple(baseline["labels"]),
        instruction=instruction,
        policy=policy,
        compute=compute,
    )


def mission_contract_from_dict(value: object) -> MissionContract:
    try:
        if not isinstance(value, dict):
            raise OperatorContractError("stored mission contract is malformed")
        contract = MissionContract(
            contract_id=value["contract_id"],
            schema_version=value["schema_version"],
            subject=value["subject"],
            model_id=value["model_id"],
            model_revision=value["model_revision"],
            baseline_artifact=value["baseline_artifact"],
            dataset_id=value["dataset_id"],
            dataset_sha256=value["dataset_sha256"],
            mapping=FieldMapping(**value["mapping"]),
            labels=tuple(value["labels"]),
            instruction=value["instruction"],
            policy=ReleasePolicy(**value["policy"]),
            compute=ComputeLimits(**value["compute"]),
            runtime=value["runtime"],
            workflow=value["workflow"],
        )
    except (KeyError, TypeError) as exc:
        if isinstance(exc, OperatorContractError):
            raise
        raise OperatorContractError("stored mission contract is malformed") from exc
    if not _CONTRACT_ID.fullmatch(contract.contract_id):
        raise OperatorContractError("stored mission contract ID is malformed")
    if not _DATASET_ID.fullmatch(contract.dataset_id) or not _SHA256.fullmatch(contract.dataset_sha256):
        raise OperatorContractError("stored mission dataset identity is malformed")
    material = contract.to_dict()
    supplied_id = material.pop("contract_id")
    digest = hashlib.sha256(_canonical_json_bytes(material)).hexdigest()
    if supplied_id != f"contract-{digest[:24]}":
        raise OperatorContractError("stored mission contract digest does not match")
    return contract


def contract_request(contract: MissionContract) -> dict[str, Any]:
    """Return the exact operator request whose validation creates ``contract``."""

    return {
        "baseline_artifact": contract.baseline_artifact,
        "compute": asdict(contract.compute),
        "dataset_id": contract.dataset_id,
        "instruction": contract.instruction,
        "mapping": asdict(contract.mapping),
        "model": {"id": contract.model_id, "revision": contract.model_revision},
        "policy": {
            "maximum_regression_drop": contract.policy.maximum_regression_drop,
            "minimum_safety_accuracy": contract.policy.minimum_safety_accuracy,
            "minimum_target_gain": contract.policy.minimum_target_gain,
            "require_zero_critical_misses": contract.policy.require_zero_critical_misses,
        },
        "subject": contract.subject,
    }


def revalidate_contract(contract: MissionContract, dataset: FrozenDataset) -> MissionContract:
    """Re-run semantic policy validation after loading immutable stored bytes."""

    rebuilt = build_mission_contract(contract_request(contract), dataset)
    if rebuilt != contract:
        raise OperatorContractError("stored mission contract failed semantic validation")
    return contract


def mission_manifest_from_contract(contract: MissionContract):
    """Adapt a frozen operator contract to the durable mission lifecycle."""

    from nightwatch.mission_orchestrator import MissionManifest

    return MissionManifest(
        manifest_id=contract.contract_id,
        subject=contract.subject,
        trigger_artifact_name=contract.baseline_artifact,
        observed_safety_accuracy=0.0,
        required_safety_accuracy=contract.policy.minimum_safety_accuracy,
        model_id=contract.model_id,
        model_revision=contract.model_revision,
        seed=contract.compute.seed,
        lora_rank=contract.compute.rank,
        epochs=contract.compute.epochs,
        learning_rate=contract.compute.learning_rate,
        maximum_training_attempts=contract.compute.maximum_training_attempts,
        maximum_gpu_minutes=contract.compute.maximum_gpu_minutes,
        workflow=contract.workflow,
        dataset_id=contract.dataset_id,
        dataset_sha256=contract.dataset_sha256,
    )


class GCSOperatorStore:
    """Create-only storage for canonical datasets and frozen mission contracts."""

    def __init__(self, bucket: Any) -> None:
        self._bucket = bucket

    @classmethod
    def from_default(cls, *, project: str | None, bucket_name: str) -> GCSOperatorStore:
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise RuntimeError("install the 'cloud' extra to store operator contracts") from exc
        return cls(storage.Client(project=project).bucket(bucket_name))

    @staticmethod
    def _dataset_name(dataset_id: str) -> str:
        if not _DATASET_ID.fullmatch(dataset_id):
            raise OperatorContractError("dataset ID is malformed")
        return f"operator/datasets/{dataset_id}.jsonl"

    @staticmethod
    def _contract_name(contract_id: str) -> str:
        if not _CONTRACT_ID.fullmatch(contract_id):
            raise OperatorContractError("contract ID is malformed")
        return f"operator/contracts/{contract_id}.json"

    def create_dataset(self, dataset: FrozenDataset) -> FrozenDataset:
        raw = dataset.canonical_bytes()
        if hashlib.sha256(raw).hexdigest() != dataset.sha256:
            raise OperatorContractError("dataset digest does not match its canonical bytes")
        blob = self._bucket.blob(self._dataset_name(dataset.dataset_id))
        try:
            blob.upload_from_string(
                raw,
                content_type="application/x-ndjson",
                if_generation_match=0,
                timeout=GCS_TIMEOUT_SECONDS,
            )
        except (Conflict, PreconditionFailed):
            existing = self.read_dataset(dataset.dataset_id)
            if existing is None or existing.sha256 != dataset.sha256:
                raise OperatorContractError("dataset identity already contains different bytes")
            return existing
        return dataset

    def read_dataset(self, dataset_id: str) -> FrozenDataset | None:
        try:
            raw = self._bucket.blob(self._dataset_name(dataset_id)).download_as_bytes(
                timeout=GCS_TIMEOUT_SECONDS
            )
        except NotFound:
            return None
        dataset = parse_uploaded_dataset(raw, "jsonl")
        if dataset.dataset_id != dataset_id:
            raise OperatorContractError("stored dataset digest does not match its object path")
        return dataset

    def create_contract(self, contract: MissionContract) -> MissionContract:
        validated = mission_contract_from_dict(contract.to_dict())
        raw = _canonical_json_bytes(validated.to_dict())
        if len(raw) > MAX_CONTRACT_BYTES:
            raise OperatorContractError("mission contract is too large")
        blob = self._bucket.blob(self._contract_name(contract.contract_id))
        try:
            blob.upload_from_string(
                raw,
                content_type="application/json",
                if_generation_match=0,
                timeout=GCS_TIMEOUT_SECONDS,
            )
        except (Conflict, PreconditionFailed):
            existing = self.read_contract(contract.contract_id)
            if existing != contract:
                raise OperatorContractError("contract identity already contains different bytes")
            return existing
        return contract

    def read_contract(self, contract_id: str) -> MissionContract | None:
        try:
            raw = self._bucket.blob(self._contract_name(contract_id)).download_as_bytes(
                timeout=GCS_TIMEOUT_SECONDS
            )
        except NotFound:
            return None
        if not raw or len(raw) > MAX_CONTRACT_BYTES:
            raise OperatorContractError("stored mission contract has an invalid size")
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise OperatorContractError("stored mission contract is malformed") from exc
        contract = mission_contract_from_dict(value)
        if contract.contract_id != contract_id:
            raise OperatorContractError("stored contract identity does not match its object path")
        return contract


def require_contract(store: OperatorStore, contract_id: str) -> MissionContract:
    try:
        contract = store.read_contract(contract_id)
    except OperatorContractError as exc:
        raise JournalError("mission contract failed integrity validation") from exc
    if contract is None:
        raise JournalError("mission contract is not registered")
    try:
        dataset = store.read_dataset(contract.dataset_id)
        if dataset is None:
            raise OperatorContractError("mission dataset is not registered")
        return revalidate_contract(contract, dataset)
    except OperatorContractError as exc:
        raise JournalError("mission contract failed semantic validation") from exc
