# Release manifest — v0.1.0

This archive is the standalone new project. It does not depend on the legacy Sepsis Bundle Agent repository.

Included:
- five-agent orchestrator
- deterministic SOFA calculator
- deterministic antibiotic rules engine + immutable KB versioning
- guideline surveillance + license gate + human approval gate
- governance layer + policy matrix + fail-closed validation
- tamper-evident audit trail
- pseudonymized memory/analytics adapter
- standalone FastAPI API (`backend/app.py`)
- automated unit/integration tests
- Dockerfile and environment template
- Acequia-inspired visual identity specification

Intentionally excluded:
- patient-identifying production data
- real guideline content copied from publishers
- legacy database/auth application code
- production credentials/secrets
- production deployment configuration

Validation performed for this release:
- Python compile check
- 41 automated tests passing
