from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from cloud_study_api.backups import (
    BackupError,
    apply_backup_retention,
    create_encrypted_backup,
    generate_backup_key_pair,
    inspect_encrypted_backup,
    restore_encrypted_backup,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create and verify encrypted 云奕学 SQLite backups.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    keygen = subparsers.add_parser("keygen", help="generate a new offline RSA key pair")
    keygen.add_argument("--private-key", type=Path, required=True)
    keygen.add_argument("--public-key", type=Path, required=True)

    create = subparsers.add_parser("create", help="create an encrypted SQLite backup")
    create.add_argument("--database", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--public-key", type=Path, required=True)
    create.add_argument("--policy-id", default="single-user-singapore")
    create.add_argument("--policy-version", default="1.0.0")

    scheduled = subparsers.add_parser(
        "scheduled",
        help="create a timestamped backup and apply confirmed retention",
    )
    scheduled.add_argument("--database", type=Path, required=True)
    scheduled.add_argument("--output-directory", type=Path, required=True)
    scheduled.add_argument("--public-key", type=Path, required=True)
    scheduled.add_argument("--policy-id", default="single-user-singapore")
    scheduled.add_argument("--policy-version", default="1.0.0")

    inspect = subparsers.add_parser("inspect", help="show non-secret envelope metadata")
    inspect.add_argument("--backup", type=Path, required=True)

    restore = subparsers.add_parser(
        "restore",
        help="restore and validate into a new database path",
    )
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--target-database", type=Path, required=True)
    restore.add_argument("--private-key", type=Path, required=True)

    retention = subparsers.add_parser(
        "retention",
        help="plan or apply the confirmed 7-daily plus 4-weekly retention",
    )
    retention.add_argument("--backup-directory", type=Path, required=True)
    retention.add_argument(
        "--apply",
        action="store_true",
        help="delete expired strictly named artifacts; omitted means dry-run",
    )
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        result: dict[str, object]
        if arguments.command == "keygen":
            generate_backup_key_pair(arguments.private_key, arguments.public_key)
            result = {
                "private_key": str(arguments.private_key),
                "public_key": str(arguments.public_key),
                "warning": "Keep the private key offline; it is required for restoration.",
            }
        elif arguments.command == "create":
            result = create_encrypted_backup(
                arguments.database,
                arguments.output,
                arguments.public_key,
                policy_id=arguments.policy_id,
                policy_version=arguments.policy_version,
            )
        elif arguments.command == "scheduled":
            timestamp = datetime.now(UTC)
            output_directory = arguments.output_directory.resolve()
            output_directory.mkdir(parents=True, exist_ok=True)
            output_path = output_directory / timestamp.strftime(
                "cloud-study-%Y%m%dT%H%M%SZ.csbak"
            )
            manifest = create_encrypted_backup(
                arguments.database,
                output_path,
                arguments.public_key,
                policy_id=arguments.policy_id,
                policy_version=arguments.policy_version,
                now=timestamp,
            )
            removals = apply_backup_retention(output_directory, apply=True)
            result = {
                "artifact": str(output_path),
                "manifest": manifest,
                "expired_removed": [str(path) for path in removals],
            }
        elif arguments.command == "inspect":
            result = inspect_encrypted_backup(arguments.backup)
        elif arguments.command == "retention":
            removals = apply_backup_retention(
                arguments.backup_directory.resolve(),
                apply=arguments.apply,
            )
            result = {
                "applied": arguments.apply,
                "removals": [str(path) for path in removals],
            }
        else:
            result = restore_encrypted_backup(
                arguments.backup,
                arguments.target_database,
                arguments.private_key,
            )
    except BackupError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
