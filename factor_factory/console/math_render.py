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
_PLAIN_GREEK_ALIASES = {
    "eps": r"\varepsilon",
    "epsilon": r"\varepsilon",
    "eta": r"\eta",
}
_PLAIN_FUNCTION_NAMES = {"abs", "exp", "max", "min", "rank", "sign"}
_PLAIN_IDENTIFIER = re.compile(
    r"(?<![A-Za-z\\])([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*)(?=(?:_\{|\b))"
)
_EQUATION_SPLIT = re.compile(r"[;\n]+")
_ANNOTATION_SPLIT = re.compile(
    r",\s*(?=(?:entry|exit)\b)|\s+(?=(?:with|where|when|because|under|so\s+that|is|means|implies|denotes|represents|captures)\b)",
    re.IGNORECASE,
)
_SIMPLE_MATH_ATOM = (
    r"(?:\\mathrm\{[^{}]+\}|\\[A-Za-z]+|[A-Za-z])"
    r"(?:_\{[^{}]+\}|_[A-Za-z0-9]+)?"
)
_SIMPLE_FRACTION = re.compile(rf"({_SIMPLE_MATH_ATOM})\s*/\s*({_SIMPLE_MATH_ATOM})")
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


def render_latex_math(expression: str, *, source_label: str | None = None) -> str:
    source = str(expression or "").strip()
    public_source = str(source_label if source_label is not None else source).strip()
    if not source:
        return ""
    if len(source) > _MAX_EXPRESSION_LENGTH or not _LATEX_SIGNAL.search(source):
        return _fallback(public_source)
    if _latex_converter is None:
        return _fallback(public_source)
    normalized = _normalize_plain_math_names(_strip_math_delimiters(source))
    try:
        converted = _latex_converter.convert(normalized)
        root = ElementTree.fromstring(converted)
        _sanitize_mathml(root)
        root.set("display", "block")
        mathml = ElementTree.tostring(root, encoding="unicode", method="xml")
    except Exception:  # Third-party parser exceptions must not break the research page.
        return _fallback(public_source)
    return (
        f'<span class="rendered-math" role="math" aria-label="{escape(public_source, quote=True)}">'
        f"{mathml}</span>"
    )


def render_equation_statement(expression: str) -> str:
    """Render semicolon-delimited model equations without treating prose as TeX."""
    source = str(expression or "").strip()
    if not source:
        return ""
    if _is_structured_latex(source):
        return (
            '<div class="equation-statement"><div class="equation-line">'
            f"{render_latex_math(_normalize_structured_latex(source), source_label=source)}</div></div>"
        )
    clauses = [item.strip() for item in _EQUATION_SPLIT.split(source) if item.strip()]
    rows: list[str] = []
    visible_clauses = clauses[:32]
    for clause in visible_clauses:
        label, body = _split_equation_label(clause)
        math_source, annotation = _split_equation_annotation(body)
        if _looks_like_equation(math_source):
            label_html = (
                f'<span class="equation-line-label">{escape(label)}</span>' if label else ""
            )
            annotation_html = (
                f'<p class="equation-annotation">{escape(annotation)}</p>'
                if annotation
                else ""
            )
            rows.append(
                '<div class="equation-line">'
                f"{label_html}{render_latex_math(_plain_equation_to_latex(math_source))}"
                f"{annotation_html}</div>"
            )
            continue
        text = f"{label}: {body}" if label else body
        rows.append(f'<p class="equation-annotation">{escape(text)}</p>')
    if len(clauses) > len(visible_clauses):
        overflow = "; ".join(clauses[len(visible_clauses) :])
        count = len(clauses) - len(visible_clauses)
        rows.append(
            '<details class="equation-overflow">'
            f"<summary>{count} additional equation clauses</summary>"
            f"<pre>{escape(overflow)}</pre></details>"
        )
    return f'<div class="equation-statement">{"".join(rows)}</div>'


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


def _split_equation_label(value: str) -> tuple[str, str]:
    if ":" not in value:
        return "", value
    label, body = value.split(":", 1)
    if _looks_like_equation(body):
        return label.strip(), body.strip()
    return "", value


def _is_structured_latex(value: str) -> bool:
    environments = re.findall(r"\\begin\{([A-Za-z*]+)\}", value)
    return bool(
        environments
        and all(rf"\end{{{environment}}}" in value for environment in environments)
    )


def _normalize_structured_latex(value: str) -> str:
    return (
        value.replace(r"\begin{aligned*}", r"\begin{split}")
        .replace(r"\end{aligned*}", r"\end{split}")
        .replace(r"\begin{aligned}", r"\begin{split}")
        .replace(r"\end{aligned}", r"\end{split}")
    )


def _split_equation_annotation(value: str) -> tuple[str, str]:
    parts = _ANNOTATION_SPLIT.split(value, maxsplit=1)
    if len(parts) == 1:
        return value.strip().rstrip("."), ""
    math_source = parts[0].strip().rstrip(".,")
    annotation = value[len(parts[0]) :].strip().lstrip(",").strip()
    return math_source.rstrip("."), annotation


def _looks_like_equation(value: str) -> bool:
    compact = str(value or "").strip()
    if re.match(r"^(?:if|when|where|because)\b", compact, re.IGNORECASE):
        return False
    return bool(
        compact
        and (
            any(
                operator in compact
                for operator in ("=", "<", ">", "~", "≤", "≥", r"\le", r"\ge", r"\neq")
            )
            or compact.startswith(("E[", r"\mathbb{E}", r"\mathbb E"))
            or ("(" in compact and any(operator in compact for operator in ("*", "/")))
        )
    )


def _plain_equation_to_latex(value: str) -> str:
    source = _strip_math_delimiters(str(value or "").strip())
    if "\\" in source:
        return source
    source = (
        source.replace("≤", r"\leq ")
        .replace("≥", r"\geq ")
        .replace("≠", r"\neq ")
        .replace("∈", r"\in ")
    )

    def replace_identifier(match: re.Match[str]) -> str:
        token = match.group(1)
        lower = token.lower()
        suffix = source[match.end() : match.end() + 1]
        if lower in _PLAIN_GREEK_ALIASES:
            return _PLAIN_GREEK_ALIASES[lower]
        for name in _PLAIN_GREEK_NAMES:
            if lower == name:
                return rf"\{name}"
            if lower.startswith(f"{name}_"):
                return rf"\{name}_{token[len(name) + 1:]}"
        if token == "E" and suffix == "[":
            return r"\mathbb{E}"
        if token == "I" and suffix == "(":
            return r"\mathbf{1}"
        if lower in _PLAIN_FUNCTION_NAMES and suffix == "(":
            return rf"\operatorname{{{lower}}}"
        if len(token) == 1 or re.fullmatch(r"[A-Za-z]_[A-Za-z0-9]+", token):
            return token
        escaped = token.replace("_", r"\_")
        return rf"\mathrm{{{escaped}}}"

    source = _PLAIN_IDENTIFIER.sub(replace_identifier, source)
    source = _SIMPLE_FRACTION.sub(
        lambda match: rf"\frac{{{match.group(1)}}}{{{match.group(2)}}}",
        source,
    )
    return source.replace("*", r" \cdot ")


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _fallback(source: str) -> str:
    return f'<span class="equation-source">{escape(source)}</span>'
