from __future__ import annotations

import json
import hashlib
import mimetypes
import os
import re
import shutil
import stat
import struct
import uuid
import zlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from factor_factory.console.secret_safety import contains_secret_values


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
    r"auth(?:orization)?[_-]?token|bearer[_-]?token|session[_-]?token|"
    r"access[_-]?token|refresh[_-]?token|id[_-]?token|aws[_-]?session[_-]?token|"
    r"token|password|passwd)"
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


def publish_official_artifacts(
    workspace_root: str | Path,
    public_job_root: str | Path,
    *,
    role_artifact_ids: dict[str, str],
    identity: dict[str, str],
    denied_values: tuple[str, ...] = (),
    max_file_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
) -> tuple[str, list[SafeArtifact]]:
    """Copy only selected formal roles into an immutable public artifact set."""

    workspace = _workspace_root(workspace_root)
    public_base = _prepare_public_job_root(public_job_root)
    publication_id = f"pub_{uuid.uuid4().hex}"
    publication_root = public_base / publication_id
    publication_root.mkdir(mode=0o750)
    published: list[SafeArtifact] = []
    records: list[dict[str, object]] = []
    omitted: list[dict[str, str]] = []
    seen: set[str] = set()
    try:
        for role, artifact_id in sorted(role_artifact_ids.items()):
            if artifact_id in seen:
                continue
            seen.add(artifact_id)
            try:
                source_description = describe_artifact(
                    workspace,
                    artifact_id,
                    max_file_bytes=max_file_bytes,
                    denied_values=denied_values,
                )
                data = read_artifact_bytes(
                    workspace,
                    artifact_id,
                    max_file_bytes=max_file_bytes,
                    denied_values=denied_values,
                )
            except ArtifactAccessError as exc:
                omitted.append(
                    {
                        "role": role,
                        "artifact_id": artifact_id,
                        "reason": str(exc),
                    }
                )
                continue
            relative = _validate_artifact_id(artifact_id)
            destination = publication_root.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
            destination.parent.chmod(0o750)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(destination, flags, 0o640)
            try:
                offset = 0
                while offset < len(data):
                    offset += os.write(descriptor, data[offset:])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            destination.chmod(0o640)
            public_description = describe_artifact(
                publication_root,
                artifact_id,
                max_file_bytes=max_file_bytes,
                denied_values=denied_values,
            )
            if (
                public_description.size_bytes != source_description.size_bytes
                or read_artifact_bytes(
                    publication_root,
                    artifact_id,
                    max_file_bytes=max_file_bytes,
                    denied_values=denied_values,
                ) != data
            ):
                raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
            published.append(public_description)
            records.append(
                {
                    "role": role,
                    "artifact_id": artifact_id,
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        manifest = {
            "version": "factorforge_console_public_artifact_manifest_v1",
            "publication_id": publication_id,
            "identity": dict(identity),
            "artifacts": records,
            "omitted_artifacts": omitted,
        }
        manifest_path = publication_root / ".publication.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_path.chmod(0o640)
        for published_path in sorted(publication_root.rglob("*"), reverse=True):
            published_path.chmod(0o550 if published_path.is_dir() else 0o440)
        publication_root.chmod(0o550)
    except Exception:
        shutil.rmtree(publication_root, ignore_errors=True)
        raise
    return publication_id, sorted(published, key=lambda item: item.artifact_id)


def read_verified_publication_artifact(
    publication_root: str | Path,
    artifact_id: str,
    *,
    max_file_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
) -> tuple[SafeArtifact, bytes]:
    root = _workspace_root(publication_root)
    try:
        manifest_descriptor = _open_artifact_descriptor(
            root,
            _validate_artifact_id(".publication.json"),
        )
        try:
            before = os.fstat(manifest_descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size > 2 * 1024 * 1024
            ):
                raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
            manifest_data = b""
            while len(manifest_data) <= 2 * 1024 * 1024:
                chunk = os.read(manifest_descriptor, 64 * 1024)
                if not chunk:
                    break
                manifest_data += chunk
            after = os.fstat(manifest_descriptor)
            if (
                len(manifest_data) != before.st_size
                or before.st_ino != after.st_ino
                or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
            ):
                raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
        finally:
            os.close(manifest_descriptor)
        manifest = json.loads(manifest_data)
    except (ArtifactAccessError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE) from exc
    records = manifest.get("artifacts") if isinstance(manifest, dict) else None
    matches = [
        item
        for item in (records or [])
        if isinstance(item, dict) and item.get("artifact_id") == artifact_id
    ]
    if (
        manifest.get("version") != "factorforge_console_public_artifact_manifest_v1"
        or manifest.get("publication_id") != root.name
        or not isinstance(records, list)
        or len(records) > 300
        or len(matches) != 1
    ):
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
    expected = matches[0]
    description = describe_artifact(root, artifact_id, max_file_bytes=max_file_bytes)
    data = read_artifact_bytes(root, artifact_id, max_file_bytes=max_file_bytes)
    if (
        expected.get("size_bytes") != len(data)
        or not re.fullmatch(r"[0-9a-f]{64}", str(expected.get("sha256") or ""))
        or expected.get("sha256") != hashlib.sha256(data).hexdigest()
    ):
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
    return description, data


def _prepare_public_job_root(public_job_root: str | Path) -> Path:
    requested = Path(public_job_root).expanduser().absolute()
    if ".." in requested.parts or not re.fullmatch(r"job_[a-f0-9]{10}", requested.name):
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_PATH_INVALID)
    parent = requested.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    current = Path(parent.anchor)
    for part in parent.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
    parent.chmod(0o750)
    parent_metadata = parent.stat()
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.geteuid()
        or parent_metadata.st_mode & 0o022
    ):
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    parent_descriptor = os.open(parent, directory_flags)
    try:
        try:
            os.mkdir(requested.name, 0o750, dir_fd=parent_descriptor)
        except FileExistsError:
            pass
        job_descriptor = os.open(requested.name, directory_flags, dir_fd=parent_descriptor)
        try:
            metadata = os.fstat(job_descriptor)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o022
            ):
                raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
        finally:
            os.close(job_descriptor)
    finally:
        os.close(parent_descriptor)
    requested.chmod(0o750)
    return requested


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
    denied_values: tuple[str, ...] = (),
) -> SafeArtifact:
    path = resolve_artifact_path(
        workspace_root,
        artifact_id,
        max_file_bytes=max_file_bytes,
        denied_values=denied_values,
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
    denied_values: tuple[str, ...] = (),
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
    if resolved.suffix.lower() in TEXT_ARTIFACT_EXTENSIONS and _contains_secret(
        resolved,
        denied_values=denied_values,
    ):
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
    if resolved.suffix.lower() == ".png" and not _valid_public_png(resolved):
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
    return resolved


def read_artifact_bytes(
    workspace_root: str | Path,
    artifact_id: str,
    *,
    max_file_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
    denied_values: tuple[str, ...] = (),
) -> bytes:
    root = _workspace_root(workspace_root)
    relative = _validate_artifact_id(artifact_id)
    if not _safe_artifact_name(relative):
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
    extension = relative.suffix.lower()
    if extension not in SAFE_ARTIFACT_EXTENSIONS:
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_TYPE_FORBIDDEN)
    try:
        descriptor = _open_artifact_descriptor(root, relative)
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
    if _contains_denied_values(data, denied_values):
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE)
    if extension in TEXT_ARTIFACT_EXTENSIONS and _contains_secret_bytes(
        data,
        extension=extension,
        denied_values=denied_values,
    ):
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
    if any(any(ord(character) < 32 or ord(character) == 127 for character in part) for part in relative.parts):
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_PATH_INVALID)
    return relative


