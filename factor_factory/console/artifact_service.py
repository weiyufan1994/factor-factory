from __future__ import annotations

import json
import mimetypes
import os
import re
import stat
import struct
import zlib
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
    r"(?imx)"
    r"(?:\"|')?"
    r"(?:api[_-]?key|access[_-]?key|secret(?:[_-]?key)?|private[_-]?key|"
    r"auth(?:orization)?[_-]?token|bearer[_-]?token|password|passwd)"
    r"(?:\"|')?\s*[:=]\s*"
    r"(?:[\"']([^\"'\r\n]{8,})[\"']|([^\s,;#\]\)}]{8,}))"
)
_BEARER_SECRET = re.compile(
    r"(?i)\b(?:authorization\s*:\s*)?bearer\s+[a-z0-9._~+/=-]{12,}"
)
_AWS_ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
_INTERNAL_ABSOLUTE_PATH = re.compile(
    r"(?i)(?:file://|s3://|"
    r"(?:^|[\s\"'=:(])/(?:Users|home|srv|private|tmp|var/lib|root|etc|opt)/|"
    r"(?:^|[\s\"'=:(])[A-Za-z]:\\\\)"
)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_FORBIDDEN_CHUNKS = {b"eXIf", b"iCCP"}
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
    if resolved.suffix.lower() == ".png" and not _valid_public_png(resolved):
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
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size > max_file_bytes:
                raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
            chunks: list[bytes] = []
            remaining = max_file_bytes + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except (OSError, ValueError) as exc:
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE) from exc
    data = b"".join(chunks)
    if (
        len(data) > max_file_bytes
        or before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or len(data) != after.st_size
    ):
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
    extension = path.suffix.lower()
    if extension in TEXT_ARTIFACT_EXTENSIONS and _contains_secret_bytes(data, extension=extension):
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
    if extension == ".png" and not _valid_public_png_bytes(data):
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
    return data


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
        sample = path.read_bytes()
    except OSError:
        return True
    return _contains_secret_bytes(sample, extension=path.suffix.lower())


def _contains_secret_bytes(sample: bytes, *, extension: str) -> bool:
    text = sample.decode("utf-8", errors="ignore")
    if (
        _PRIVATE_KEY.search(text)
        or _BEARER_SECRET.search(text)
        or _AWS_ACCESS_KEY.search(text)
        or _INTERNAL_ABSOLUTE_PATH.search(text)
    ):
        return True
    for match in _SECRET_ASSIGNMENT.finditer(text):
        value = (match.group(1) or match.group(2) or "").strip().lower()
        if value not in _MASKED_VALUES and set(value) != {"*"}:
            return True
    if extension == ".json":
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False
        return _json_contains_secret(payload)
    return False


def _valid_public_png(path: Path) -> bool:
    try:
        payload = path.read_bytes()
    except OSError:
        return False
    return _valid_public_png_bytes(payload)


def _valid_public_png_bytes(payload: bytes) -> bool:
    if not payload.startswith(_PNG_SIGNATURE):
        return False
    offset = len(_PNG_SIGNATURE)
    saw_header = False
    saw_data = False
    saw_end = False
    while offset < len(payload):
        if offset + 12 > len(payload):
            return False
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(payload) or not re.fullmatch(rb"[A-Za-z]{4}", chunk_type):
            return False
        data = payload[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", payload[offset + 8 + length : chunk_end])[0]
        if zlib.crc32(chunk_type + data) & 0xFFFFFFFF != expected_crc:
            return False
        if chunk_type == b"IHDR":
            if saw_header or offset != len(_PNG_SIGNATURE) or length != 13:
                return False
            saw_header = True
        elif chunk_type == b"IDAT":
            saw_data = True
        elif chunk_type == b"IEND":
            if length != 0 or saw_end:
                return False
            saw_end = True
            offset = chunk_end
            break
        elif chunk_type in _PNG_FORBIDDEN_CHUNKS:
            return False
        elif chunk_type in {b"tEXt", b"iTXt", b"zTXt"}:
            text = data.decode("utf-8", errors="ignore")
            if (
                _PRIVATE_KEY.search(text)
                or _BEARER_SECRET.search(text)
                or _AWS_ACCESS_KEY.search(text)
                or _INTERNAL_ABSOLUTE_PATH.search(text)
                or _SECRET_ASSIGNMENT.search(text)
            ):
                return False
        offset = chunk_end
    return saw_header and saw_data and saw_end and offset == len(payload)


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
