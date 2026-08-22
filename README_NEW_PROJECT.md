# Sepsis Bundle — Five-Agent Clinical Decision Support

Standalone successor project to the original Sepsis Bundle Agent. The legacy app is intentionally not required at runtime.

## Architecture

1. **Sepsis Bundle / Orchestrator** — deterministic SOFA + case orchestration.
2. **Antibiotic Specialist** — deterministic regimen selection from the active immutable KB; optional LLM narration only.
3. **Guideline Surveillance** — scheduled, non-patient-facing surveillance; changes become pending human review items.
4. **Memory & Clinical Analytics** — pseudonymized longitudinal snapshots and aggregate analytics; not a treatment recommender.
5. **Governance / Safety Monitor** — deterministic validation boundary, policy matrix, audit trail, and fail-closed release.

**Physician remains the final decision-maker.** Governance can block a recommendation; it never invents or changes therapy.

## Safety boundaries

- No LLM selects antibiotic drug/dose/frequency.
- Active KB versions are immutable and require explicit human approval.
- Guideline fetching is blocked unless the source is explicitly `VERIFIED` in the source registry.
- Governance validates the AntibioticResponse against the deterministic rules engine.
- Unknown governance findings fail closed.
- Audit events are hash-chained and tamper-evident.
- Memory stores a pseudonymous patient key in its development adapter and produces aggregate analytics.

## Run locally

```bash
cd backend
python -m pip install -r ../requirements.txt
uvicorn app:app --reload
```

Then open `/docs` in the local FastAPI server.

## Test

```bash
cd backend
PYTHONPATH=. pytest -q ../tests
```

## Important clinical readiness note

The included antibiotic KB is a **scaffold**, not a production clinical guideline. Before clinical use it must be replaced/validated against the institution's approved antimicrobial guidance, local antibiogram, formulary, renal dosing policy, allergy policy, and the currently approved sepsis/antimicrobial-stewardship guidelines. This repository is a software architecture and safety-governance implementation, not a substitute for clinical validation.