def _open_artifact_descriptor(root: Path, relative: PurePosixPath) -> int:
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptors: list[int] = []
    try:
        current = os.open(root, directory_flags)
        descriptors.append(current)
        for part in relative.parts[:-1]:
            current = os.open(part, directory_flags, dir_fd=current)
            descriptors.append(current)
        descriptor = os.open(relative.parts[-1], file_flags, dir_fd=current)
    except OSError as exc:
        raise ArtifactAccessError(BLOCK_FACTORFORGE_CONSOLE_ARTIFACT_UNSAFE) from exc
    finally:
        for item in reversed(descriptors):
            try:
                os.close(item)
            except OSError:
                pass
    return descriptor


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


def _contains_secret(path: Path, *, denied_values: tuple[str, ...] = ()) -> bool:
    try:
        sample = path.read_bytes()
    except OSError:
        return True
    return _contains_secret_bytes(
        sample,
        extension=path.suffix.lower(),
        denied_values=denied_values,
    )


def _contains_secret_bytes(
    sample: bytes,
    *,
    extension: str,
    denied_values: tuple[str, ...] = (),
) -> bool:
    if _contains_denied_values(sample, denied_values):
        return True
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
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if _contains_denied_values(canonical, denied_values):
            return True
        return _json_contains_secret(payload)
    return False


def _contains_denied_values(sample: bytes, denied_values: tuple[str, ...]) -> bool:
    return contains_secret_values(sample, denied_values)


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
                "token",
                "sessiontoken",
                "awssessiontoken",
                "accesstoken",
                "refreshtoken",
                "idtoken",
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
