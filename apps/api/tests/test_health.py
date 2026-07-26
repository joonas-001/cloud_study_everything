from pathlib import Path

from fastapi.testclient import TestClient

from cloud_study_api.main import app


def test_health_initializes_sqlite_and_reports_repository_state(
    tmp_path: Path, monkeypatch: object
) -> None:
    database_path = tmp_path / "health-test.db"
    monkeypatch.setenv("CLOUD_STUDY_DATABASE_PATH", str(database_path))  # type: ignore[attr-defined]

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "cloud-study-api",
        "database_schema_version": "0001",
        "registered_skill_packages": 1,
    }
    assert database_path.is_file()
