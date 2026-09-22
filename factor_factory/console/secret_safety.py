from __future__ import annotations

import base64
import re
from collections.abc import Iterable


_UNICODE_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")


def secret_text_variants(raw: str) -> tuple[str, ...]:
    if len(raw) < 8:
        return ()
    encoded = raw.encode("utf-8")
    standard = base64.b64encode(encoded).decode("ascii")
    urlsafe = base64.urlsafe_b64encode(encoded).decode("ascii")
    return tuple(
        sorted(
            {raw, standard, standard.rstrip("="), urlsafe, urlsafe.rstrip("=")},
            key=len,
            reverse=True,
        )
    )


def decode_unicode_escapes(text: str) -> str:
    return _UNICODE_ESCAPE.sub(lambda match: chr(int(match.group(1), 16)), text)


def contains_secret_values(sample: bytes | str, values: Iterable[str]) -> bool:
    text = sample.decode("utf-8", errors="ignore") if isinstance(sample, bytes) else sample
    candidates = (text, decode_unicode_escapes(text))
    for raw in values:
        variants = secret_text_variants(str(raw))
        if variants and any(variant in candidate for candidate in candidates for variant in variants):
            return True
    return False


def redact_secret_values(
    text: str,
    values: Iterable[str],
    *,
    replacement: str,
) -> str:
    output = text
    normalized = tuple(str(raw) for raw in values if len(str(raw)) >= 8)
    for raw in sorted(normalized, key=len, reverse=True):
        for variant in secret_text_variants(raw):
            output = output.replace(variant, replacement)
    if contains_secret_values(output, normalized):
        return replacement
    return output
