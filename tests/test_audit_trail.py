import json
from pathlib import Path

import audit_trail


def test_audit_event_is_append_only_and_chain_verifies(tmp_path, monkeypatch):
    log = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit_trail, "AUDIT_LOG_PATH", log)
    audit_trail.append_event("TEST_EVENT", case_id="CASE-1", agent="governance_layer", status="PASS", payload={"x": 1})
    audit_trail.append_event("TEST_EVENT_2", case_id="CASE-1", actor="clinician", status="APPROVED")
    assert audit_trail.verify_chain() == (True, None)


def test_audit_tampering_is_detected(tmp_path, monkeypatch):
    log = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit_trail, "AUDIT_LOG_PATH", log)
    audit_trail.append_event("TEST_EVENT", case_id="CASE-1", status="PASS", payload={"x": 1})
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    rows[0]["status"] = "BLOCK"
    log.write_text("\n".join(json.dumps(x, sort_keys=True, separators=(",", ":")) for x in rows) + "\n")
    valid, error = audit_trail.verify_chain()
    assert not valid
    assert "hash_mismatch" in error
