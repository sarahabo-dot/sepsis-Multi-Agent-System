"""
test_fixtures_antibiotic.py
Mock for the Antibiotic Specialist Agent, so antibiotic_orchestrator.py and
synthesis_layer.py can be tested end-to-end before Agent 2 is actually
built. Uses the same synthetic sepsis case (SYN-SEPSIS-001) already used to
validate the SOFA calculator, so results across both parts of the system
stay comparable.

Usage:
    import antibiotic_orchestrator as orch
    orch._call_antibiotic_agent = mock_call_antibiotic_agent  # monkeypatch
"""

from datetime import datetime
from antibiotic_agent_schema import (
    AntibioticResponse,
    AntibioticRequest,
    RegimenOption,
    AppliedModifier,
    ModifierType,
)


async def mock_call_antibiotic_agent(request: AntibioticRequest) -> AntibioticResponse:
    """Deterministic stand-in — same shape a real Agent 2 call would return.
    No network call, no randomness, safe for repeated test runs.
    """
    return AntibioticResponse(
        case_id=request.case_id,
        request_type=request.request_type,
        knowledge_base_version="mock-2026-08-19",
        timing_target_hours=1 if request.severity.value == "septic_shock" else 3,
        recommended_regimen=[
            RegimenOption(
                drug_name="Piperacillin-tazobactam",
                dose="4.5 g",
                route="IV",
                frequency="every 6h",
                renal_adjusted=bool(request.creatinine_mg_dl and request.creatinine_mg_dl > 1.5),
                renal_adjustment_note=(
                    "Interval extended for renal impairment"
                    if request.creatinine_mg_dl and request.creatinine_mg_dl > 1.5
                    else None
                ),
            )
        ],
        applied_modifiers=[
            AppliedModifier(
                modifier_type=ModifierType.MDR,
                triggered_by=request.risk_factors.mdr_risk_factors,
                action_taken="broadened empirical coverage for MDR risk",
                requires_confirmation=True,
            )
        ] if request.risk_factors.mdr_risk_factors else [],
        warnings=(
            ["Documented allergy on file — verify before administration"]
            if request.documented_allergies else []
        ),
        rationale=(
            f"Empirical regimen proposed for {request.suspected_source.value} "
            f"source, {request.severity.value}. Renal dosing applied where indicated."
        ),
        generated_at=datetime.utcnow(),
        missing_inputs=(
            [] if request.creatinine_mg_dl is not None else ["creatinine"]
        ),
    )


# --- Reuses the same synthetic case as the SOFA test (SYN-SEPSIS-001) ---
# creatinine 2.1, source urinary, no MDR/allergy history in the base case —
# import and adapt from sepsis_synthetic_test_case.json when wiring up a
# real test runner (e.g. pytest fixture reading that JSON directly).
