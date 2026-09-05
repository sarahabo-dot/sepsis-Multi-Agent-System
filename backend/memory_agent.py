"""
memory_agent.py
Agent 4 — longitudinal clinical memory and analytics.

The Memory Agent is NOT a treatment recommender. It stores structured,
auditable case snapshots and computes aggregate statistics — including
outbreak-style pattern signals (organism clustering, device-exposure
association). These signals are statistical flags for infection-control /
epidemiologist review, never a causal diagnosis. "3 cases share an organism
and a device exposure" is a hypothesis to investigate, not a finding.

Privacy-by-design:
- the persistence adapter should store a pseudonymous patient key rather than
  direct identifiers in analytics tables;
- raw clinical records remain in the application's existing protected DB;
- analytics are aggregate by default;
- no LLM is required for storage, statistics, or pattern detection — cluster
  and association detection here is deterministic counting/thresholding,
  the same "AI proposes, physician decides" boundary as every other agent.

The module uses a small adapter protocol so it can be connected to the
project's SQLAlchemy database without assuming a particular database.py
implementation.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
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
    # record_type distinguishes an initial assessment (device exposures are
    # known at this point) from a later culture-result update (organism is
    # known once the lab result comes back) — the two arrive at different
    # times for the same case_id/patient_key and are joined by case_id when
    # computing pattern signals.
    record_type: str = "assessment"  # "assessment" | "culture_result"
    organism: str | None = None
    device_exposures: dict[str, Any] = field(default_factory=dict)
    # e.g. {"mechanical_ventilation": true, "central_line_hours": 52,
    #       "urinary_catheter_hours": 60}

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
            # Backward compatibility: records written before these fields
            # existed simply won't have them — dataclass defaults cover it,
            # so only pass through keys the dataclass actually knows about.
            known = {"case_id", "patient_key", "recorded_at", "severity", "suspected_source",
                     "sofa_total", "timing_target_hours", "antibiotic_kb_version",
                     "antibiotic_governance_status", "antibiotic_error", "regimen",
                     "warnings", "missing_inputs", "record_type", "organism", "device_exposures"}
            row = {k: v for k, v in row.items() if k in known}
            result.append(ClinicalMemoryRecord(**row))
        return result


class MemoryAnalyticsAgent:
    """Computes non-generative analytics from stored structured records,
    including deterministic outbreak-style pattern signals."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def record_case(self, record: ClinicalMemoryRecord) -> None:
        self.store.append(record)

    def record_culture_result(
        self, *, case_id: str, patient_key: str, organism: str, recorded_at: datetime | None = None
    ) -> None:
        """Called from the de-escalation path once a culture result names an
        organism. Appended as its own record (this store is append-only) and
        joined back to the originating assessment by case_id when computing
        pattern signals."""
        self.store.append(ClinicalMemoryRecord(
            case_id=case_id,
            patient_key=patient_key,
            recorded_at=recorded_at or datetime.utcnow(),
            severity="", suspected_source="",
            record_type="culture_result",
            organism=organism,
        ))

    def patient_history(self, patient_key: str) -> list[ClinicalMemoryRecord]:
        return self.store.query(patient_key=patient_key)

    def aggregate(self) -> dict[str, Any]:
        records = self.store.query()
        assessments = [r for r in records if r.record_type == "assessment"]
        if not assessments:
            return {
                "case_count": 0,
                "septic_shock_rate": None,
                "antibiotic_governance_block_rate": None,
                "mean_sofa": None,
                "missing_input_rate": None,
                "governance_pass_count": 0,
                "governance_blocked_count": 0,
            }

        sofa_values = [r.sofa_total for r in assessments if r.sofa_total is not None]
        shock = sum(r.severity == "septic_shock" for r in assessments)
        blocked = sum(r.antibiotic_governance_status == "BLOCK" for r in assessments)
        passed = sum(r.antibiotic_governance_status == "PASS" for r in assessments)
        missing = sum(bool(r.missing_inputs) for r in assessments)

        return {
            "case_count": len(assessments),
            "septic_shock_rate": shock / len(assessments),
            "antibiotic_governance_block_rate": blocked / len(assessments),
            "mean_sofa": mean(sofa_values) if sofa_values else None,
            "missing_input_rate": missing / len(assessments),
            "governance_pass_count": passed,
            "governance_blocked_count": blocked,
        }

    def _organism_by_case(self) -> dict[str, str]:
        """Latest known organism per case_id, from culture_result records."""
        records = self.store.query()
        by_case: dict[str, tuple[datetime, str]] = {}
        for r in records:
            if r.record_type == "culture_result" and r.organism:
                prev = by_case.get(r.case_id)
                if prev is None or r.recorded_at > prev[0]:
                    by_case[r.case_id] = (r.recorded_at, r.organism)
        return {cid: org for cid, (_, org) in by_case.items()}

    def detect_organism_clusters(self, window_hours: int = 168, min_count: int = 3) -> list[dict[str, Any]]:
        """Flag organisms appearing in >= min_count distinct cases within a
        rolling window_hours (default 7 days). This is a raw-count signal —
        it does not know about unit/ward, so a real deployment should scope
        it by care unit before treating it as an outbreak alert."""
        organism_by_case = self._organism_by_case()
        if not organism_by_case:
            return []

        assessments = {r.case_id: r for r in self.store.query() if r.record_type == "assessment"}
        cutoff = datetime.utcnow() - timedelta(hours=window_hours)

        grouped: dict[str, list[str]] = defaultdict(list)
        for case_id, organism in organism_by_case.items():
            case = assessments.get(case_id)
            recorded_at = case.recorded_at if case else None
            if recorded_at is not None and recorded_at < cutoff:
                continue
            grouped[organism].append(case_id)

        clusters = []
        for organism, case_ids in grouped.items():
            if len(case_ids) >= min_count:
                clusters.append({
                    "organism": organism,
                    "case_count": len(case_ids),
                    "case_ids": case_ids,
                    "window_hours": window_hours,
                })
        return sorted(clusters, key=lambda c: -c["case_count"])

    def detect_device_associations(
        self, min_count: int = 2, device_threshold_hours: float = 48,
    ) -> list[dict[str, Any]]:
        """For each organism with >= min_count cases (no time window — this
        looks across all recorded cases), check what fraction shared a device
        exposure above device_threshold_hours (or mechanical ventilation).
        Surfaced as a hypothesis for infection-control review — co-occurrence
        is not causation, and this makes no claim about the ward, technique,
        or individual clinician."""
        organism_by_case = self._organism_by_case()
        assessments = {r.case_id: r for r in self.store.query() if r.record_type == "assessment"}

        grouped: dict[str, list[str]] = defaultdict(list)
        for case_id, organism in organism_by_case.items():
            grouped[organism].append(case_id)

        device_fields = {
            "central_line_hours": "central line",
            "urinary_catheter_hours": "urinary catheter",
        }
        hypotheses = []
        for organism, case_ids in grouped.items():
            if len(case_ids) < min_count:
                continue
            for field_name, label in device_fields.items():
                exposed = [
                    cid for cid in case_ids
                    if assessments.get(cid) and (assessments[cid].device_exposures.get(field_name) or 0) >= device_threshold_hours
                ]
                if len(exposed) >= min_count:
                    hypotheses.append({
                        "organism": organism,
                        "device": label,
                        "threshold_hours": device_threshold_hours,
                        "matching_case_count": len(exposed),
                        "total_organism_case_count": len(case_ids),
                        "case_ids": exposed,
                    })
            vent_cases = [
                cid for cid in case_ids
                if assessments.get(cid) and assessments[cid].device_exposures.get("mechanical_ventilation")
            ]
            if len(vent_cases) >= min_count:
                hypotheses.append({
                    "organism": organism,
                    "device": "mechanical ventilation",
                    "threshold_hours": None,
                    "matching_case_count": len(vent_cases),
                    "total_organism_case_count": len(case_ids),
                    "case_ids": vent_cases,
                })
        return hypotheses

    def pattern_signals(self) -> dict[str, Any]:
        return {
            "organism_clusters": self.detect_organism_clusters(),
            "device_associations": self.detect_device_associations(),
        }
