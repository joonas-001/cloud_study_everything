from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import sqlite3
import struct
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, BinaryIO, cast

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"CSBKP01\n"
FORMAT_VERSION = "1"
CHUNK_SIZE = 1024 * 1024
MAX_HEADER_BYTES = 64 * 1024
MAX_CHUNK_BYTES = CHUNK_SIZE + 32
MAX_DATABASE_BYTES = 32 * 1024 * 1024 * 1024
DATABASE_MEMBER = "database.sqlite3"
MANIFEST_MEMBER = "manifest.json"
BACKUP_NAME_PATTERN = re.compile(r"^cloud-study-(\d{8}T\d{6}Z)\.csbak$")


class BackupError(RuntimeError):
    """Raised when a backup cannot be created or safely restored."""


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _database_metadata(database_path: Path) -> dict[str, Any]:
    with closing(sqlite3.connect(database_path)) as database:
        quick_check = database.execute("PRAGMA quick_check").fetchone()
        if quick_check is None or quick_check[0] != "ok":
            raise BackupError("SQLite quick_check failed")
        foreign_key_errors = database.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise BackupError("SQLite foreign_key_check found violations")
        revision_row = database.execute("SELECT version_num FROM alembic_version").fetchone()
        if revision_row is None:
            raise BackupError("SQLite database has no Alembic revision")
        table_names = [
            cast(str, row[0])
            for row in database.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        table_rows: dict[str, int] = {}
        for table_name in table_names:
            escaped_name = table_name.replace('"', '""')
            row = database.execute(f'SELECT COUNT(*) FROM "{escaped_name}"').fetchone()
            table_rows[table_name] = 0 if row is None else int(row[0])
    return {
        "alembic_revision": str(revision_row[0]),
        "table_rows": table_rows,
    }


def _create_snapshot(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise BackupError("backup source must be a regular SQLite database file")
    try:
        with (
            closing(
                sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
            ) as source_database,
            closing(sqlite3.connect(destination)) as destination_database,
        ):
            source_database.backup(destination_database)
    except sqlite3.Error as error:
        raise BackupError("SQLite snapshot creation failed") from error


def _load_public_key(path: Path) -> rsa.RSAPublicKey:
    try:
        value = serialization.load_pem_public_key(path.read_bytes())
    except (OSError, ValueError, TypeError) as error:
        raise BackupError("backup public key could not be loaded") from error
    if not isinstance(value, rsa.RSAPublicKey) or value.key_size < 3072:
        raise BackupError("backup public key must be RSA with at least 3072 bits")
    return value


def _load_private_key(path: Path) -> rsa.RSAPrivateKey:
    try:
        value = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as error:
        raise BackupError("backup private key could not be loaded") from error
    if not isinstance(value, rsa.RSAPrivateKey) or value.key_size < 3072:
        raise BackupError("backup private key must be unencrypted RSA with at least 3072 bits")
    return value


def _write_frame(stream: BinaryIO, value: bytes) -> None:
    stream.write(struct.pack(">I", len(value)))
    stream.write(value)


def _read_exact(stream: BinaryIO, length: int) -> bytes:
    value = stream.read(length)
    if len(value) != length:
        raise BackupError("encrypted backup is truncated")
    return value


def _read_frames(stream: BinaryIO) -> Iterator[bytes]:
    while True:
        length = struct.unpack(">I", _read_exact(stream, 4))[0]
        if length == 0:
            if stream.read(1):
                raise BackupError("encrypted backup has trailing data")
            return
        if length > MAX_CHUNK_BYTES:
            raise BackupError("encrypted backup chunk exceeds the supported limit")
        yield _read_exact(stream, length)


def _copy_to_new_path(source_path: Path, destination_path: Path) -> None:
    created = False
    try:
        with source_path.open("rb") as source, destination_path.open("xb") as destination:
            created = True
            while chunk := source.read(CHUNK_SIZE):
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
    except OSError as error:
        if created:
            destination_path.unlink(missing_ok=True)
        raise BackupError("output could not be written without overwriting a file") from error


def create_encrypted_backup(
    database_path: Path,
    output_path: Path,
    public_key_path: Path,
    *,
    policy_id: str,
    policy_version: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create an authenticated, encrypted SQLite snapshot without overwriting an artifact."""
    if output_path.exists():
        raise BackupError("backup output already exists")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    public_key = _load_public_key(public_key_path)
    created_at = (now or datetime.now(UTC)).astimezone(UTC).isoformat()

    with tempfile.TemporaryDirectory(prefix="cloud-study-backup-") as temporary:
        temporary_root = Path(temporary)
        snapshot_path = temporary_root / DATABASE_MEMBER
        archive_path = temporary_root / "payload.zip"
        _create_snapshot(database_path, snapshot_path)
        metadata = _database_metadata(snapshot_path)
        manifest = {
            "format_version": FORMAT_VERSION,
            "created_at": created_at,
            "policy_id": policy_id,
            "policy_version": policy_version,
            "database": {
                "sha256": _sha256(snapshot_path),
                "bytes": snapshot_path.stat().st_size,
                **metadata,
            },
        }
        with zipfile.ZipFile(
            archive_path,
            mode="x",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            archive.writestr(MANIFEST_MEMBER, _canonical_json(manifest))
            archive.write(snapshot_path, DATABASE_MEMBER)

        data_key = AESGCM.generate_key(bit_length=256)
        nonce_prefix = os.urandom(8)
        wrapped_key = public_key.encrypt(
            data_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        header = {
            "format_version": FORMAT_VERSION,
            "algorithm": "RSA-OAEP-SHA256+AES-256-GCM",
            "created_at": created_at,
            "policy_id": policy_id,
            "policy_version": policy_version,
            "chunk_size": CHUNK_SIZE,
            "payload_sha256": _sha256(archive_path),
            "wrapped_key": base64.b64encode(wrapped_key).decode("ascii"),
            "nonce_prefix": base64.b64encode(nonce_prefix).decode("ascii"),
        }
        header_bytes = _canonical_json(header)
        temporary_output = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
        try:
            aes = AESGCM(data_key)
            with archive_path.open("rb") as source, temporary_output.open("xb") as output:
                output.write(MAGIC)
                _write_frame(output, header_bytes)
                counter = 0
                while plaintext := source.read(CHUNK_SIZE):
                    if counter >= 2**32:
                        raise BackupError("backup exceeds the supported chunk count")
                    nonce = nonce_prefix + counter.to_bytes(4, "big")
                    ciphertext = aes.encrypt(
                        nonce,
                        plaintext,
                        header_bytes + counter.to_bytes(4, "big"),
                    )
                    _write_frame(output, ciphertext)
                    counter += 1
                _write_frame(output, b"")
                output.flush()
                os.fsync(output.fileno())
            _copy_to_new_path(temporary_output, output_path)
        except (OSError, ValueError) as error:
            raise BackupError("encrypted backup creation failed") from error
        finally:
            temporary_output.unlink(missing_ok=True)
    return manifest


def inspect_encrypted_backup(backup_path: Path) -> dict[str, Any]:
    """Read untrusted envelope metadata without decrypting the authenticated payload."""
    try:
        with backup_path.open("rb") as stream:
            if _read_exact(stream, len(MAGIC)) != MAGIC:
                raise BackupError("encrypted backup has an unsupported format")
            header_length = struct.unpack(">I", _read_exact(stream, 4))[0]
            if header_length == 0 or header_length > MAX_HEADER_BYTES:
                raise BackupError("encrypted backup header exceeds the supported limit")
            value = json.loads(_read_exact(stream, header_length))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise BackupError("encrypted backup header could not be read") from error
    if not isinstance(value, dict) or value.get("format_version") != FORMAT_VERSION:
        raise BackupError("encrypted backup header is invalid")
    safe_keys = {
        "format_version",
        "algorithm",
        "created_at",
        "policy_id",
        "policy_version",
        "chunk_size",
        "payload_sha256",
    }
    return {key: value[key] for key in safe_keys if key in value}


def restore_encrypted_backup(
    backup_path: Path,
    target_database_path: Path,
    private_key_path: Path,
) -> dict[str, Any]:
    """Decrypt and validate a backup into a new SQLite path, never over an existing path."""
    if target_database_path.exists():
        raise BackupError("restore target already exists")
    target_database_path.parent.mkdir(parents=True, exist_ok=True)
    private_key = _load_private_key(private_key_path)

    with tempfile.TemporaryDirectory(
        prefix="cloud-study-restore-",
        dir=target_database_path.parent,
    ) as temporary:
        temporary_root = Path(temporary)
        archive_path = temporary_root / "payload.zip"
        restored_database = temporary_root / DATABASE_MEMBER
        try:
            with backup_path.open("rb") as source:
                if _read_exact(source, len(MAGIC)) != MAGIC:
                    raise BackupError("encrypted backup has an unsupported format")
                header_length = struct.unpack(">I", _read_exact(source, 4))[0]
                if header_length == 0 or header_length > MAX_HEADER_BYTES:
                    raise BackupError("encrypted backup header exceeds the supported limit")
                header_bytes = _read_exact(source, header_length)
                header = json.loads(header_bytes)
                if (
                    not isinstance(header, dict)
                    or header.get("format_version") != FORMAT_VERSION
                    or header.get("algorithm") != "RSA-OAEP-SHA256+AES-256-GCM"
                    or header.get("chunk_size") != CHUNK_SIZE
                ):
                    raise BackupError("encrypted backup header is invalid")
                wrapped_key = base64.b64decode(header["wrapped_key"], validate=True)
                nonce_prefix = base64.b64decode(header["nonce_prefix"], validate=True)
                if len(nonce_prefix) != 8:
                    raise BackupError("encrypted backup nonce is invalid")
                data_key = private_key.decrypt(
                    wrapped_key,
                    padding.OAEP(
                        mgf=padding.MGF1(algorithm=hashes.SHA256()),
                        algorithm=hashes.SHA256(),
                        label=None,
                    ),
                )
                aes = AESGCM(data_key)
                with archive_path.open("xb") as output:
                    for counter, ciphertext in enumerate(_read_frames(source)):
                        if counter >= 2**32:
                            raise BackupError("encrypted backup exceeds the supported chunk count")
                        nonce = nonce_prefix + counter.to_bytes(4, "big")
                        output.write(
                            aes.decrypt(
                                nonce,
                                ciphertext,
                                header_bytes + counter.to_bytes(4, "big"),
                            )
                        )
                if _sha256(archive_path) != header.get("payload_sha256"):
                    raise BackupError("encrypted backup payload digest does not match")
        except BackupError:
            raise
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            InvalidTag,
            binascii.Error,
            json.JSONDecodeError,
        ) as error:
            raise BackupError("encrypted backup authentication or decryption failed") from error

        try:
            with zipfile.ZipFile(archive_path, mode="r") as archive:
                if sorted(archive.namelist()) != [DATABASE_MEMBER, MANIFEST_MEMBER]:
                    raise BackupError("backup archive contains unexpected members")
                manifest_value = json.loads(archive.read(MANIFEST_MEMBER))
                if (
                    not isinstance(manifest_value, dict)
                    or manifest_value.get("format_version") != FORMAT_VERSION
                    or manifest_value.get("created_at") != header.get("created_at")
                    or manifest_value.get("policy_id") != header.get("policy_id")
                    or manifest_value.get("policy_version") != header.get("policy_version")
                ):
                    raise BackupError("backup manifest is invalid")
                database_info = archive.getinfo(DATABASE_MEMBER)
                if database_info.file_size <= 0 or database_info.file_size > MAX_DATABASE_BYTES:
                    raise BackupError("backup SQLite member exceeds the supported size")
                with (
                    archive.open(DATABASE_MEMBER) as source,
                    restored_database.open("xb") as target,
                ):
                    while chunk := source.read(CHUNK_SIZE):
                        target.write(chunk)
        except BackupError:
            raise
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as error:
            raise BackupError("backup archive validation failed") from error

        database_manifest = manifest_value.get("database")
        if not isinstance(database_manifest, dict):
            raise BackupError("backup manifest has no database metadata")
        if restored_database.stat().st_size != database_manifest.get("bytes") or _sha256(
            restored_database
        ) != database_manifest.get("sha256"):
            raise BackupError("restored SQLite digest does not match the manifest")
        restored_metadata = _database_metadata(restored_database)
        if restored_metadata["alembic_revision"] != database_manifest.get("alembic_revision"):
            raise BackupError("restored SQLite revision does not match the manifest")
        if restored_metadata["table_rows"] != database_manifest.get("table_rows"):
            raise BackupError("restored SQLite row counts do not match the manifest")
        _copy_to_new_path(restored_database, target_database_path)
        return manifest_value


def generate_backup_key_pair(private_key_path: Path, public_key_path: Path) -> None:
    """Generate a new RSA key pair without overwriting either path."""
    if private_key_path.exists() or public_key_path.exists():
        raise BackupError("backup key output already exists")
    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    public_key_path.parent.mkdir(parents=True, exist_ok=True)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private_value = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_value = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_descriptor: int | None = None
    public_descriptor: int | None = None
    try:
        private_descriptor = os.open(
            private_key_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        os.write(private_descriptor, private_value)
        os.fsync(private_descriptor)
        os.close(private_descriptor)
        private_descriptor = None
        public_descriptor = os.open(
            public_key_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o644,
        )
        os.write(public_descriptor, public_value)
        os.fsync(public_descriptor)
        os.close(public_descriptor)
        public_descriptor = None
    except OSError as error:
        private_key_path.unlink(missing_ok=True)
        public_key_path.unlink(missing_ok=True)
        raise BackupError("backup key pair could not be written") from error
    finally:
        if private_descriptor is not None:
            os.close(private_descriptor)
        if public_descriptor is not None:
            os.close(public_descriptor)


def apply_backup_retention(
    backup_directory: Path,
    *,
    daily_retention: int = 7,
    weekly_retention: int = 4,
    apply: bool = False,
) -> list[Path]:
    """Plan or apply retention only to strictly named regular backup artifacts."""
    if daily_retention < 1 or weekly_retention < 1:
        raise BackupError("backup retention counts must be positive")
    if not backup_directory.is_absolute() or not backup_directory.is_dir():
        raise BackupError("backup directory must be an existing absolute directory")
    candidates: list[tuple[datetime, Path]] = []
    for path in backup_directory.iterdir():
        match = BACKUP_NAME_PATTERN.fullmatch(path.name)
        if match is None or not path.is_file() or path.is_symlink():
            continue
        try:
            timestamp = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        except ValueError:
            continue
        candidates.append((timestamp, path))
    candidates.sort(key=lambda item: item[0], reverse=True)

    kept_days: set[date] = set()
    kept_weeks: set[tuple[int, int]] = set()
    retained: set[Path] = set()
    for timestamp, path in candidates:
        day = timestamp.date()
        iso = timestamp.isocalendar()
        week = (iso.year, iso.week)
        if len(kept_days) < daily_retention and day not in kept_days:
            kept_days.add(day)
            retained.add(path)
        if len(kept_weeks) < weekly_retention and week not in kept_weeks:
            kept_weeks.add(week)
            retained.add(path)

    removals = [path for _timestamp, path in candidates if path not in retained]
    if apply:
        for path in removals:
            path.unlink()
    return removals
