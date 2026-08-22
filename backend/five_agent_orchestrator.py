"""
five_agent_orchestrator.py
Agent 1 orchestration boundary for the five-agent architecture.

Agents:
1. Sepsis Bundle Agent / Orchestrator
2. Antibiotic Specialist Agent
3. Guideline Surveillance Agent (background job)
4. Memory & Clinical Analytics Agent
5. Governance / Safety Monitor

The orchestrator runs deterministic SOFA and the antibiotic path in parallel.
Governance validates Agent 2 before the result is promoted as trusted.
Memory receives the resulting structured case snapshot after governance.

Agent 3 is deliberately NOT invoked during a patient case.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from sofa_calculator import calculate_sofa
from antibiotic_agent_schema import (
    AntibioticRequest,
    AntibioticResponse,
    RiskFactors,
    Severity,
    SuspectedSource,
    RequestType,
)
from antibiotic_specialist_agent import get_recommendation
from antibiotic_rules_engine import load_knowledge_base
from governance_layer import (
    GovernanceResult,
    validate_antibiotic_response,
)
from memory_agent import ClinicalMemoryRecord, MemoryAnalyticsAgent, pseudonymize_patient_id
from audit_trail import append_event

logger = logging.getLogger("sepsis_bundle.five_agent_orchestrator")


async def _safe_antibiotic_call(request: AntibioticRequest):
    try:
        return await asyncio.wait_for(get_recommendation(request), timeout=8.0), None
    except asyncio.TimeoutError:
        return None, "antibiotic_agent_timeout"
    except Exception:
        logger.exception("Antibiotic Agent failed")
        return None, "antibiotic_agent_error"


async def assess_case(
    *,
    case_id: str,
    patient_id: str,
    sofa_input,
    severity: Severity,
    suspected_source: SuspectedSource,
    onset_timestamp: datetime,
    risk_factors: Optional[RiskFactors] = None,
    documented_allergies: Optional[list[str]] = None,
    memory_agent: Optional[MemoryAnalyticsAgent] = None,
    memory_secret: Optional[str] = None,
):
    """Run the real-time portion of the five-agent architecture.

    Agent 3 (Guideline Surveillance) is intentionally absent from this
    function because it is a scheduled background process.
    """
    request = AntibioticRequest(
        case_id=case_id,
        request_type=RequestType.EMPIRICAL,
        severity=severity,
        suspected_source=suspected_source,
        onset_timestamp=onset_timestamp,
        creatinine_mg_dl=getattr(getattr(sofa_input, "creatinine", None), "value", None),
        bilirubin_mg_dl=getattr(getattr(sofa_input, "bilirubin", None), "value", None),
        weight_kg=getattr(sofa_input, "weight_kg", None),
        risk_factors=risk_factors or RiskFactors(),
        documented_allergies=documented_allergies or [],
    )

    sofa_task = asyncio.create_task(asyncio.to_thread(calculate_sofa, sofa_input))
    antibiotic_task = asyncio.create_task(_safe_antibiotic_call(request))

    # Await independently: an antibiotic failure must not erase SOFA.
    sofa_result = await sofa_task
    antibiotic_response, antibiotic_error = await antibiotic_task

    governance: Optional[GovernanceResult] = None
    trusted_antibiotic = None
    if antibiotic_response is not None:
        kb = load_knowledge_base()
        governance = validate_antibiotic_response(request, antibiotic_response, kb)
        # Fail closed: only PASS/WARNING outputs can cross the governance
        # boundary. BLOCKed recommendations remain internal/audited only.
        if governance.allowed:
            trusted_antibiotic = antibiotic_response
        else:
            antibiotic_error = "antibiotic_governance_blocked"

    append_event(
        "CASE_ASSESSMENT",
        case_id=case_id,
        agent="five_agent_orchestrator",
        status=(governance.status.value if governance else ("ERROR" if antibiotic_error else "NO_ANTIBIOTIC_RESPONSE")),
        payload={
            "severity": severity.value,
            "suspected_source": suspected_source.value,
            "antibiotic_error": antibiotic_error,
            "governance": (
                {
                    "status": governance.status.value,
                    "violations": list(governance.violations),
                    "warnings": list(governance.warnings),
                    "kb_version": governance.kb_version,
                } if governance else None
            ),
            "trusted_antibiotic": trusted_antibiotic is not None,
        },
    )

    if memory_agent is not None and memory_secret:
        sofa_total = getattr(sofa_result, "total", None)
        if sofa_total is None and isinstance(sofa_result, dict):
            sofa_total = sofa_result.get("total")
        patient_key = pseudonymize_patient_id(patient_id, memory_secret)
        memory_agent.record_case(
            ClinicalMemoryRecord(
                case_id=case_id,
                patient_key=patient_key,
                recorded_at=datetime.utcnow(),
                severity=severity.value,
                suspected_source=suspected_source.value,
                sofa_total=sofa_total,
                timing_target_hours=(
                    trusted_antibiotic.timing_target_hours
                    if trusted_antibiotic else None
                ),
                antibiotic_kb_version=(
                    trusted_antibiotic.knowledge_base_version
                    if trusted_antibiotic else None
                ),
                antibiotic_governance_status=(
                    governance.status.value if governance else None
                ),
                antibiotic_error=antibiotic_error,
                regimen=(
                    [r.model_dump() for r in trusted_antibiotic.recommended_regimen]
                    if trusted_antibiotic else []
                ),
                warnings=(
                    trusted_antibiotic.warnings if trusted_antibiotic else []
                ),
                missing_inputs=(
                    trusted_antibiotic.missing_inputs if trusted_antibiotic else []
                ),
            )
        )

    return {
        "case_id": case_id,
        "sofa": sofa_result,
        "antibiotic": trusted_antibiotic,
        "antibiotic_raw": antibiotic_response,
        "antibiotic_error": antibiotic_error,
        "governance": governance,
    }
