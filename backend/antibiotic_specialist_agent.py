"""
antibiotic_specialist_agent.py
Agent 2 in the architecture. The regimen itself comes entirely from
antibiotic_rules_engine.py (deterministic). This file's only job is to call
Claude for the `rationale` narration field, constrained to the structured
data already decided — same separation of concerns as SOFA's
score_* functions vs. the /interpretation endpoint.

Wire this into antibiotic_orchestrator._call_antibiotic_agent to replace the
NotImplementedError placeholder.
"""

import os
from datetime import timedelta
try:
    from anthropic import AsyncAnthropic
except ImportError:  # optional: deterministic mode works without the SDK
    AsyncAnthropic = None

from antibiotic_agent_schema import AntibioticRequest, AntibioticResponse, RequestType
from antibiotic_rules_engine import select_regimen, load_knowledge_base, evaluate_deescalation, REASSESSMENT_WINDOW_HOURS

client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY")) if AsyncAnthropic else None

NARRATION_SYSTEM_PROMPT = """You are writing a one-paragraph clinical rationale \
for an antibiotic recommendation that has ALREADY been decided by a deterministic \
rules engine. You do not choose drugs, doses, or modifiers — they are given to you \
as fixed facts. Frame the recommendation class-first: lead with the antibiotic \
class (drug_class) as the actual recommendation, then name the specific drug_name/ \
dose/frequency as one suggested starting agent within that class — not the only \
acceptable choice. Explain, in plain clinical language, why this fits the case: \
cite the source, severity, timing target, any applied modifiers, and any renal \
adjustment. If a deescalation object is present, describe it exactly as given: \
whether the current regimen is covered, any resistant_alert, and any \
narrower_regimen — do not propose a different de-escalation than what is given. \
If missing_inputs is non-empty, say so explicitly rather than ignoring it. Do not \
suggest a different class, drug, or dose than what is provided. Keep it to 3-5 \
sentences."""


def _fallback_rationale(regimen, modifiers, missing_inputs, deescalation=None) -> str:
    """Used only if the Claude API narration call fails. The deterministic
    regimen is the clinically important output — losing the whole
    recommendation because the prose-writing step failed would be a worse
    failure mode than showing a plain, templated summary."""
    if deescalation is not None:
        if deescalation.resistant_alert:
            return (
                "RESISTANT ALERT: culture shows the organism is not covered by any "
                "drug in the current regimen. Manual antibiotic selection is "
                "required immediately. (Automated narration unavailable; showing "
                "structured summary only.)"
            )
        if deescalation.narrower_regimen:
            d = deescalation.narrower_regimen[0]
            return (
                f"Culture-guided de-escalation available: current regimen is "
                f"covered, but a narrower option is susceptible — "
                f"{d.drug_class or 'unclassified'} (suggested agent: {d.drug_name} "
                f"{d.dose} {d.frequency}). Confirm before switching. "
                "(Automated narration unavailable; showing structured summary only.)"
            )
        return (
            "Culture-guided review: current regimen remains covered by "
            "susceptibility results; no narrower option identified. "
            "(Automated narration unavailable; showing structured summary only.)"
        )
    if not regimen:
        return (
            "No regimen could be determined from the knowledge base for this "
            "source/severity combination. Manual antibiotic selection is required."
        )
    drug_list = ", ".join(
        f"{r.drug_class or 'unclassified'} (suggested agent: {r.drug_name} {r.dose} {r.frequency})"
        for r in regimen
    )
    parts = [f"Recommended class(es): {drug_list}."]
    if modifiers:
        parts.append(
            "Modifiers applied: " + "; ".join(m.action_taken for m in modifiers) + "."
        )
    if missing_inputs:
        parts.append(f"Note — incomplete input data: {', '.join(missing_inputs)}.")
    parts.append("(Automated narration unavailable; showing structured summary only.)")
    return " ".join(parts)


async def _narrate(request: AntibioticRequest, regimen, modifiers, fungal_flag, missing_inputs, deescalation=None) -> str:
    facts = {
        "severity": request.severity.value,
        "suspected_source": request.suspected_source.value,
        "regimen": [r.model_dump() for r in regimen],
        "applied_modifiers": [m.model_dump() for m in modifiers],
        "fungal_flag": fungal_flag.model_dump() if fungal_flag else None,
        "missing_inputs": missing_inputs,
        "deescalation": deescalation.model_dump() if deescalation else None,
    }
    if client is None or not os.environ.get("ANTHROPIC_API_KEY"):
        return _fallback_rationale(regimen, modifiers, missing_inputs, deescalation)
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            system=NARRATION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": str(facts)}],
        )
        return "".join(block.text for block in response.content if block.type == "text")
    except Exception as exc:  # noqa: BLE001 — narration failure must not lose the regimen
        import logging
        logging.getLogger("sepsis_bundle.antibiotic_specialist").error(
            "Narration call failed, falling back to templated summary: %s", exc,
            extra={"case_id": request.case_id},
        )
        return _fallback_rationale(regimen, modifiers, missing_inputs, deescalation)


async def get_recommendation(request: AntibioticRequest) -> AntibioticResponse:
    kb = load_knowledge_base()
    timing_target = 1 if request.severity.value == "septic_shock" else 3
    warnings = []
    if request.documented_allergies:
        warnings.append(
            f"Documented allergies on file ({', '.join(request.documented_allergies)}) — "
            "verify against proposed regimen before administration."
        )

    if request.request_type == RequestType.DEESCALATION:
        # Culture result is in — no new empirical regimen is chosen here.
        # We only evaluate the existing (current_regimen) choice against the
        # deterministic KB/spectrum logic.
        deescalation = evaluate_deescalation(request, kb)
        if deescalation.resistant_alert:
            warnings.append(
                "RESISTANT ALERT — culture shows the organism is not covered by "
                "any drug in the current regimen. Manual antibiotic selection is "
                "required immediately."
            )
        rationale = await _narrate(request, [], [], None, [], deescalation)
        return AntibioticResponse(
            case_id=request.case_id,
            request_type=request.request_type,
            knowledge_base_version=kb.get("version", "unknown"),
            timing_target_hours=timing_target,
            recommended_regimen=[],
            applied_modifiers=[],
            fungal_flag=None,
            deescalation=deescalation,
            warnings=warnings,
            rationale=rationale,
            missing_inputs=[],
        )

    regimen, modifiers, fungal_flag, missing_inputs = select_regimen(request, kb)
    if any(m.startswith("CRITICAL_") for m in missing_inputs):
        warnings.append(
            "No regimen could be determined automatically — manual antibiotic "
            "selection is required for this case."
        )

    rationale = await _narrate(request, regimen, modifiers, fungal_flag, missing_inputs)
    reassessment_due_at = request.onset_timestamp + timedelta(hours=REASSESSMENT_WINDOW_HOURS)

    return AntibioticResponse(
        case_id=request.case_id,
        request_type=request.request_type,
        knowledge_base_version=kb.get("version", "unknown"),
        timing_target_hours=timing_target,
        recommended_regimen=regimen,
        applied_modifiers=modifiers,
        fungal_flag=fungal_flag,
        warnings=warnings,
        rationale=rationale,
        missing_inputs=missing_inputs,
        reassessment_due_at=reassessment_due_at,
    )

