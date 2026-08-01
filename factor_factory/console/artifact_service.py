from __future__ import annotations

import json
import mimetypes
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


SAFE_ARTIFACT_EXTENSIONS = frozenset(
    {".json", ".md", ".txt", ".csv", ".png", ".svg", ".html"}
)
TEXT_ARTIFACT_EXTENSIONS = frozenset(
    {".json", ".md", ".txt", ".csv", ".svg", ".html"}
)
DEFAULT_MAX_ARTIFACT_BYTES = 25 * 1024 * 1024
SECRET_SCAN_BYTES = 2 * 1024 * 1024

BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_PATH_INVALID = (
    "BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_PATH_INVALID"
)
BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_OUTSIDE_WORKSPACE = (
    "BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_OUTSIDE_WORKSPACE"
)
BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_TYPE_FORBIDDEN = (
    "BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_TYPE_FORBIDDEN"
)
BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE = (
    "BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE"
)

_PATH_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")
_SENSITIVE_NAME = re.compile(
    r"(?:^|[^a-z0-9])(?:"
    r"raw|logs?|stdout|stderr|trace|debug|"
    r"secrets?|credentials?|password|passwd|"
    r"api[_-]?keys?|access[_-]?keys?|secret[_-]?keys?|private[_-]?keys?|"
    r"auth[_-]?tokens?|bearer[_-]?tokens?"
    r")(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?ix)"
    r"(?:\"|')?"
    r"(?:api[_-]?key|access[_-]?key|secret(?:[_-]?key)?|private[_-]?key|"
    r"auth(?:orization)?[_-]?token|bearer[_-]?token|password|passwd)"
    r"(?:\"|')?\s*[:=]\s*(?:\"|')([^\"'\r\n]{8,})(?:\"|')"
)
_BEARER_SECRET = re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[a-z0-9._~+/=-]{12,}")
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
_INTERNAL_ABSOLUTE_PATH = re.compile(
    r"(?:^|[\s\"'=:(])(?:/Users/|/home/|/srv/|/private/tmp/|/tmp/|[A-Za-z]:\\\\)"
)
_MASKED_VALUES = {
    "<redacted>",
    "redacted",
    "<masked>",
    "masked",
    "********",
    "************",
    "changeme",
    "example",
    "placeholder",
}


class ArtifactAccessError(ValueError):
    """Raised when a Console artifact is not safe to expose."""


@dataclass(frozen=True)
class SafeArtifact:
    artifact_id: str
    media_type: str
    size_bytes: int
    modified_at_utc: str
    content_disposition: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def list_safe_artifacts(
    workspace_root: str | Path,
    *,
    max_file_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
) -> list[SafeArtifact]:
    """List downloadable artifacts without exposing host filesystem paths."""

    root = _workspace_root(workspace_root)
    artifacts: list[SafeArtifact] = []
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if _safe_path_name(name)
            and not (directory_path / name).is_symlink()
        )
        for file_name in sorted(file_names):
            candidate = directory_path / file_name
            if candidate.is_symlink() or not candidate.is_file():
                continue
            artifact_id = candidate.relative_to(root).as_posix()
            try:
                artifacts.append(
                    describe_artifact(
                        root,
                        artifact_id,
                        max_file_bytes=max_file_bytes,
                    )
                )
            except ArtifactAccessError:
                continue
    return sorted(artifacts, key=lambda item: item.artifact_id)


def list_artifact_ids(
    workspace_root: str | Path,
    *,
    max_file_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
) -> list[str]:
    return [
        item.artifact_id
        for item in list_safe_artifacts(
            workspace_root,
            max_file_bytes=max_file_bytes,
        )
    ]


def describe_artifact(
    workspace_root: str | Path,
    artifact_id: str,
    *,
    max_file_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
) -> SafeArtifact:
    path = resolve_artifact_path(
        workspace_root,
        artifact_id,
        max_file_bytes=max_file_bytes,
    )
    stat = path.stat()
    extension = path.suffix.lower()
    media_type = mimetypes.types_map.get(extension) or "application/octet-stream"
    if extension == ".md":
        media_type = "text/markdown"
    elif extension == ".json":
        media_type = "application/json"
    elif extension == ".svg":
        media_type = "image/svg+xml"
    return SafeArtifact(
        artifact_id=_validate_artifact_id(artifact_id).as_posix(),
        media_type=media_type,
        size_bytes=stat.st_size,
        modified_at_utc=datetime.fromtimestamp(
            stat.st_mtime,
            tz=timezone.utc,
        ).isoformat().replace("+00:00", "Z"),
        # Active document types are downloadable but must not execute in Console origin.
        content_disposition="attachment" if extension in {".html", ".svg"} else "inline",
    )


