from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from cloud_study_api.main import app


def test_health_initializes_sqlite_and_returns_minimal_status(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    database_path = tmp_path / "health-test.db"
    monkeypatch.setenv("CLOUD_STUDY_DATABASE_PATH", str(database_path))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert database_path.is_file()
