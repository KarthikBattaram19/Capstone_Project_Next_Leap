from fastapi.testclient import TestClient

from scout.config import Settings
from scout.main import create_app


def test_health_and_contract(bundle_min):
    app = create_app(
        Settings(
            _env_file=None, cors_allowed_origins="http://localhost:3000", bundle_dir=bundle_min
        )
    )
    c = TestClient(app)
    assert c.get("/health").json() == {"status": "ok", "contract_version": "1"}
    assert c.get("/contract").json()["contract_version"] == "1"
