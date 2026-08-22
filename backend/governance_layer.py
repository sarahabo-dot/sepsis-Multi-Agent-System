"""
governance_layer.py
Deterministic safety boundary for the five-agent sepsis architecture.

Governance does not select therapy and never uses an LLM. It validates Agent 2
against the exact deterministic output of the active knowledge base and gates
guideline activation behind explicit human review.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from antibiotic_agent_schema import AntibioticRequest, AntibioticResponse
from antibiotic_rules_engine import select_regimen
from audit_trail import append_event
from governance_policy import evaluate_findings


class GovernanceStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class GovernanceResult:
    status: GovernanceStatus
    agent_name: str
    kb_version: Optional[str]
    violations: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def allowed(self) -> bool:
        return self.status != GovernanceStatus.BLOCK


def _compare_regimens(expected, actual) -> list[str]:
    violations: list[str] = []
    if len(expected) != len(actual):
        violations.append(f"regimen_length_mismatch:expected={len(expected)}:got={len(actual)}")
        return violations

    for i, (e, a) in enumerate(zip(expected, actual)):
        for field in ("drug_name", "dose", "route", "frequency", "renal_adjusted"):
            ev = getattr(e, field)
            av = getattr(a, field)
            if str(ev).strip().lower() != str(av).strip().lower():
                violations.append(
                    (f"drug_not_in_deterministic_kb:{av}" if field == "drug_name" else
                     f"dose_mismatch:{av}:expected={ev}" if field == "dose" else
                     f"route_mismatch:{av}:expected={ev}" if field == "route" else
                     f"frequency_mismatch:{av}:expected={ev}" if field == "frequency" else
                     f"renal_adjusted_mismatch:index={i}:expected={ev}:got={av}")
                )
        if (e.renal_adjustment_note or "") != (a.renal_adjustment_note or ""):
            violations.append(f"renal_adjustment_note_mismatch:index={i}")
    return violations


def _compare_modifiers(expected, actual) -> list[str]:
    violations: list[str] = []
    if len(expected) != len(actual):
        violations.append(f"modifier_count_mismatch:expected={len(expected)}:got={len(actual)}")
        return violations
    for i, (e, a) in enumerate(zip(expected, actual)):
        if e.modifier_type != a.modifier_type:
            violations.append(f"modifier_type_mismatch:index={i}")
        if list(e.triggered_by) != list(a.triggered_by):
            violations.append(f"modifier_trigger_mismatch:index={i}")
        if e.action_taken != a.action_taken:
            violations.append(f"modifier_action_mismatch:index={i}")
    return violations


def validate_antibiotic_response(
    request: AntibioticRequest,
    response: AntibioticResponse,
    kb: dict,
) -> GovernanceResult:
    """Validate Agent 2 against the deterministic rules engine.

    This is intentionally stronger than checking whether each drug exists in
    the KB: renal-adjusted frequency, modifiers, missing-input flags and the
    fungal safety boundary must also match the deterministic calculation.
    """
    violations: list[str] = []
    warnings: list[str] = []
    active_version = kb.get("version")

    if response.case_id != request.case_id:
        violations.append("case_id_mismatch")
    if response.request_type != request.request_type:
        violations.append("request_type_mismatch")
    if not active_version:
        violations.append("active_kb_version_missing")
    elif response.knowledge_base_version != active_version:
        violations.append(
            f"kb_version_mismatch:response={response.knowledge_base_version}:active={active_version}"
        )

    expected_regimen, expected_modifiers, expected_fungal, expected_missing = select_regimen(request, kb)
    violations.extend(_compare_regimens(expected_regimen, response.recommended_regimen))
    violations.extend(_compare_modifiers(expected_modifiers, response.applied_modifiers))

    if (expected_fungal is None) != (response.fungal_flag is None):
        violations.append("fungal_flag_mismatch")
    elif expected_fungal is not None and response.fungal_flag is not None:
        if list(expected_fungal.risk_factors_present) != list(response.fungal_flag.risk_factors_present):
            violations.append("fungal_flag_risk_factors_mismatch")

    expected_timing = 1 if request.severity.value == "septic_shock" else 3
    if response.timing_target_hours != expected_timing:
        violations.append(
            f"timing_target_mismatch:expected={expected_timing}:got={response.timing_target_hours}"
        )

    if list(response.missing_inputs) != list(expected_missing):
        violations.append("missing_inputs_mismatch")

    # Warnings are informational, but must remain visible. Rationale is never
    # used as evidence for clinical correctness.
    if response.fungal_flag is not None:
        warnings.append("fungal_risk_requires_manual_id_or_pharmacy_review")
    if response.missing_inputs:
        warnings.append("missing_inputs_present:" + ",".join(response.missing_inputs))
    if any(x.startswith("CRITICAL_") for x in response.missing_inputs):
        violations.append("critical_missing_input")
    if not response.rationale.strip():
        warnings.append("empty_rationale")

    policy_action, _ = evaluate_findings(violations, warnings)
    status = GovernanceStatus(policy_action.value)
    result = GovernanceResult(
        status=status,
        agent_name="governance_layer",
        kb_version=active_version,
        violations=tuple(violations),
        warnings=tuple(warnings),
    )
    append_event(
        "GOVERNANCE_DECISION",
        case_id=request.case_id,
        agent="governance_layer",
        status=result.status.value,
        payload=governance_event_payload(result),
    )
    return result


def validate_guideline_activation(
    *,
    review: dict,
    proposed_kb: dict,
    active_kb_version: Optional[str],
    reviewer_id: str,
) -> GovernanceResult:
    """Gate the only dangerous transition: pending guideline -> active KB."""
    violations: list[str] = []
    warnings: list[str] = []

    if not reviewer_id or not reviewer_id.strip():
        violations.append("reviewer_required")
    if review.get("status") != "pending":
        violations.append(f"invalid_review_state:{review.get('status')}")
    if not review.get("review_id"):
        violations.append("review_id_missing")
    if not proposed_kb.get("entries"):
        violations.append("proposed_kb_has_no_entries")
    if not proposed_kb.get("version"):
        warnings.append("proposed_kb_version_missing_will_be_assigned_by_versioning")
    if active_kb_version and proposed_kb.get("version") == active_kb_version:
        violations.append("proposed_version_matches_active_version")

    for i, entry in enumerate(proposed_kb.get("entries", [])):
        if not all(k in entry for k in ("source", "severity", "base_regimen")):
            violations.append(f"invalid_kb_entry_structure:{i}")

    policy_action, _ = evaluate_findings(violations, warnings)
    status = GovernanceStatus(policy_action.value)
    result = GovernanceResult(
        status=status,
        agent_name="governance_layer",
        kb_version=active_kb_version,
        violations=tuple(violations),
        warnings=tuple(warnings),
    )
    append_event(
        "GUIDELINE_ACTIVATION_GOVERNANCE",
        actor=reviewer_id or "unknown",
        agent="governance_layer",
        status=result.status.value,
        payload={
            "review_id": review.get("review_id"),
            "active_kb_version": active_kb_version,
            "proposed_kb_version": proposed_kb.get("version"),
            **governance_event_payload(result),
        },
    )
    return result


def governance_event_payload(result: GovernanceResult) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "allowed": result.allowed,
        "agent_name": result.agent_name,
        "kb_version": result.kb_version,
        "violations": list(result.violations),
        "warnings": list(result.warnings),
    }


def enforce_antibiotic_decision(result: GovernanceResult) -> None:
    """Fail-closed policy boundary: BLOCK may never be promoted downstream."""
    if result.status == GovernanceStatus.BLOCK:
        details = "; ".join(result.violations) or "unspecified_governance_violation"
        raise GovernanceBlockedError(details)


class GovernanceBlockedError(RuntimeError):
    """Raised when a clinical output fails deterministic governance checks."""
