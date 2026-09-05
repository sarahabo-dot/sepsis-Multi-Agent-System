"""
memory_agent.py
Agent 4 — longitudinal clinical memory and analytics.

The Memory Agent is NOT a treatment recommender. It stores structured,
auditable case snapshots and computes aggregate statistics.

Privacy-by-design:
- the persistence adapter should store a pseudonymous patient key rather than
  direct identifiers in analytics tables;
- raw clinical records remain in the application's existing protected DB;
- analytics are aggregate by default;
- no LLM is required for storage or statistics.

The module uses a small adapter protocol so it can be connected to the
project's SQLAlchemy database without assuming a particular database.py
implementation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from statistics import mean
from typing import Any, Protocol


def pseudonymize_patient_id(patient_id: str, secret: str) -> str:
    """Stable HMAC-like pseudonym without storing the original identifier."""
    import hmac
    return hmac.new(
        secret.encode("utf-8"),
        patient_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@dataclass
class ClinicalMemoryRecord:
    case_id: str
    patient_key: str
    recorded_at: datetime
    severity: str
    suspected_source: str
    sofa_total: float | None = None
    timing_target_hours: int | None = None
    antibiotic_kb_version: str | None = None
    antibiotic_governance_status: str | None = None
    antibiotic_error: str | None = None
    regimen: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["recorded_at"] = self.recorded_at.isoformat()
        return d


class MemoryStore(Protocol):
    def append(self, record: ClinicalMemoryRecord) -> None: ...
    def query(self, *, patient_key: str | None = None) -> list[ClinicalMemoryRecord]: ...


class JsonlMemoryStore:
    """Development adapter only. Production should use the protected DB."""

    def __init__(self, path: str):
        self.path = path

    def append(self, record: ClinicalMemoryRecord) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def query(self, *, patient_key: str | None = None) -> list[ClinicalMemoryRecord]:
        try:
            with open(self.path, encoding="utf-8") as f:
                rows = [json.loads(line) for line in f if line.strip()]
        except FileNotFoundError:
            return []

        result = []
        for row in rows:
            if patient_key is not None and row["patient_key"] != patient_key:
                continue
            row["recorded_at"] = datetime.fromisoformat(row["recorded_at"])
            result.append(ClinicalMemoryRecord(**row))
        return result


class MemoryAnalyticsAgent:
    """Computes non-generative analytics from stored structured records."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def record_case(self, record: ClinicalMemoryRecord) -> None:
        self.store.append(record)

    def patient_history(self, patient_key: str) -> list[ClinicalMemoryRecord]:
        return self.store.query(patient_key=patient_key)

    def aggregate(self) -> dict[str, Any]:
        records = self.store.query()
        if not records:
            return {
                "case_count": 0,
                "septic_shock_rate": None,
                "antibiotic_governance_block_rate": None,
                "mean_sofa": None,
                "missing_input_rate": None,
                "governance_pass_count": 0,
                "governance_blocked_count": 0,
            }

        sofa_values = [r.sofa_total for r in records if r.sofa_total is not None]
        shock = sum(r.severity == "septic_shock" for r in records)
        blocked = sum(r.antibiotic_governance_status == "BLOCK" for r in records)
        passed = sum(r.antibiotic_governance_status == "PASS" for r in records)
        missing = sum(bool(r.missing_inputs) for r in records)

        return {
            "case_count": len(records),
            "septic_shock_rate": shock / len(records),
            "antibiotic_governance_block_rate": blocked / len(records),
            "mean_sofa": mean(sofa_values) if sofa_values else None,
            "missing_input_rate": missing / len(records),
            # Explicit counts alongside the rates above — the frontend
            # displays raw counts next to case_count, not rates, so these
            # are provided directly rather than making the UI recompute
            # (count = rate * case_count) from a rate field.
            "governance_pass_count": passed,
            "governance_blocked_count": blocked,
        }
