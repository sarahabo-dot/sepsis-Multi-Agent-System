from fastapi.testclient import TestClient
import app


def test_health_and_assess(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "MEMORY_PATH", str(tmp_path / "memory.jsonl"))
    monkeypatch.setattr(app, "memory_agent", app.MemoryAnalyticsAgent(app.JsonlMemoryStore(str(tmp_path / "memory.jsonl"))))
    with TestClient(app.app) as client:
        h = client.get('/health')
        assert h.status_code == 200
        payload = {
            "case_id":"CASE-INT-1","patient_id":"PAT-1","severity":"septic_shock","suspected_source":"urinary",
            "pao2_fio2":350,"platelets":180,"bilirubin":1.0,"map_mmhg":75,"pressor_drug":"none","gcs":15,"creatinine":1.0,"urine_output_24h":1000
        }
        r = client.post('/assess', json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body['sofa']['total'] == 1
        assert body['antibiotic'] is not None
        assert body['governance']['status'] == 'PASS'
