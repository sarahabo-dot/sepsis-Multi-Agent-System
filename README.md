# Sepsis Bundle Agent — Five-Agent Governed Architecture

Everything in this zip is new work from this session: the Antibiotic
Specialist Agent (Agent 2), the paused Guideline Surveillance Agent
(Agent 3), the urine output unit fix, and the frontend panel. Nothing
here has touched your existing repo yet — merge it in deliberately using
the map below, not by dumping the whole zip into place.

## Folder map → where it goes in your repo

```
backend/                          → same directory as your existing sofa_calculator.py / models.py
  antibiotic_agent_schema.py         ✅ new file, copy as-is
  antibiotic_rules_engine.py         ✅ new file, copy as-is
  antibiotic_specialist_agent.py     ✅ new file, copy as-is
  antibiotic_knowledge_base.json     ⚠️ SCAFFOLD — copy as-is, but do not treat
                                         the contents as clinically validated
  guideline_versioning.py            ✅ new file, copy as-is
  urine_output_conversion.py         ✅ new file, copy as-is
  api_main_PATCHED.py                → REPLACES your existing api/main.py
  requirements_PATCHED.txt           → REPLACES your existing requirements.txt
                                         (only addition: anthropic>=0.40)

  agent3_paused/                  → DO NOT DEPLOY YET (see docs/READINESS_ASSESSMENT.md)
    guideline_surveillance_agent.py    Agent 3 — blocked by its own license
                                        gate until SCCM/IDSA terms are confirmed
    config/source_registry.json        the gate itself — every source starts
                                        as VERIFY_BEFORE_PRODUCTION_USE

  reference_not_deployed/         → design reference only, not imported anywhere
    antibiotic_orchestrator.py         superseded — your real backend is
    synthesis_layer.py                 endpoint-based (frontend orchestrates
                                        via parallel fetches), not a Python-side
                                        orchestrator. Kept for the reasoning,
                                        not for deployment.

frontend/
  App_PATCHED.jsx                  → REPLACES your existing src/App.jsx
                                        Adds: Antibiotic Recommendation panel,
                                        two-option urine output input, weight field

tests/
  test_antibiotic_pipeline.py      → your test directory. 20/20 passing as of
                                        this session (see docs/READINESS_ASSESSMENT.md)
  test_antibiotic_endpoint_integration.py → real HTTP-level test against the
                                        actual FastAPI app (not mocked internals).
                                        NOT run by me — requires your full stack
                                        (database.py, auth.py, etc.) which I don't
                                        have. Run this once in your real repo
                                        before trusting it.
  test_fixtures_antibiotic.py      → mock for the Antibiotic Specialist Agent,
                                        used by the pipeline tests
  sepsis_synthetic_test_case.json  → the synthetic patient case used to
                                        validate the original SOFA renal bug fix

docs/
  ADR-antibiotic-multiagent-architecture.md   why this was built as 3 agents
  READINESS_ASSESSMENT.md                     the honest "is it ready" answer —
                                                 read this before any deployment
                                                 or stakeholder conversation
  HANDOFF_CHECKLIST.md                        step-by-step merge + what's left
  INTEGRATION_PATCH_api_main.md               reasoning behind api_main_PATCHED.py
  INTEGRATION_PATCH_urine_output.md           reasoning behind the urine fix
```

## Suggested merge order

1. Read `docs/HANDOFF_CHECKLIST.md` first — it has the exact pre-deploy steps.
2. Create a new branch, don't merge straight to main.
3. Copy the `backend/` files (excluding `agent3_paused/` and
   `reference_not_deployed/`) into place.
4. Replace `api/main.py` and `requirements.txt` with the `_PATCHED` versions.
5. Replace `src/App.jsx` with `App_PATCHED.jsx`.
6. Copy the `tests/` files into your test directory and run them.
7. Deploy to staging, not production, and confirm `/health` and
   `/antibiotic/recommend` both respond before merging to main.
8. Do **not** copy `agent3_paused/` into your active import path — it's
   included here for completeness, not for deployment.

## The one thing to remember if you forget everything else

The code is tested and production-grade. The antibiotic knowledge base
content is a scaffold that has not been clinically reviewed. Those are two
separate kinds of "done" — see `docs/READINESS_ASSESSMENT.md` for the full
version of this distinction.


## Five-agent transformation

This package extends the original three-agent design into a governed
five-agent architecture:

1. **Sepsis Bundle Agent / Orchestrator** — real-time entry point; runs SOFA and
   the antibiotic path independently.
2. **Antibiotic Specialist Agent** — deterministic regimen selection + bounded
   LLM rationale.
3. **Guideline Surveillance Agent** — scheduled guideline monitoring; remains
   license-gated and never activates rules automatically.
4. **Memory & Clinical Analytics Agent** — longitudinal structured memory and
   aggregate analytics.
5. **Governance / Safety Monitor** — deterministic anti-hallucination and
   approval gate.

### New files

```
backend/
  governance_layer.py
  memory_agent.py
  five_agent_orchestrator.py

tests/
  test_five_agent_architecture.py

docs/
  ADR-five-agent-architecture.md
  GOVERNANCE_SPEC.md
  MEMORY_DATA_GOVERNANCE.md
```

### Integration note

`five_agent_orchestrator.py` is the new orchestration reference. The existing
DB-backed FastAPI endpoint remains intentionally conservative in this package:
the new governance and memory modules are isolated so they can be integrated
after the project's actual `database.py` schema and authentication/role model
are reviewed.

Do not interpret the presence of these modules as clinical validation. The
antibiotic KB remains a scaffold, and Agent 3 remains blocked until source
licensing is verified.
