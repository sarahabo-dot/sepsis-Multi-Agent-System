"""Minimal standalone FastAPI entry point for the new five-agent project.
No legacy application/database is required to run the deterministic core.
"""
from datetime import datetime
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from antibiotic_agent_schema import Severity, SuspectedSource, RiskFactors, ActiveDrug, CultureResult
from five_agent_orchestrator import assess_case, deescalate_case
from sofa_calculator import SofaInput, ClinicalValue, PressorState
from urine_output_conversion import convert_urine_output_to_24h
from memory_agent import JsonlMemoryStore, MemoryAnalyticsAgent
from guideline_versioning import get_active_version_id, bootstrap_initial_version
import guideline_versioning as versioning
import auth
from guideline_surveillance_agent import (
    list_pending_reviews,
    approve_pending_review,
    reject_pending_review,
    run_surveillance_check,
)
from audit_trail import recent_events
from pathlib import Path
import os

BASE = Path(__file__).parent
MEMORY_SECRET = os.environ.get("MEMORY_SECRET", "development-only-change-me")
MEMORY_PATH = os.environ.get("MEMORY_PATH", str(BASE / "memory.jsonl"))
FRONTEND_DIR = BASE.parent / "frontend"

app = FastAPI(title="Sepsis Bundle — Five Agent Clinical Decision Support", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://sepsis-multi-agent-system.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(FRONTEND_DIR / "index.html")
memory_agent = MemoryAnalyticsAgent(JsonlMemoryStore(MEMORY_PATH))

@app.on_event("startup")
def startup():
    if get_active_version_id() is None:
        bootstrap_initial_version(BASE / "antibiotic_knowledge_base.json")

# --- Authentication ---------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str

class BootstrapRequest(BaseModel):
    username: str
    password: str

class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "physician"

def require_auth(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_or_invalid_authorization_header")
    token = authorization.removeprefix("Bearer ").strip()
    user = auth.get_user_from_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="invalid_or_expired_session")
    return user

@app.get("/auth/status")
def auth_status():
    return {"has_users": auth.any_users_exist()}

@app.post("/auth/bootstrap")
def auth_bootstrap(req: BootstrapRequest):
    """One-time first-run account creation. Only works while zero users
    exist — once the first account is made, new accounts require an
    existing logged-in user (see /auth/users)."""
    if auth.any_users_exist():
        raise HTTPException(status_code=403, detail="already_bootstrapped_use_login")
    try:
        auth.create_user(req.username, req.password, role="physician", created_by="bootstrap")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    token = auth.create_session(req.username)
    return {"token": token, "username": req.username, "role": "physician"}

@app.post("/auth/login")
def auth_login(req: LoginRequest):
    user = auth.authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="invalid_username_or_password")
    token = auth.create_session(user["username"])
    return {"token": token, "username": user["username"], "role": user["role"]}

@app.post("/auth/logout")
def auth_logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.startswith("Bearer "):
        auth.revoke_session(authorization.removeprefix("Bearer ").strip())
    return {"status": "logged_out"}

@app.get("/auth/me")
def auth_me(user: dict = Depends(require_auth)):
    return user

