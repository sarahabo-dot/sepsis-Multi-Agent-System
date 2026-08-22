from pathlib import Path

ROOT = Path(__file__).parents[1]
FRONTEND = ROOT / "frontend"


def test_frontend_assets_exist():
    assert (FRONTEND / "index.html").exists()
    assert (FRONTEND / "styles.css").exists()
    assert (FRONTEND / "app.js").exists()


def test_frontend_has_safety_language():
    html = (FRONTEND / "index.html").read_text()
    assert "PHYSICIAN DECIDES" in html
    assert "Governance" in html
    assert "Memory & Analytics" in html


def test_frontend_calls_governed_api():
    js = (FRONTEND / "app.js").read_text()
    assert "'/assess'" in js
    assert "'/analytics'" in js
    assert "'/health'" in js


def test_api_root_serves_frontend():
    import app
    from fastapi.testclient import TestClient
    client = TestClient(app.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Sepsis Bundle" in response.text
