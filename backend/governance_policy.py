"""Deterministic policy matrix for the Governance/Safety Monitor.

This module contains policy only. It never selects or modifies clinical therapy.
Unknown governance findings fail closed by design.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PolicyAction(str, Enum):
    BLOCK = "BLOCK"
    WARNING = "WARNING"
    PASS = "PASS"


@dataclass(frozen=True)
class PolicyRule:
    rule_id: str
    finding: str
    action: PolicyAction
    physician_visible: bool
    memory_record: bool
    audit_event: str
    rationale: str


POLICY_MATRIX: tuple[PolicyRule, ...] = (
    PolicyRule("GOV-001", "case_id_mismatch", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Never allow cross-case clinical output."),
    PolicyRule("GOV-002", "request_type_mismatch", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Output must correspond to the requested operation."),
    PolicyRule("GOV-003", "active_kb_version_missing", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "A clinical recommendation must be traceable to an active KB version."),
    PolicyRule("GOV-004", "kb_version_mismatch", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Do not release an answer generated against a different KB version."),
    PolicyRule("GOV-005", "drug_not_in_deterministic_kb", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Governance cannot permit an unrecognized drug."),
    PolicyRule("GOV-006", "dose_mismatch", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Dose must exactly match deterministic output."),
    PolicyRule("GOV-007", "route_mismatch", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Route must exactly match deterministic output."),
    PolicyRule("GOV-008", "frequency_mismatch", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Frequency must exactly match deterministic/renal-adjusted output."),
    PolicyRule("GOV-009", "renal_adjusted_mismatch", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Renal adjustment state must match deterministic calculation."),
    PolicyRule("GOV-010", "renal_adjustment_note_mismatch", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Renal adjustment provenance must remain consistent."),
    PolicyRule("GOV-011", "modifier_count_mismatch", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Modifiers are deterministic and cannot be invented or omitted."),
    PolicyRule("GOV-012", "modifier_type_mismatch", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Modifier type must match deterministic output."),
    PolicyRule("GOV-013", "modifier_trigger_mismatch", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Modifier triggers must match captured risk factors."),
    PolicyRule("GOV-014", "modifier_action_mismatch", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Modifier action cannot be altered by the LLM."),
    PolicyRule("GOV-015", "fungal_flag_mismatch", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Fungal flag is safety-sensitive and deterministic."),
    PolicyRule("GOV-016", "fungal_flag_risk_factors_mismatch", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Fungal risk factors cannot be fabricated."),
    PolicyRule("GOV-017", "timing_target_mismatch", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Timing target is a deterministic clinical constraint."),
    PolicyRule("GOV-018", "missing_inputs_mismatch", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "The model may not suppress missing-input safety signals."),
    PolicyRule("GOV-019", "critical_missing_input", PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Critical missing data prevents safe automated release."),
    PolicyRule("GOV-020", "empty_rationale", PolicyAction.WARNING, True, True, "GOVERNANCE_WARNING", "Narration is not evidence of correctness, but an empty rationale should be visible."),
    PolicyRule("GOV-021", "fungal_risk_requires_manual_id_or_pharmacy_review", PolicyAction.WARNING, True, True, "GOVERNANCE_WARNING", "Fungal coverage is not auto-prescribed; manual review remains required."),
    PolicyRule("GOV-022", "missing_inputs_present", PolicyAction.WARNING, True, True, "GOVERNANCE_WARNING", "Non-critical missing inputs must remain visible."),
    PolicyRule("GOV-023", "reviewer_required", PolicyAction.BLOCK, False, True, "GUIDELINE_GOVERNANCE_BLOCK", "Clinical guideline activation requires an accountable reviewer."),
    PolicyRule("GOV-024", "invalid_review_state", PolicyAction.BLOCK, False, True, "GUIDELINE_GOVERNANCE_BLOCK", "Only pending reviews may enter approval."),
    PolicyRule("GOV-025", "review_id_missing", PolicyAction.BLOCK, False, True, "GUIDELINE_GOVERNANCE_BLOCK", "Approval must be traceable to a specific review."),
    PolicyRule("GOV-026", "proposed_kb_has_no_entries", PolicyAction.BLOCK, False, True, "GUIDELINE_GOVERNANCE_BLOCK", "An empty clinical KB cannot be activated."),
    PolicyRule("GOV-027", "proposed_version_matches_active_version", PolicyAction.BLOCK, False, True, "GUIDELINE_GOVERNANCE_BLOCK", "Activation must create a distinct immutable version."),
    PolicyRule("GOV-028", "invalid_kb_entry_structure", PolicyAction.BLOCK, False, True, "GUIDELINE_GOVERNANCE_BLOCK", "Malformed clinical rules cannot be activated."),
    PolicyRule("GOV-029", "proposed_kb_version_missing_will_be_assigned_by_versioning", PolicyAction.WARNING, True, True, "GUIDELINE_GOVERNANCE_WARNING", "Versioning will assign the final immutable identifier."),
    PolicyRule("GOV-030", "resistant_alert_requires_immediate_manual_review", PolicyAction.WARNING, True, True, "GOVERNANCE_WARNING", "A resistant-organism finding is a valid clinical result, not a governance failure — it must reach the physician clearly, not be suppressed."),
)

_RULE_BY_FINDING = {r.finding: r for r in POLICY_MATRIX}


def rule_for_finding(finding: str) -> PolicyRule | None:
    """Resolve a finding by its stable prefix, allowing parameterized details."""
    if finding in _RULE_BY_FINDING:
        return _RULE_BY_FINDING[finding]
    prefix = finding.split(":", 1)[0]
    return _RULE_BY_FINDING.get(prefix)


def evaluate_findings(violations: list[str] | tuple[str, ...], warnings: list[str] | tuple[str, ...]):
    """Return (action, matched_rules). Unknown findings are BLOCK (fail closed)."""
    matched: list[PolicyRule] = []
    action = PolicyAction.PASS
    for finding in [*violations, *warnings]:
        rule = rule_for_finding(finding)
        if rule is None:
            # A newly introduced safety finding must never silently pass.
            matched.append(PolicyRule("GOV-UNKNOWN", finding, PolicyAction.BLOCK, False, True, "GOVERNANCE_BLOCK", "Unknown governance finding; fail closed."))
            action = PolicyAction.BLOCK
            continue
        matched.append(rule)
        if rule.action == PolicyAction.BLOCK:
            action = PolicyAction.BLOCK
        elif rule.action == PolicyAction.WARNING and action == PolicyAction.PASS:
            action = PolicyAction.WARNING
    return action, tuple(matched)