def resolve_artifact_path(
    workspace_root: str | Path,
    artifact_id: str,
    *,
    max_file_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
) -> Path:
    """Resolve an artifact ID for backend use after strict containment checks."""

    root = _workspace_root(workspace_root)
    relative = _validate_artifact_id(artifact_id)
    candidate = root.joinpath(*relative.parts)
    _reject_symlink_segments(root, candidate)
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise ArtifactAccessError(
            BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_PATH_INVALID
        ) from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ArtifactAccessError(
            BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_OUTSIDE_WORKSPACE
        ) from exc
    if not resolved.is_file():
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_PATH_INVALID)
    if not _safe_artifact_name(relative):
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
    if resolved.suffix.lower() not in SAFE_ARTIFACT_EXTENSIONS:
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_TYPE_FORBIDDEN)
    size = resolved.stat().st_size
    if size > max_file_bytes:
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
    if resolved.suffix.lower() in TEXT_ARTIFACT_EXTENSIONS and _contains_secret(resolved):
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
    return resolved


def read_artifact_bytes(
    workspace_root: str | Path,
    artifact_id: str,
    *,
    max_file_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
) -> bytes:
    path = resolve_artifact_path(
        workspace_root,
        artifact_id,
        max_file_bytes=max_file_bytes,
    )
    return path.read_bytes()


def _workspace_root(workspace_root: str | Path) -> Path:
    try:
        root = Path(workspace_root).expanduser().resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise ArtifactAccessError(
            BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_PATH_INVALID
        ) from exc
    if not root.is_dir():
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_PATH_INVALID)
    return root


def _validate_artifact_id(artifact_id: str) -> PurePosixPath:
    if not isinstance(artifact_id, str) or not artifact_id or "\x00" in artifact_id:
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_PATH_INVALID)
    if "\\" in artifact_id:
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_PATH_INVALID)
    relative = PurePosixPath(artifact_id)
    if relative.is_absolute() or artifact_id.startswith(("/", "~")):
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_PATH_INVALID)
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_PATH_INVALID)
    return relative


def _reject_symlink_segments(root: Path, candidate: Path) -> None:
    current = root
    for part in candidate.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)


def _safe_path_name(name: str) -> bool:
    return bool(name) and not name.startswith(".") and not _SENSITIVE_NAME.search(name)


def _safe_artifact_name(relative: PurePosixPath) -> bool:
    if any(not _safe_path_name(part) for part in relative.parts):
        return False
    # Tokenization catches names such as step1_llm_raw__primary.json while not
    # confusing words such as drawdown with the standalone token "raw".
    tokens = {
        token
        for part in relative.parts
        for token in _PATH_TOKEN_SPLIT.split(part.lower())
        if token
    }
    return not tokens.intersection(
        {
            "raw",
            "log",
            "logs",
            "stdout",
            "stderr",
            "trace",
            "debug",
            "secret",
            "secrets",
            "credential",
            "credentials",
            "password",
            "passwd",
        }
    )


def _contains_secret(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            sample = handle.read(SECRET_SCAN_BYTES)
        text = sample.decode("utf-8", errors="ignore")
    except OSError:
        return True
    if _PRIVATE_KEY.search(text) or _BEARER_SECRET.search(text) or _INTERNAL_ABSOLUTE_PATH.search(text):
        return True
    for match in _SECRET_ASSIGNMENT.finditer(text):
        value = match.group(1).strip().lower()
        if value not in _MASKED_VALUES and set(value) != {"*"}:
            return True
    if path.suffix.lower() == ".json" and len(sample) < SECRET_SCAN_BYTES:
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False
        return _json_contains_secret(payload)
    return False


def _json_contains_secret(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in {
                "apikey",
                "accesskey",
                "accesskeyid",
                "secret",
                "secretkey",
                "privatekey",
                "authtoken",
                "authorizationtoken",
                "password",
                "passwd",
            } and _looks_like_secret_value(child):
                return True
            if _json_contains_secret(child):
                return True
    elif isinstance(value, list):
        return any(_json_contains_secret(child) for child in value)
    return False


def _looks_like_secret_value(value: object) -> bool:
    if value is None:
        return False
    if not isinstance(value, str):
        return bool(value)
    normalized = value.strip().lower()
    return bool(normalized) and normalized not in _MASKED_VALUES and set(normalized) != {"*"}
