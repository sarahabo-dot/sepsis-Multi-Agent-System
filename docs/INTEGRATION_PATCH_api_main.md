# Integration patch: /antibiotic/recommend into api/main.py

This is written as a patch, not a full file replacement, because I don't
have database.py/auth.py/agent.py — only main.py and sofa_calculator.py.
Follow the 4 steps below in order.

---

## Step 1 — Add imports near the top of api/main.py

Add these alongside the existing imports (after the `from agent import ...` line):

```python
from antibiotic_agent_schema import AntibioticRequest, RiskFactors, Severity, SuspectedSource, RequestType
from antibiotic_specialist_agent import get_recommendation as get_antibiotic_recommendation
import guideline_versioning as antibiotic_versioning
```

Also copy these files into the same directory as `sofa_calculator.py` (i.e.
wherever `models.py` lives, since `antibiotic_rules_engine.py` imports from
there too):

```
antibiotic_agent_schema.py
antibiotic_rules_engine.py
antibiotic_specialist_agent.py
antibiotic_knowledge_base.json
guideline_versioning.py
```

(`guideline_surveillance_agent.py` and `config/source_registry.json` are
NOT needed for this step — those are only for Agent 3, which is still
paused pending license verification. Don't deploy them yet.)

---

## Step 2 — Bootstrap the antibiotic knowledge base on startup

Mirrors the existing `seed_default_user_if_configured()` pattern — same
idea, applied to the KB instead of the first user account.

Add this function near `seed_default_user_if_configured`:

```python
def bootstrap_antibiotic_kb_if_needed():
    """One-time setup: registers the scaffold antibiotic_knowledge_base.json
    as the first active version if no version has been activated yet. Safe
    to leave this call in permanently — it only acts when no active version
    exists, same pattern as the default-user seeding above."""
    if antibiotic_versioning.get_active_version_id() is not None:
        return
    kb_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "antibiotic_knowledge_base.json")
    antibiotic_versioning.bootstrap_initial_version(kb_path)
```

And call it in `on_startup`, right after `seed_default_user_if_configured()`:

```python
@app.on_event("startup")
def on_startup():
    init_db()
    seed_default_user_if_configured()
    bootstrap_antibiotic_kb_if_needed()
```

---

## Step 3 — Add the request schema

Add this next to the other schema classes (`SofaRequest`, `BundleStartRequest`, etc.):

```python
class AntibioticRecommendRequest(BaseModel):
    patient_id: str
    severity: str  # "sepsis" | "septic_shock"
    suspected_source: str  # "urinary" | "respiratory" | "abdominal" | "skin_soft_tissue" |
                            # "cns" | "bloodstream_unknown" | "other" | "undifferentiated"
    weight_kg: Optional[float] = None
    mdr_risk_factors: list[str] = []
    mrsa_risk_factors: list[str] = []
    anaerobic_risk_factors: list[str] = []
    fungal_risk_factors: list[str] = []
    documented_allergies: list[str] = []
    # De-escalation (culture-guided) is a documented future extension, not
    # wired in this endpoint yet — request_type is fixed to EMPIRICAL here.
```

**Note on `weight_kg`:** `SofaRequest` doesn't currently capture weight, so
this endpoint captures it directly rather than silently depending on a
field that doesn't exist yet. If weight becomes something you want tracked
per-session generally (not just for antibiotic dosing), that's a separate,
deliberate change to `ClinicalValueRecord`/`SofaRequest` — not something to
fold in here without your review.

---

## Step 4 — Add the endpoint itself

Add this after the `/sofa/calculate` endpoint (same section — deterministic,
authenticated, reuses the same DB session pattern):

```python
@app.post("/antibiotic/recommend")
async def antibiotic_recommend(
    req: AntibioticRecommendRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Agent 2 (Antibiotic Specialist). Independent of /sofa/calculate —
    the frontend should call both in parallel (e.g. Promise.all), not
    sequentially. If this endpoint fails, /sofa/calculate must still have
    already returned or be in flight; nothing here should ever gate SOFA
    results. Regimen selection is deterministic (antibiotic_rules_engine.py);
    only the `rationale` text comes from Claude, and only after the regimen
    is already fixed.
    """
    session = get_or_create_session(db, req.patient_id)

    # Reuse already-captured values instead of asking the physician to
    # re-enter creatinine/bilirubin — same principle as build_antibiotic_request
    # in the original design, adapted to this DB-backed session model.
    creatinine = last_confirmed_value(db, session.id, "creatinine")
    bilirubin = last_confirmed_value(db, session.id, "bilirubin")

    try:
        severity = Severity(req.severity)
        source = SuspectedSource(req.suspected_source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid severity or suspected_source: {exc}")

    case_id = f"{req.patient_id}-{uuid.uuid4().hex[:8]}"

    antibiotic_request = AntibioticRequest(
        case_id=case_id,
        request_type=RequestType.EMPIRICAL,
        severity=severity,
        suspected_source=source,
        onset_timestamp=datetime.utcnow(),
        creatinine_mg_dl=creatinine,
        bilirubin_mg_dl=bilirubin,
        weight_kg=req.weight_kg,
        risk_factors=RiskFactors(
            mdr_risk_factors=req.mdr_risk_factors,
            mrsa_risk_factors=req.mrsa_risk_factors,
            anaerobic_risk_factors=req.anaerobic_risk_factors,
            fungal_risk_factors=req.fungal_risk_factors,
        ),
        documented_allergies=req.documented_allergies,
    )

    try:
        response = await get_antibiotic_recommendation(antibiotic_request)
    except Exception as exc:  # noqa: BLE001 — this endpoint must degrade, not 500 silently
        record_audit(db, user.username, "antibiotic_recommendation_failed", {
            "patient_id": req.patient_id, "case_id": case_id, "error": str(exc),
        })
        raise HTTPException(
            status_code=503,
            detail="Antibiotic recommendation temporarily unavailable. SOFA/Bundle data is unaffected.",
        )

    record_audit(db, user.username, "antibiotic_recommendation_generated", {
        "patient_id": req.patient_id,
        "case_id": case_id,
        "knowledge_base_version": response.knowledge_base_version,
        "regimen": [r.model_dump() for r in response.recommended_regimen],
        "applied_modifiers": [m.model_dump() for m in response.applied_modifiers],
        "warnings": response.warnings,
        "missing_inputs": response.missing_inputs,
    })

    return {
        "case_id": case_id,
        "knowledge_base_version": response.knowledge_base_version,
        "timing_target_hours": response.timing_target_hours,
        "recommended_regimen": [r.model_dump() for r in response.recommended_regimen],
        "applied_modifiers": [m.model_dump() for m in response.applied_modifiers],
        "fungal_flag": response.fungal_flag.model_dump() if response.fungal_flag else None,
        "warnings": response.warnings,
        "rationale": response.rationale,
        "missing_inputs": response.missing_inputs,
    }
```

---

## What this deliberately does NOT do

- **Does not touch `/sofa/calculate` or `/bundle/*` at all.** Zero risk of
  regressing the existing, working SOFA/Bundle logic.
- **Does not require dual sign-off** at the API level (unlike
  `/bundle/confirm`) — this endpoint only proposes a recommendation, it
  doesn't record that a drug was administered. If you later add an
  "antibiotic administered" confirmation action (parallel to
  `bundle_confirm`), THAT action should require dual sign-off, same as
  other high-risk bundle items — the recommendation step itself is
  read-only, same governance class as `/interpretation` and `/agent/consult`.
- **Does not add a new SQLAlchemy table.** The recommendation is logged via
  the existing `record_audit()` mechanism, same as everything else in
  `main.py`. If you later want to query "all antibiotic recommendations for
  patient X" efficiently rather than filtering audit events, that's a
  deliberate follow-up (a dedicated `AntibioticRecommendationRecord` table
  in `database.py`) — not done here to avoid touching your DB schema
  without your review.
- **Does not wire Agent 3** (guideline surveillance). Only Agent 2 is
  connected. This matches the readiness assessment — Agent 3's fetch
  function still deliberately raises `NotImplementedError` pending license
  verification.

---

## Frontend integration note

To get the "SOFA isn't blocked by antibiotic failure" property at the HTTP
level (not just inside a Python orchestrator), call both endpoints in
parallel from the frontend, e.g.:

```javascript
const [sofaResult, antibioticResult] = await Promise.allSettled([
  fetch('/sofa/calculate', { method: 'POST', body: ... }),
  fetch('/antibiotic/recommend', { method: 'POST', body: ... }),
]);
// Render sofaResult regardless of antibioticResult's outcome.
// Promise.allSettled (not Promise.all) is what matters here — it never
// rejects the whole batch just because one call failed.
```
