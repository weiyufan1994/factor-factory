from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PDF_MEDIA_TYPE = "application/pdf"
MAX_PDF_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 600
MAX_EXTRACTED_TEXT_CHARS = 300_000
PDF_EXTRACTION_TIMEOUT_SECONDS = 60
BLOCK_PDF_UPLOAD_INVALID = "BLOCK_FACTORFORGE_CONSOLE_PDF_UPLOAD_INVALID"
BLOCK_PDF_EXTRACTION_FAILED = "BLOCK_FACTORFORGE_CONSOLE_PDF_EXTRACTION_FAILED"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_original_filename(value: str) -> str:
    normalized = str(value or "").replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1].strip()
    if (
        not name
        or len(name) > 180
        or name in {".", ".."}
        or Path(name).suffix.lower() != ".pdf"
        or any(ord(character) < 32 for character in name)
    ):
        raise ValueError(f"{BLOCK_PDF_UPLOAD_INVALID}: invalid PDF filename")
    return name


@dataclass(frozen=True)
class ResearchAttachmentUpload:
    original_filename: str
    media_type: str
    data: bytes

    def __post_init__(self) -> None:
        name = safe_original_filename(self.original_filename)
        media_type = str(self.media_type or "").split(";", 1)[0].strip().lower()
        payload = bytes(self.data)
        if media_type not in {PDF_MEDIA_TYPE, "application/octet-stream"}:
            raise ValueError(f"{BLOCK_PDF_UPLOAD_INVALID}: only PDF uploads are accepted")
        if not payload or len(payload) > MAX_PDF_UPLOAD_BYTES:
            raise ValueError(
                f"{BLOCK_PDF_UPLOAD_INVALID}: PDF must be between 1 byte and "
                f"{MAX_PDF_UPLOAD_BYTES} bytes"
            )
        if not payload.startswith(b"%PDF-"):
            raise ValueError(f"{BLOCK_PDF_UPLOAD_INVALID}: file signature is not PDF")
        object.__setattr__(self, "original_filename", name)
        object.__setattr__(self, "media_type", PDF_MEDIA_TYPE)
        object.__setattr__(self, "data", payload)

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @property
    def sha256(self) -> str:
        return sha256_bytes(self.data)


@dataclass(frozen=True)
class ResearchAttachment:
    attachment_id: str
    job_id: str
    original_filename: str
    media_type: str
    size_bytes: int
    sha256: str
    relative_path: str
    created_at_utc: str

    def __post_init__(self) -> None:
        safe_original_filename(self.original_filename)
        if not re.fullmatch(r"att_[a-f0-9]{16}", self.attachment_id):
            raise ValueError("invalid attachment_id")
        if not re.fullmatch(r"job_[a-f0-9]{10}", self.job_id):
            raise ValueError("invalid attachment job_id")
        if self.media_type != PDF_MEDIA_TYPE:
            raise ValueError("invalid attachment media_type")
        if not 0 < int(self.size_bytes) <= MAX_PDF_UPLOAD_BYTES:
            raise ValueError("invalid attachment size")
        if not re.fullmatch(r"[a-f0-9]{64}", self.sha256):
            raise ValueError("invalid attachment sha256")
        relative = Path(self.relative_path)
        expected = Path("uploads") / self.job_id / f"{self.attachment_id}.pdf"
        if relative.is_absolute() or ".." in relative.parts or relative != expected:
            raise ValueError("invalid attachment relative_path")

    def to_dict(self, *, public: bool = False) -> dict[str, Any]:
        payload = asdict(self)
        if public:
            payload.pop("relative_path", None)
        return payload


def write_bytes_atomic(path: Path, data: bytes, *, root: Path) -> None:
    resolved_root = Path(root).resolve(strict=True)
    destination = Path(path)
    try:
        destination.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("binary destination escapes root") from exc
    cursor = resolved_root
    for part in destination.relative_to(resolved_root).parts[:-1]:
        cursor = cursor / part
        if not cursor.exists() and not cursor.is_symlink():
            cursor.mkdir(mode=0o770)
        if cursor.is_symlink() or not cursor.is_dir():
            raise ValueError("binary destination parent is unsafe")
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise ValueError("binary destination is unsafe")
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o640)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def read_verified_file(
    path: Path,
    *,
    root: Path,
    expected_size: int,
    expected_sha256: str,
) -> bytes:
    resolved_root = Path(root).resolve(strict=True)
    candidate = Path(path)
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("attachment path escapes its store") from exc
    cursor = resolved_root
    relative = candidate.relative_to(resolved_root)
    for part in relative.parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink() or not cursor.is_dir():
            raise ValueError("attachment parent is unsafe")
    resolved_candidate = candidate.resolve(strict=True)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("attachment resolves outside its store") from exc
    metadata = resolved_candidate.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError("attachment is not a safe regular file")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(resolved_candidate, flags)
    with os.fdopen(descriptor, "rb", closefd=True) as handle:
        data = handle.read(MAX_PDF_UPLOAD_BYTES + 1)
    if len(data) != int(expected_size) or sha256_bytes(data) != expected_sha256:
        raise ValueError("attachment integrity check failed")
    return data


