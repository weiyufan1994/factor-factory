from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any


MAX_SAFE_INTEGER = (1 << 53) - 1


class RFC8785CanonicalizationError(ValueError):
    """Raised when a value is outside the deliberately accepted JCS subset."""


def _string(value: str) -> str:
    output: list[str] = ['"']
    short_escapes = {
        "\b": "\\b",
        "\t": "\\t",
        "\n": "\\n",
        "\f": "\\f",
        "\r": "\\r",
        '"': '\\"',
        "\\": "\\\\",
    }
    for character in value:
        codepoint = ord(character)
        if 0xD800 <= codepoint <= 0xDFFF:
            raise RFC8785CanonicalizationError("unpaired_utf16_surrogate")
        if character in short_escapes:
            output.append(short_escapes[character])
        elif codepoint < 0x20:
            output.append(f"\\u{codepoint:04x}")
        else:
            output.append(character)
    output.append('"')
    return "".join(output)


def _utf16_sort_key(value: str) -> bytes:
    try:
        return value.encode("utf-16-be")
    except UnicodeEncodeError as exc:
        raise RFC8785CanonicalizationError("unpaired_utf16_surrogate") from exc


def _serialize(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int) and not isinstance(value, bool):
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise RFC8785CanonicalizationError("integer_outside_ieee754_safe_range")
        return str(value)
    if isinstance(value, float):
        # Factor Forge control-plane commitments deliberately use integer-only
        # JSON.  Rejecting floats keeps this implementation RFC 8785-correct on
        # its accepted domain instead of approximating ECMAScript NumberToString.
        raise RFC8785CanonicalizationError("floating_point_not_accepted")
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ",".join(_serialize(item) for item in value) + "]"
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise RFC8785CanonicalizationError("object_key_must_be_string")
        keys = sorted(value, key=_utf16_sort_key)
        return "{" + ",".join(
            f"{_string(key)}:{_serialize(value[key])}" for key in keys
        ) + "}"
    raise RFC8785CanonicalizationError(
        f"unsupported_json_type:{type(value).__name__}"
    )


def canonicalize(value: Any) -> bytes:
    """Return RFC 8785 bytes for the integer-only Factor Forge JSON profile.

    RFC 8785 number serialization follows ECMAScript.  This security-sensitive
    profile accepts only exactly representable JSON integers, so callers cannot
    accidentally commit to a Python-specific float rendering.
    """

    return _serialize(value).encode("utf-8")


def framed_sha256(domain: str, value: Any) -> str:
    if not domain or "\x00" in domain:
        raise RFC8785CanonicalizationError("invalid_domain")
    preimage = domain.encode("utf-8") + b"\x00" + canonicalize(value)
    return hashlib.sha256(preimage).hexdigest()
