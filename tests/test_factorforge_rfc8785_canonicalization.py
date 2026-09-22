from __future__ import annotations

import hashlib

import pytest

from factor_factory.research_org.rfc8785_canonical import (
    MAX_SAFE_INTEGER,
    RFC8785CanonicalizationError,
    canonicalize,
    framed_sha256,
)


def test_integer_only_jcs_canonicalizes_utf16_order_and_escapes() -> None:
    payload = {
        "€": "euro",
        "\r": "carriage\nreturn",
        "1": "one",
        "😀": "face",
        "\u0080": "control",
        'quote"': "slash\\tab\t",
    }
    assert canonicalize(payload) == (
        '{"\\r":"carriage\\nreturn","1":"one","quote\\\"":"slash\\\\tab\\t",'
        '"\u0080":"control","€":"euro","😀":"face"}'
    ).encode("utf-8")


def test_jcs_safe_integer_and_domain_framing_are_deterministic() -> None:
    payload = {"z": [None, True, False, -1, MAX_SAFE_INTEGER], "a": {"b": 2}}
    raw = canonicalize(payload)
    expected = hashlib.sha256(b"FF_TEST_DOMAIN\x00" + raw).hexdigest()
    assert framed_sha256("FF_TEST_DOMAIN", payload) == expected
    assert framed_sha256("FF_TEST_DOMAIN", payload) == expected


@pytest.mark.parametrize(
    "value,reason",
    [
        (1.0, "floating_point_not_accepted"),
        (MAX_SAFE_INTEGER + 1, "integer_outside_ieee754_safe_range"),
        ({1: "value"}, "object_key_must_be_string"),
        ({"bad": "\ud800"}, "unpaired_utf16_surrogate"),
        ((1, 2), "unsupported_json_type:tuple"),
    ],
)
def test_jcs_profile_rejects_values_that_could_canonicalize_ambiguously(
    value: object, reason: str
) -> None:
    with pytest.raises(RFC8785CanonicalizationError, match=reason):
        canonicalize(value)


def test_domain_must_be_nonempty_and_nul_free() -> None:
    with pytest.raises(RFC8785CanonicalizationError, match="invalid_domain"):
        framed_sha256("", {})
    with pytest.raises(RFC8785CanonicalizationError, match="invalid_domain"):
        framed_sha256("bad\x00domain", {})
