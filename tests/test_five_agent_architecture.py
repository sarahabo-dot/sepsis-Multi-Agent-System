import asyncio
from datetime import datetime

from antibiotic_agent_schema import (
    AntibioticRequest, AntibioticResponse, RegimenOption,
    RequestType, Severity, SuspectedSource, RiskFactors
)
from governance_layer import (
    GovernanceStatus, validate_antibiotic_response, validate_guideline_activation
)


def kb():
    return {
        "version": "kb-v1",
        "entries": [{
            "source": "urinary",
            "severity": "septic_shock",
            "base_regimen": [{
                "drug_name": "Piperacillin-tazobactam",
                "dose": "4.5 g",
                "route": "IV",
                "frequency": "every 6h",
            }],
            "renal_adjustment_rules": [],
        }],
        "modifier_rules": {
            "mdr": {"note": "broaden_or_switch"},
            "mrsa": {"drug_options": []},
            "anaerobic": {"drug_options": []},
        },
    }


def request():
    return AntibioticRequest(
        case_id="CASE-1",
        request_type=RequestType.EMPIRICAL,
        severity=Severity.SEPTIC_SHOCK,
        suspected_source=SuspectedSource.URINARY,
        onset_timestamp=datetime.utcnow(),
        creatinine_mg_dl=1.0,
    )


def response(drug="Piperacillin-tazobactam", dose="4.5 g", version="kb-v1"):
    return AntibioticResponse(
        case_id="CASE-1",
        request_type=RequestType.EMPIRICAL,
        knowledge_base_version=version,
        timing_target_hours=1,
        recommended_regimen=[RegimenOption(
            drug_name=drug, dose=dose, route="IV", frequency="every 6h",
            renal_adjusted=False,
        )],
        rationale="Deterministic test rationale.",
    )


def test_valid_response_passes():
    result = validate_antibiotic_response(request(), response(), kb())
    assert result.status == GovernanceStatus.PASS


def test_unknown_drug_is_blocked():
    result = validate_antibiotic_response(request(), response("Vancomycin"), kb())
    assert result.status == GovernanceStatus.BLOCK
    assert any("drug_not_in_deterministic_kb" in x for x in result.violations)


def test_dose_mismatch_is_blocked():
    result = validate_antibiotic_response(request(), response(dose="2 g"), kb())
    assert result.status == GovernanceStatus.BLOCK
    assert any("dose_mismatch" in x for x in result.violations)


def test_kb_version_mismatch_is_blocked():
    result = validate_antibiotic_response(request(), response(version="kb-v0"), kb())
    assert result.status == GovernanceStatus.BLOCK


def test_case_id_mismatch_is_blocked():
    r = response()
    r.case_id = "OTHER"
    result = validate_antibiotic_response(request(), r, kb())
    assert result.status == GovernanceStatus.BLOCK


def test_guideline_activation_requires_pending_review():
    result = validate_guideline_activation(
        review={"review_id": "R1", "status": "rejected"},
        proposed_kb={"version": "kb-v2", "entries": [{"source": "urinary", "severity": "sepsis", "base_regimen": []}]},
        active_kb_version="kb-v1",
        reviewer_id="clinician-1",
    )
    assert result.status == GovernanceStatus.BLOCK


def test_guideline_activation_requires_reviewer():
    result = validate_guideline_activation(
        review={"review_id": "R1", "status": "pending"},
        proposed_kb={"version": "kb-v2", "entries": [{"source": "urinary", "severity": "sepsis", "base_regimen": []}]},
        active_kb_version="kb-v1",
        reviewer_id="",
    )
    assert result.status == GovernanceStatus.BLOCK


def test_governance_blocks_frequency_hallucination():
    r = response()
    r.recommended_regimen[0].frequency = "every 12h"
    result = validate_antibiotic_response(request(), r, kb())
    assert result.status == GovernanceStatus.BLOCK
    assert any("frequency_mismatch" in x for x in result.violations)


def test_governance_blocks_timing_target_hallucination():
    r = response()
    r.timing_target_hours = 3
    result = validate_antibiotic_response(request(), r, kb())
    assert result.status == GovernanceStatus.BLOCK
    assert any("timing_target_mismatch" in x for x in result.violations)


def test_governance_blocks_missing_input_suppression():
    req = request()
    req.creatinine_mg_dl = None
    r = response()
    result = validate_antibiotic_response(req, r, kb())
    assert result.status == GovernanceStatus.BLOCK
    assert "missing_inputs_mismatch" in result.violations


def test_governance_blocks_fabricated_fungal_flag():
    r = response()
    from antibiotic_agent_schema import FungalFlag
    r.fungal_flag = FungalFlag(risk_factors_present=["invented_risk"])
    result = validate_antibiotic_response(request(), r, kb())
    assert result.status == GovernanceStatus.BLOCK
    assert "fungal_flag_mismatch" in result.violations


def test_governance_policy_is_fail_closed():
    from governance_layer import GovernanceResult, GovernanceStatus, enforce_antibiotic_decision, GovernanceBlockedError
    blocked = GovernanceResult(
        status=GovernanceStatus.BLOCK,
        agent_name="governance_layer",
        kb_version="kb-v1",
        violations=("dose_mismatch",),
    )
    assert blocked.allowed is False
    try:
        enforce_antibiotic_decision(blocked)
        assert False, "BLOCK must raise"
    except GovernanceBlockedError as exc:
        assert "dose_mismatch" in str(exc)


def test_governance_warning_remains_releasable():
    from governance_layer import GovernanceResult, GovernanceStatus, enforce_antibiotic_decision
    warning = GovernanceResult(
        status=GovernanceStatus.WARNING,
        agent_name="governance_layer",
        kb_version="kb-v1",
        warnings=("fungal_risk_requires_manual_id_or_pharmacy_review",),
    )
    assert warning.allowed is True
    enforce_antibiotic_decision(warning)
