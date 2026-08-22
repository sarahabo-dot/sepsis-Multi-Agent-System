"""Backward-compatible test/adapter boundary.
The new project uses five_agent_orchestrator.py as the canonical orchestrator.
This module keeps the old antibiotic-only contract available for migration tests.
"""
import asyncio
from datetime import datetime
from antibiotic_agent_schema import AntibioticRequest, RequestType, RiskFactors, Severity, SuspectedSource
from antibiotic_specialist_agent import get_recommendation
from sofa_calculator import calculate_sofa

async def _call_antibiotic_agent(request):
    return await get_recommendation(request)

def build_antibiotic_request(*, case_id, sofa_input, severity, suspected_source, onset_timestamp):
    if not case_id or not case_id.strip():
        raise ValueError("case_id must not be empty")
    return AntibioticRequest(
        case_id=case_id, request_type=RequestType.EMPIRICAL, severity=severity,
        suspected_source=suspected_source, onset_timestamp=onset_timestamp,
        creatinine_mg_dl=getattr(getattr(sofa_input, 'creatinine', None), 'value', None),
        bilirubin_mg_dl=getattr(getattr(sofa_input, 'bilirubin', None), 'value', None),
        weight_kg=getattr(sofa_input, 'weight_kg', None), risk_factors=RiskFactors(), documented_allergies=[]
    )

async def assess_case(*, case_id, sofa_input, severity, suspected_source, onset_timestamp):
    request = build_antibiotic_request(case_id=case_id, sofa_input=sofa_input, severity=severity, suspected_source=suspected_source, onset_timestamp=onset_timestamp)
    sofa_task = asyncio.create_task(asyncio.to_thread(calculate_sofa, sofa_input))
    try:
        antibiotic = await _call_antibiotic_agent(request)
        error = None
    except asyncio.TimeoutError:
        antibiotic, error = None, 'antibiotic_agent_timeout'
    except Exception:
        antibiotic, error = None, 'antibiotic_agent_error'
    sofa = await sofa_task
    return {'sofa': sofa, 'antibiotic': antibiotic, 'antibiotic_error': error}
