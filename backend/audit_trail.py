"""Append-only, tamper-evident audit trail for the five-agent architecture.

This module is deliberately deterministic and has no LLM/network dependency.
Each event is canonicalized, chained to the previous event hash, and appended
as one JSON object per line. The audit trail records governance decisions and
human guideline actions; it is not the clinical record and must not be used as
one.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

AUDIT_LOG_PATH = Path(os.environ.get("SEPSIS_AUDIT_LOG_PATH", Path(__file__).parent / "audit_trail.jsonl"))
GENESIS_HASH = "0" * 64


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _last_hash() -> str:
    if not AUDIT_LOG_PATH.exists():
        return GENESIS_HASH
    last = None
    with AUDIT_LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                last = json.loads(line)
    return last.get("event_hash", GENESIS_HASH) if last else GENESIS_HASH


def append_event(
    event_type: str,
    *,
    case_id: Optional[str] = None,
    actor: str = "system",
    agent: Optional[str] = None,
    status: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Append one immutable audit event and return the stored event.

    The event hash covers the event body plus the previous event hash. Any
    later deletion/reordering/modification in the chain becomes detectable by
    verify_chain().
    """
    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    previous_hash = _last_hash()
    event = {
        "event_id": hashlib.sha256(f"{_utc_now()}:{event_type}:{case_id}:{previous_hash}".encode()).hexdigest()[:24],
        "timestamp": _utc_now(),
        "event_type": event_type,
        "case_id": case_id,
        "actor": actor,
        "agent": agent,
        "status": status,
        "payload": payload or {},
        "previous_hash": previous_hash,
    }
    event["event_hash"] = hashlib.sha256(_canonical(event).encode("utf-8")).hexdigest()
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(_canonical(event) + "\n")
    return event


def verify_chain() -> tuple[bool, Optional[str]]:
    """Verify ordering and hashes. Returns (valid, error_message)."""
    if not AUDIT_LOG_PATH.exists():
        return True, None
    previous = GENESIS_HASH
    with AUDIT_LOG_PATH.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                return False, f"invalid_json:line={line_no}"
            if event.get("previous_hash") != previous:
                return False, f"chain_break:line={line_no}"
            supplied = event.get("event_hash")
            unsigned = dict(event)
            unsigned.pop("event_hash", None)
            expected = hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest()
            if supplied != expected:
                return False, f"hash_mismatch:line={line_no}"
            previous = supplied
    return True, None
