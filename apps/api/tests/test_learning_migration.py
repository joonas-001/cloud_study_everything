from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from cloud_study_api.database import (
    create_database_engine,
    create_database_url,
    read_schema_version,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _migration_config(database_path: Path) -> Config:
    config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(REPOSITORY_ROOT / "apps" / "api" / "migrations"),
    )
    config.set_main_option(
        "sqlalchemy.url",
        create_database_url(database_path).replace("%", "%%"),
    )
    return config


def test_existing_milestone_three_database_upgrades_to_indeterminate_status(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "upgrade.db"
    config = _migration_config(database_path)
    command.upgrade(config, "0003")
    engine = create_database_engine(database_path)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO source_check_runs (
                        id, skill_id, skill_version, local_date, trigger, status,
                        checked_count, changed_count, failed_count, started_at, completed_at
                    ) VALUES (
                        'existing-run', 'algorithm', '0.1.0', '2026-07-27', 'manual',
                        'completed', 1, 0, 0, '2026-07-27 08:00:00',
                        '2026-07-27 08:00:00'
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO source_check_results (
                        id, run_id, source_id, source_title, status, checked_at
                    ) VALUES (
                        'existing-result', 'existing-run', 'python-tutorial',
                        'The Python Tutorial', 'baseline_created',
                        '2026-07-27 08:00:00'
                    )
                    """
                )
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    assert read_schema_version(database_path) == "0005"
    engine = create_database_engine(database_path)
    try:
        with engine.begin() as connection:
            assert (
                connection.execute(
                    text("SELECT status FROM source_check_results WHERE id = 'existing-result'")
                ).scalar_one()
                == "baseline_created"
            )
            connection.execute(
                text(
                    """
                    INSERT INTO source_check_results (
                        id, run_id, source_id, source_title, status, checked_at
                    ) VALUES (
                        'indeterminate-result', 'existing-run', 'mit-ocw-6006',
                        'Introduction to Algorithms', 'indeterminate',
                        '2026-07-28 08:00:00'
                    )
                    """
                )
            )
    finally:
        engine.dispose()

    command.downgrade(config, "0003")

    assert read_schema_version(database_path) == "0003"
    engine = create_database_engine(database_path)
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT status FROM source_check_results WHERE id = 'indeterminate-result'"
                    )
                ).scalar_one()
                == "manual"
            )
    finally:
        engine.dispose()


def test_upgrade_freezes_open_0_1_intake_with_audit_history(tmp_path: Path) -> None:
    database_path = tmp_path / "freeze-legacy.db"
    config = _migration_config(database_path)
    command.upgrade(config, "0004")
    engine = create_database_engine(database_path)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO diagnostic_sessions (
                        id, skill_id, skill_version, is_preview, provider_id, model_id,
                        credential_reference, external_ai_consent,
                        external_ai_consent_at, status, current_question_id,
                        created_at, updated_at, last_activity_at, ended_at, end_reason
                    ) VALUES (
                        'legacy-diagnostic', 'algorithm', '0.1.0', 1,
                        'local-deterministic', 'diagnostic-v1', NULL, 0, NULL,
                        'active', 'programming-background',
                        '2026-07-27 08:00:00', '2026-07-27 08:00:00',
                        '2026-07-27 08:00:00', NULL, NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO planning_proposals (
                        id, diagnostic_session_id, skill_id, skill_version,
                        template_id, provider_id, model_id, is_preview, status,
                        title, rationale, limitations_json, created_at, updated_at
                    ) VALUES (
                        'legacy-plan', 'legacy-diagnostic', 'algorithm', '0.1.0',
                        'algorithm-common-trunk-entry', 'local-deterministic',
                        'planner-sim-v1', 1, 'draft', 'legacy', 'legacy',
                        '[]', '2026-07-27 08:00:00', '2026-07-27 08:00:00'
                    )
                    """
                )
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_database_engine(database_path)
    try:
        with engine.connect() as connection:
            diagnostic = connection.execute(
                text(
                    """
                    SELECT status, end_reason
                    FROM diagnostic_sessions
                    WHERE id = 'legacy-diagnostic'
                    """
                )
            ).one()
            assert diagnostic == ("ended", "version_intake_closed")
            assert (
                connection.execute(
                    text("SELECT status FROM planning_proposals WHERE id = 'legacy-plan'")
                ).scalar_one()
                == "frozen_preview"
            )
            assert (
                connection.execute(
                    text(
                        """
                        SELECT event_type
                        FROM diagnostic_events
                        WHERE session_id = 'legacy-diagnostic'
                        """
                    )
                ).scalar_one()
                == "version_intake_closed"
            )
            assert (
                connection.execute(
                    text(
                        """
                        SELECT event_type
                        FROM planning_change_events
                        WHERE proposal_id = 'legacy-plan'
                        """
                    )
                ).scalar_one()
                == "planning_preview_frozen"
            )
    finally:
        engine.dispose()
