# Handoff Checklist — Antibiotic Specialist Agent Integration

**Purpose:** everything you need to pick this back up later — during a
study break, after Step 1, or whenever — without having to reconstruct
context from scratch.

---

## File manifest — where everything goes

| File | Goes in | Status |
|---|---|---|
| `api_main_PATCHED.py` | replaces `api/main.py` | ✅ ready to deploy |
| `requirements_PATCHED.txt` | replaces `requirements.txt` | ✅ ready (adds `anthropic`) |
| `urine_output_conversion.py` | same dir as `sofa_calculator.py` | ✅ ready |
| `antibiotic_agent_schema.py` | same dir as `models.py` | ✅ ready |
| `antibiotic_rules_engine.py` | same dir as `models.py` | ✅ ready |
| `antibiotic_specialist_agent.py` | same dir as `models.py` | ✅ ready |
| `antibiotic_knowledge_base.json` | project root (path used by bootstrap) | ⚠️ scaffold — needs pharmacist/ID review |
| `guideline_versioning.py` | same dir as `models.py` | ✅ ready |
| `synthesis_layer.py` | reference only — not wired into the DB-backed API (superseded by direct endpoint calls) | 📎 keep for reference |
| `antibiotic_orchestrator.py` | reference only — same reason as above | 📎 keep for reference |
| `test_fixtures_antibiotic.py` | test directory | ✅ for local testing |
| `test_antibiotic_pipeline.py` | test directory | ✅ 20/20 passing |
| `guideline_surveillance_agent.py` | **do not deploy yet** | ⏸️ paused — license gate |
| `config/source_registry.json` | **do not deploy yet** | ⏸️ paused — license gate |
| `AntibioticRecommendationCard.jsx` | frontend components dir | ⚠️ built from screenshots, needs verification against real component |
| `ADR-antibiotic-multiagent-architecture.md` | docs | 📎 reference |
| `READINESS_ASSESSMENT.md` | docs | 📎 reference — the honest "is it ready" answer |
| `INTEGRATION_PATCH_api_main.md` | docs | 📎 explains the reasoning behind `api_main_PATCHED.py` |
| `INTEGRATION_PATCH_urine_output.md` | docs | 📎 explains the reasoning behind the urine output fix |

---

## Before deploying `api_main_PATCHED.py`

1. **Diff it against your current `api/main.py`** — I worked from the copy
   you pasted into chat; if you've changed anything since, re-paste the
   current version and I'll re-apply the patch on top of it.
2. **Copy the 6 new Python files + JSON** listed above into the right
   directories.
3. **Run `pip install -r requirements_PATCHED.txt`** (adds `anthropic`).
4. **Set `ANTHROPIC_API_KEY`** in your environment if it isn't already
   (the existing `/interpretation` endpoint already needs this, so it's
   likely already set).
5. **Deploy to a staging/dev environment first**, not directly to
   production — this is new, freshly-tested code, not battle-tested code.
6. **Confirm the bootstrap worked**: after first startup, check that
   `kb_versions/` was created and `antibiotic_versioning.get_active_version_id()`
   returns something. If `/antibiotic/recommend` 503s immediately, this is
   the first thing to check.

## Before using it on any real patient

This is the line that matters most — repeating it here because it's easy
to lose track of once the code is deployed and "just works":

1. **Pharmacist/ID physician review of `antibiotic_knowledge_base.json`.**
   Every drug, dose, and interval in it is a placeholder.
2. **License verification for SCCM/IDSA** before Agent 3 (guideline
   surveillance) is ever turned on. Currently structurally impossible —
   `check_license_gate()` blocks it — so this can wait without risk.
3. **Regulatory pathway assessment** for this specific feature (separate
   from the SOFA/Bundle EDA pathway already documented).

## Known gaps, explicitly not fixed (by choice, not oversight)

- `guideline_surveillance_agent._fetch_source_topic_text()` still raises
  `NotImplementedError`. Correct as-is until licensing is confirmed.
- The frontend card (`AntibioticRecommendationCard.jsx`) was built from
  screenshots, not real source — colors/tokens are a best guess. Send the
  real component file when you're ready and I'll match it exactly instead
  of guessing.
- No dedicated `AntibioticRecommendationRecord` DB table — recommendations
  are logged via the existing `record_audit()` mechanism. Fine for now;
  revisit if you need efficient querying later ("all antibiotic
  recommendations for patient X" currently means filtering audit events).
- De-escalation (culture-guided) logic exists in the schema
  (`DeescalationAdvice`, `resistant_alert`) but isn't wired into
  `/antibiotic/recommend` yet — that endpoint is EMPIRICAL-only for now.

## If you come back to this after a break, start here

1. Re-read `READINESS_ASSESSMENT.md` first — it's the single source of
   truth for "what's actually done."
2. Check whether `antibiotic_knowledge_base.json` has been reviewed yet —
   if not, that's still the biggest blocker to real use, not more code.
3. If the government conversation has moved forward, revisit the
   licensing question before touching Agent 3 again.
