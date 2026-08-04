from __future__ import annotations

from html import escape
import re
from xml.etree import ElementTree

try:
    import latex2mathml.converter as _latex_converter
except ImportError:  # The web host installs the pinned console dependency.
    _latex_converter = None


_MATHML_NAMESPACE = "http://www.w3.org/1998/Math/MathML"
ElementTree.register_namespace("", _MATHML_NAMESPACE)
_MAX_EXPRESSION_LENGTH = 12_000
_LATEX_SIGNAL = re.compile(r"(?:\\[A-Za-z]+|[_^={}]|[∑∏∫√λμσθβγαΔ])")
_PLAIN_GREEK_NAMES = (
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "eta",
    "theta",
    "kappa",
    "lambda",
    "mu",
    "rho",
    "sigma",
)
_ALLOWED_TAGS = {
    "math",
    "semantics",
    "mrow",
    "mi",
    "mn",
    "mo",
    "mtext",
    "mspace",
    "ms",
    "mglyph",
    "msub",
    "msup",
    "msubsup",
    "mfrac",
    "msqrt",
    "mroot",
    "munder",
    "mover",
    "munderover",
    "mfenced",
    "mtable",
    "mtr",
    "mtd",
    "maligngroup",
    "malignmark",
    "mpadded",
    "mphantom",
    "menclose",
    "mstyle",
}
_ALLOWED_ATTRIBUTES = {
    "display",
    "mathvariant",
    "stretchy",
    "fence",
    "separator",
    "accent",
    "accentunder",
    "linethickness",
    "columnalign",
    "rowalign",
    "columnspacing",
    "rowspacing",
    "displaystyle",
    "scriptlevel",
}


def render_latex_math(expression: str) -> str:
    source = str(expression or "").strip()
    if not source:
        return ""
    if len(source) > _MAX_EXPRESSION_LENGTH or not _LATEX_SIGNAL.search(source):
        return _fallback(source)
    if _latex_converter is None:
        return _fallback(source)
    normalized = _normalize_plain_math_names(_strip_math_delimiters(source))
    try:
        converted = _latex_converter.convert(normalized)
        root = ElementTree.fromstring(converted)
        _sanitize_mathml(root)
        root.set("display", "block")
        mathml = ElementTree.tostring(root, encoding="unicode", method="xml")
    except Exception:  # Third-party parser exceptions must not break the research page.
        return _fallback(source)
    return (
        f'<span class="rendered-math" role="math" aria-label="{escape(source, quote=True)}">'
        f"{mathml}</span>"
    )


def _sanitize_mathml(element: ElementTree.Element) -> None:
    local_name = _local_name(element.tag)
    if local_name not in _ALLOWED_TAGS:
        raise ValueError(f"unsupported MathML tag: {local_name}")
    element.tag = f"{{{_MATHML_NAMESPACE}}}{local_name}"
    for attribute in list(element.attrib):
        if _local_name(attribute) not in _ALLOWED_ATTRIBUTES:
            del element.attrib[attribute]
    for child in list(element):
        child_name = _local_name(child.tag)
        if child_name in {"annotation", "annotation-xml"}:
            element.remove(child)
            continue
        _sanitize_mathml(child)


def _strip_math_delimiters(value: str) -> str:
    if value.startswith("$$") and value.endswith("$$") and len(value) >= 4:
        return value[2:-2].strip()
    if value.startswith("$") and value.endswith("$") and len(value) >= 2:
        return value[1:-1].strip()
    if value.startswith(r"\[") and value.endswith(r"\]"):
        return value[2:-2].strip()
    return value


def _normalize_plain_math_names(value: str) -> str:
    normalized = value
    for name in _PLAIN_GREEK_NAMES:
        normalized = re.sub(
            rf"(?<!\\)\b{name}(?=_|\b)",
            rf"\\{name}",
            normalized,
        )
    normalized = re.sub(r"(?<![A-Za-z\\])E(?=\[)", r"\\mathbb{E}", normalized)
    normalized = re.sub(
        r"(?<![A-Za-z\\])(rank|exp|max|min)(?=\()",
        lambda match: rf"\operatorname{{{match.group(1)}}}",
        normalized,
    )
    return re.sub(r"\s+x\s+", r" \\times ", normalized)


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _fallback(source: str) -> str:
    return f'<span class="equation-source">{escape(source)}</span>'