def extract_pdf_markdown(pdf_path: Path, *, original_filename: str) -> dict[str, Any]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - production dependency preflighted.
        raise RuntimeError(f"{BLOCK_PDF_EXTRACTION_FAILED}: pypdf is unavailable") from exc
    try:
        reader = PdfReader(str(pdf_path), strict=False)
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise ValueError("encrypted PDF requires a password")
        page_count = len(reader.pages)
        if page_count < 1 or page_count > MAX_PDF_PAGES:
            raise ValueError(f"PDF page count must be between 1 and {MAX_PDF_PAGES}")
        chunks = [
            f"# Uploaded report: {safe_original_filename(original_filename)}",
            "",
            "The page markers below are generated by the Factor Forge Host.",
        ]
        extracted_chars = 0
        extracted_pages = 0
        truncated = False
        for page_number, page in enumerate(reader.pages, start=1):
            text = str(page.extract_text() or "").replace("\x00", "").strip()
            if not text:
                continue
            remaining = MAX_EXTRACTED_TEXT_CHARS - extracted_chars
            if remaining <= 0:
                truncated = True
                break
            if len(text) > remaining:
                text = text[:remaining]
                truncated = True
            chunks.extend(
                [
                    "",
                    f"<!-- factorforge-pdf-page: {page_number} -->",
                    f"## Page {page_number}",
                    "",
                    text,
                ]
            )
            extracted_chars += len(text)
            extracted_pages += 1
            if truncated:
                break
        if extracted_chars == 0:
            raise ValueError("PDF contains no extractable text; OCR is not available in this pilot")
    except Exception as exc:
        if isinstance(exc, RuntimeError) and str(exc).startswith(BLOCK_PDF_EXTRACTION_FAILED):
            raise
        raise RuntimeError(f"{BLOCK_PDF_EXTRACTION_FAILED}: {exc}") from exc
    markdown = "\n".join(chunks).rstrip() + "\n"
    return {
        "markdown": markdown,
        "page_count": page_count,
        "extracted_page_count": extracted_pages,
        "extracted_char_count": extracted_chars,
        "truncated": truncated,
        "backend": "pypdf",
    }


def extract_pdf_markdown_isolated(
    pdf_path: Path,
    *,
    original_filename: str,
) -> dict[str, Any]:
    repository_root = Path(__file__).resolve().parents[2]
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(repository_root),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
    }
    try:
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "factor_factory.console.report_upload",
                "--extract",
                str(Path(pdf_path)),
                "--original-filename",
                safe_original_filename(original_filename),
            ],
            cwd=repository_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=PDF_EXTRACTION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{BLOCK_PDF_EXTRACTION_FAILED}: extraction exceeded "
            f"{PDF_EXTRACTION_TIMEOUT_SECONDS} seconds"
        ) from exc
    if process.returncode != 0:
        detail = (process.stderr or "PDF extraction subprocess failed").strip()[-500:]
        raise RuntimeError(f"{BLOCK_PDF_EXTRACTION_FAILED}: {detail}")
    try:
        payload = json.loads(process.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"{BLOCK_PDF_EXTRACTION_FAILED}: extractor returned invalid output"
        ) from exc
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("markdown"), str)
        or len(payload["markdown"]) > MAX_EXTRACTED_TEXT_CHARS + 32_000
        or not isinstance(payload.get("page_count"), int)
        or not isinstance(payload.get("extracted_page_count"), int)
        or not isinstance(payload.get("extracted_char_count"), int)
        or payload.get("backend") != "pypdf"
    ):
        raise RuntimeError(
            f"{BLOCK_PDF_EXTRACTION_FAILED}: extractor output failed validation"
        )
    return payload


def _main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--extract", type=Path, required=True)
    parser.add_argument("--original-filename", required=True)
    args = parser.parse_args()
    try:
        payload = extract_pdf_markdown(
            args.extract,
            original_filename=args.original_filename,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the parent API.
    raise SystemExit(_main())
