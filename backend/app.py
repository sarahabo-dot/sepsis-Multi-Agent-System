"""Minimal standalone FastAPI entry point for the new five-agent project.
No legacy application/database is required to run the deterministic core.
"""
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from antibiotic_agent_schema import Severity, SuspectedSource, RiskFactors
from five_agent_orchestrator import assess_case
from sofa_calculator import SofaInput, ClinicalValue, PressorState
from memory_agent import JsonlMemoryStore, MemoryAnalyticsAgent
from guideline_versioning import get_active_version_id, bootstrap_initial_version
from pathlib import Path
import os

BASE = Path(__file__).parent
MEMORY_SECRET = os.environ.get("MEMORY_SECRET", "development-only-change-me")
MEMORY_PATH = os.environ.get("MEMORY_PATH", str(BASE / "memory.jsonl"))
FRONTEND_DIR = BASE.parent / "frontend"

app = FastAPI(title="Sepsis Bundle — Five Agent Clinical Decision Support", version="0.1.0")

@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(FRONTEND_DIR / "index.html")
memory_agent = MemoryAnalyticsAgent(JsonlMemoryStore(MEMORY_PATH))

@app.on_event("startup")
def startup():
    if get_active_version_id() is None:
        bootstrap_initial_version(BASE / "antibiotic_knowledge_base.json")

class AssessRequest(BaseModel):
    case_id: str
    patient_id: str
    severity: Severity
    suspected_source: SuspectedSource
    pao2_fio2: float | None = None
    platelets: float | None = None
    bilirubin: float | None = None
    map_mmhg: float | None = None
    pressor_drug: str = "none"
    pressor_dose: float | None = None
    gcs: float | None = None
    creatinine: float | None = None
    urine_output_24h: float | None = None
    weight_kg: float | None = None
    mdr_risk_factors: list[str] = []
    mrsa_risk_factors: list[str] = []
    anaerobic_risk_factors: list[str] = []
    fungal_risk_factors: list[str] = []
    documented_allergies: list[str] = []

@app.get("/health")
def health():
    return {"status":"ok","active_kb_version":get_active_version_id()}

@app.get("/analytics")
def analytics():
    return memory_agent.aggregate()

@app.post("/assess")
async def assess(req: AssessRequest):
    sofa = SofaInput(
        pao2_fio2=ClinicalValue(req.pao2_fio2) if req.pao2_fio2 is not None else None,
        platelets=ClinicalValue(req.platelets) if req.platelets is not None else None,
        bilirubin=ClinicalValue(req.bilirubin) if req.bilirubin is not None else None,
        map_mmhg=ClinicalValue(req.map_mmhg) if req.map_mmhg is not None else None,
        pressor=PressorState(req.pressor_drug, req.pressor_dose),
        gcs=ClinicalValue(req.gcs) if req.gcs is not None else None,
        creatinine=ClinicalValue(req.creatinine) if req.creatinine is not None else None,
        urine_output_24h=ClinicalValue(req.urine_output_24h) if req.urine_output_24h is not None else None,
    )
    try:
        result = await assess_case(
            case_id=req.case_id, patient_id=req.patient_id, sofa_input=sofa,
            severity=req.severity, suspected_source=req.suspected_source,
            onset_timestamp=datetime.utcnow(),
            risk_factors=RiskFactors(
                mdr_risk_factors=req.mdr_risk_factors,
                mrsa_risk_factors=req.mrsa_risk_factors,
                anaerobic_risk_factors=req.anaerobic_risk_factors,
                fungal_risk_factors=req.fungal_risk_factors,
            ), documented_allergies=req.documented_allergies,
            memory_agent=memory_agent, memory_secret=MEMORY_SECRET,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
