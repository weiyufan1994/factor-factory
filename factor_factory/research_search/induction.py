"""Bound a generated expression to one reviewed forward-induction scope.

This module checks identity, declared scope, and review state.  It does not
prove that an economic premise or mathematical derivation is correct.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Iterable


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class Unit:
    """A small exact dimension vector used only by the search type checker."""

    dimensions: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        normalized = tuple(sorted((str(name), int(power)) for name, power in self.dimensions if power))
        if normalized != self.dimensions or len({name for name, _ in normalized}) != len(normalized):
            raise ValueError("unit dimensions must be unique, sorted, and nonzero")

    @classmethod
    def dimensionless(cls) -> "Unit":
        return cls(())

    @classmethod
    def named(cls, name: str) -> "Unit":
        if not name or not name.strip():
            raise ValueError("unit name is required")
        return cls(((name.strip(), 1),))

    def multiply(self, other: "Unit") -> "Unit":
        powers = dict(self.dimensions)
        for name, power in other.dimensions:
            powers[name] = powers.get(name, 0) + power
        return Unit(tuple(sorted((name, power) for name, power in powers.items() if power)))

    def divide(self, other: "Unit") -> "Unit":
        return self.multiply(Unit(tuple((name, -power) for name, power in other.dimensions)))

    def payload(self) -> list[list[object]]:
        return [[name, power] for name, power in self.dimensions]


@dataclass(frozen=True)
class SemanticType:
    """Independent semantic dimensions; no single overloaded ``sort`` field."""

    shape: str
    value_type: str
    unit: Unit
    clock: str
    grouping: str
    information_semantics: str

    def __post_init__(self) -> None:
        if self.shape not in {"scalar", "panel"}:
            raise ValueError("shape must be scalar or panel")
        if self.value_type not in {"numeric", "boolean"}:
            raise ValueError("value_type must be numeric or boolean")
        if not all((self.clock, self.grouping, self.information_semantics)):
            raise ValueError("clock, grouping, and information semantics are required")

    def payload(self) -> dict[str, object]:
        return {
            "shape": self.shape,
            "value_type": self.value_type,
            "unit": self.unit.payload(),
            "clock": self.clock,
            "grouping": self.grouping,
            "information_semantics": self.information_semantics,
        }


@dataclass(frozen=True)
class FieldSpec:
    name: str
    semantic_type: SemanticType

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("field name is required")


@dataclass(frozen=True)
class ForwardInductionRecord:
    """Public, auditable content consumed before expression search.

    Synthetic fixtures carry no review authority. A production Step2 record is
    accepted only with the content hash created by the native review-binding
    adapter; a caller cannot promote an unreviewed payload with a status flag.
    """

    record_id: str
    origin: str
    source_ref: str
    assumptions: tuple[str, ...]
    key_derivation_steps: tuple[str, ...]
    parent_delta: tuple[str, ...]
    observation_map: str
    response_family: str
    response_constraint: str
    grammar_productions: tuple[str, ...]
    conclusions: tuple[str, ...]
    falsifiers: tuple[str, ...]
    review_decision: str
    data_exposure: str
    review_binding_hash: str | None = None

    def __post_init__(self) -> None:
        if self.origin not in {"synthetic_fixture", "step2_review"}:
            raise ValueError("unsupported induction record origin")
        if self.review_decision != "proceed":
            raise ValueError("only a proceed induction record can define search scope")
        if self.response_constraint != "causal_affine":
            raise ValueError("unsupported response constraint")
        strings = (self.record_id, self.source_ref, self.observation_map, self.response_family,
                   self.data_exposure)
        if not all(isinstance(value, str) and value.strip() for value in strings):
            raise ValueError("induction record requires nonempty public bindings")
        lists = (self.assumptions, self.key_derivation_steps, self.grammar_productions,
                 self.conclusions, self.falsifiers)
        if not all(rows and all(isinstance(value, str) and value.strip() for value in rows) for rows in lists):
            raise ValueError("induction record requires substantive public derivation content")
        allowed = {"field", "constant", "plus", "minus", "multiply", "divide", "delay", "mean"}
        if not set(self.grammar_productions).issubset(allowed):
            raise ValueError("induction grammar contains unsupported productions")
        if self.origin == "synthetic_fixture":
            if self.data_exposure != "synthetic_only" or self.review_binding_hash is not None:
                raise ValueError("synthetic induction records cannot carry reviewed data authority")
        elif (self.data_exposure != "development_only"
              or not isinstance(self.review_binding_hash, str)
              or not re.fullmatch(r"[0-9a-f]{64}", self.review_binding_hash)):
            raise ValueError("Step2 induction requires a bound review hash and development-only scope")

    @property
    def record_hash(self) -> str:
        return sha256(_canonical(self.payload()).encode()).hexdigest()

    def payload(self) -> dict[str, object]:
        return {
            "record_id": self.record_id, "origin": self.origin, "source_ref": self.source_ref,
            "assumptions": list(self.assumptions), "key_derivation_steps": list(self.key_derivation_steps),
            "parent_delta": list(self.parent_delta), "observation_map": self.observation_map,
            "response_family": self.response_family, "response_constraint": self.response_constraint,
            "grammar_productions": list(self.grammar_productions), "conclusions": list(self.conclusions),
            "falsifiers": list(self.falsifiers), "review_decision": self.review_decision,
            "data_exposure": self.data_exposure,
            "review_binding_hash": self.review_binding_hash,
        }


@dataclass(frozen=True)
class InductionScope:
    induction_id: str
    parent_induction_id: str | None
    induction_record: ForwardInductionRecord
    response_family: str
    mathematical_object: str
    observation_map: str
    allowed_fields: tuple[FieldSpec, ...]
    output_type: SemanticType
    allowed_operators: tuple[str, ...]
    allowed_constants: tuple[float, ...]
    allowed_windows: tuple[int, ...]
    max_depth: int
    missing_value_policy: str
    numeric_domain: str
    change_class: str

    def __post_init__(self) -> None:
        required = (
            self.induction_id, self.response_family,
            self.mathematical_object, self.observation_map,
            self.missing_value_policy, self.numeric_domain, self.change_class,
        )
        if not all(value.strip() for value in required):
            raise ValueError("induction scope requires nonempty public semantics")
        if self.change_class not in {
            "implementation_equivalent", "in_family_parameter",
            "measurement_variant", "new_response_structure",
        }:
            raise ValueError("unsupported induction change class")
        if (self.induction_record.response_family != self.response_family
                or self.induction_record.observation_map != self.observation_map):
            raise ValueError("scope must match its public induction record")
        if type(self.max_depth) is not int or self.max_depth < 1:
            raise ValueError("max_depth must be positive")
        if not self.allowed_fields or len({row.name for row in self.allowed_fields}) != len(self.allowed_fields):
            raise ValueError("allowed fields must be nonempty and unique")
        if not self.allowed_operators or len(set(self.allowed_operators)) != len(self.allowed_operators):
            raise ValueError("allowed operators must be nonempty and unique")
        if any(type(value) not in (int, float) for value in self.allowed_constants):
            raise ValueError("allowed constants must be numeric")
        if any(type(value) is not int or value < 1 for value in self.allowed_windows):
            raise ValueError("allowed windows must be positive integers")
        operator_productions = set(self.induction_record.grammar_productions) - {"field", "constant"}
        if not set(self.allowed_operators).issubset(operator_productions):
            raise ValueError("operator allowlist must be derived from the induction grammar")

    @property
    def scope_hash(self) -> str:
        return sha256(_canonical(self.payload()).encode()).hexdigest()

    def payload(self) -> dict[str, object]:
        return {
            "induction_id": self.induction_id,
            "parent_induction_id": self.parent_induction_id,
            "induction_record": self.induction_record.payload(),
            "induction_record_hash": self.induction_record.record_hash,
            "response_family": self.response_family,
            "mathematical_object": self.mathematical_object,
            "observation_map": self.observation_map,
            "allowed_fields": [
                {"name": row.name, "semantic_type": row.semantic_type.payload()}
                for row in self.allowed_fields
            ],
            "output_type": self.output_type.payload(),
            "allowed_operators": list(self.allowed_operators),
            "allowed_constants": list(self.allowed_constants),
            "allowed_windows": list(self.allowed_windows),
            "max_depth": self.max_depth,
            "missing_value_policy": self.missing_value_policy,
            "numeric_domain": self.numeric_domain,
            "change_class": self.change_class,
        }

    def field_map(self) -> dict[str, SemanticType]:
        return {row.name: row.semantic_type for row in self.allowed_fields}


class InductionScopeError(ValueError):
    pass


def require_effect_evaluation_scope(
    scope: InductionScope,
    *,
    candidate_scope_hash: str,
    candidate_response_family: str,
    changed_aspects: Iterable[str] = (),
) -> None:
    """Fail before fitness for a missing, stale, or out-of-family induction."""
    if scope.induction_record.review_decision != "proceed":
        raise InductionScopeError("induction_not_approved_for_effect_evaluation")
    if candidate_scope_hash != scope.scope_hash:
        raise InductionScopeError("stale_or_different_induction_scope")
    if candidate_response_family != scope.response_family:
        raise InductionScopeError("response_family_requires_new_induction")
    structural = {
        "economic_assumption", "mathematical_object", "response_structure",
        "state_equation", "observation_equation", "response_family",
    }
    if structural.intersection(changed_aspects) and scope.change_class != "new_response_structure":
        raise InductionScopeError("structural_change_not_bound_to_new_induction")