@app.post("/auth/users")
def auth_create_user(req: CreateUserRequest, actor: dict = Depends(require_auth)):
    """Any logged-in user can add a colleague — deliberately simple for a
    small clinical team with no separate admin tier yet."""
    try:
        auth.create_user(req.username, req.password, role=req.role, created_by=actor["username"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "created", "username": req.username}

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
    urine_output_value: float | None = None
    urine_output_unit: str | None = "ml_24h"  # "ml_24h" (measured total) or "ml_kg_hr" (rate, projected)
    weight_kg: float | None = None
    mdr_risk_factors: list[str] = []
    mrsa_risk_factors: list[str] = []
    anaerobic_risk_factors: list[str] = []
    fungal_risk_factors: list[str] = []
    documented_allergies: list[str] = []

class SensitivityMap(BaseModel):
    organism: str
    sensitivities: dict[str, str]  # drug_name -> "S" / "I" / "R"

class DeescalateRequest(BaseModel):
    case_id: str
    severity: Severity
    suspected_source: SuspectedSource
    current_regimen_drug_names: list[str]  # what the patient is on right now
    culture: SensitivityMap
    creatinine: float | None = None
    documented_allergies: list[str] = []

@app.get("/health")
def health():
    return {"status":"ok","active_kb_version":get_active_version_id()}

@app.get("/analytics")
def analytics(user: dict = Depends(require_auth)):
    return memory_agent.aggregate()

@app.get("/audit")
def audit(limit: int = 25, case_id: str | None = None, user: dict = Depends(require_auth)):
    return {"events": recent_events(limit=limit, case_id=case_id)}

class ApproveReviewRequest(BaseModel):
    updated_kb_content: dict

class RejectReviewRequest(BaseModel):
    reason: str

@app.get("/guidelines/status")
def guidelines_status(user: dict = Depends(require_auth)):
    pending = list_pending_reviews()
    return {
        "active_version": get_active_version_id(),
        "versions": versioning.list_versions(),
        "pending": pending,
        "pending_count": len(pending),
        "overdue_count": sum(1 for r in pending if r.get("overdue")),
    }

@app.get("/guidelines/active-kb")
def guidelines_active_kb(user: dict = Depends(require_auth)):
    """Convenience for the review form — the reviewer edits a copy of the
    currently active KB rather than typing one from scratch."""
    try:
        return versioning.load_active_knowledge_base()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.post("/guidelines/{review_id}/approve")
def guidelines_approve(review_id: str, req: ApproveReviewRequest, user: dict = Depends(require_auth)):
    try:
        version_id = approve_pending_review(review_id, user["username"], req.updated_kb_content)
        return {"status": "approved", "version_id": version_id}
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.post("/guidelines/{review_id}/reject")
def guidelines_reject(review_id: str, req: RejectReviewRequest, user: dict = Depends(require_auth)):
    try:
        reject_pending_review(review_id, user["username"], req.reason)
        return {"status": "rejected"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.post("/guidelines/check")
async def guidelines_check(user: dict = Depends(require_auth)):
    """Manual trigger for Agent 3's surveillance sweep. Source acquisition
    itself (_fetch_source_topic_text) is not yet implemented for any source
    — see guideline_surveillance_agent.py — so this currently returns 0 new
    reviews until a licensed source is wired in. Kept exposed so that wiring
    a real source later needs no frontend change."""
    reviews = await run_surveillance_check()
    return {"new_reviews": len(reviews)}

@app.post("/deescalate")
async def deescalate(req: DeescalateRequest, user: dict = Depends(require_auth)):
    now = datetime.utcnow()
    result = await deescalate_case(
        case_id=req.case_id,
        current_regimen=[ActiveDrug(drug_name=n, started_at=now) for n in req.current_regimen_drug_names],
        culture_result=CultureResult(
            organism=req.culture.organism,
            sensitivities=req.culture.sensitivities,
            collected_at=now,
            resulted_at=now,
        ),
        severity=req.severity,
        suspected_source=req.suspected_source,
        onset_timestamp=now,
        creatinine_mg_dl=req.creatinine,
        documented_allergies=req.documented_allergies,
    )
    return result

@app.post("/assess")
async def assess(req: AssessRequest, user: dict = Depends(require_auth)):
    urine_24h, urine_note = convert_urine_output_to_24h(
        req.urine_output_value, req.urine_output_unit, req.weight_kg
    )
    # A note that is actually an unresolvable problem (unit given without
    # weight, or an unknown unit) must not be silently treated as "no
    # urine data" — surface it so the physician sees why the renal SOFA
    # component didn't get a urine value.
    urine_output_error = None
    if req.urine_output_value is not None and urine_24h is None:
        urine_output_error = urine_note

    # Same silent-downgrade risk as urine output: a vasopressor named
    # without a dose must not quietly score as "no vasopressor running" —
    # that's a full cardiovascular SOFA point difference (or more) for
    # exactly the septic-shock patients this tool targets.
    pressor_error = None
    if req.pressor_drug not in (None, "", "none") and req.pressor_dose is None:
        pressor_error = f"vasopressor_dose_missing_for:{req.pressor_drug}"

    sofa = SofaInput(
        pao2_fio2=ClinicalValue(req.pao2_fio2) if req.pao2_fio2 is not None else None,
        platelets=ClinicalValue(req.platelets) if req.platelets is not None else None,
        bilirubin=ClinicalValue(req.bilirubin) if req.bilirubin is not None else None,
        map_mmhg=ClinicalValue(req.map_mmhg) if req.map_mmhg is not None else None,
        pressor=PressorState(req.pressor_drug, req.pressor_dose),
        gcs=ClinicalValue(req.gcs) if req.gcs is not None else None,
        creatinine=ClinicalValue(req.creatinine) if req.creatinine is not None else None,
        urine_output_24h=ClinicalValue(urine_24h, source=req.urine_output_unit or "ml_24h")
            if urine_24h is not None else None,
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
        result["urine_output_note"] = urine_note if urine_24h is not None else None
        result["urine_output_error"] = urine_output_error
        result["pressor_error"] = pressor_error
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

