from __future__ import annotations

import argparse
import json
from pathlib import Path

from cloud_study_api.backups import BackupError
from cloud_study_api.migration_rehearsal import run_migration_rehearsal

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the 6C encrypted real-data migration and rollback rehearsal.",
    )
    parser.add_argument("--source-database", type=Path, required=True)
    parser.add_argument("--encrypted-backup", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument(
        "--confirm-writes-stopped",
        action="store_true",
        help="required acknowledgement that all writers were stopped before the snapshot",
    )
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    if arguments.report.exists() or arguments.report.is_symlink():
        print(json.dumps({"ok": False, "error": "report path already exists"}))
        return 1
    try:
        report = run_migration_rehearsal(
            arguments.source_database,
            arguments.encrypted_backup,
            arguments.public_key,
            arguments.private_key,
            REPOSITORY_ROOT,
            operator=arguments.operator,
            writes_stopped=arguments.confirm_writes_stopped,
        )
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (BackupError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {"ok": True, "status": report["status"], "report": str(arguments.report)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
