from __future__ import annotations

import hashlib
import json
import sqlite3
import stat
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from app.migrations import CURRENT_SCHEMA_VERSION, VERBANODE_APPLICATION_ID

BACKUP_FORMAT_VERSION = 3
SUPPORTED_BACKUP_FORMATS = frozenset({1, 2, 3})
MAX_BACKUP_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_BACKUP_DATABASE_BYTES = 1024 * 1024 * 1024
MAX_BACKUP_MANIFEST_BYTES = 64 * 1024
MAX_BACKUP_ARCHIVE_MEMBERS = 8


class BackupError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ValidatedBackup:
    database_path: Path
    manifest: dict[str, object]
    schema_version: int
    sha256: str
    size_bytes: int


def sha256_path(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise BackupError("Backup contains an unsafe archive path")
    return normalized


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def validate_archive_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_BACKUP_ARCHIVE_MEMBERS:
        raise BackupError("Backup contains too many archive members")
    members: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        name = _safe_member_name(info.filename)
        if name in members:
            raise BackupError("Backup contains duplicate archive members")
        if _is_zip_symlink(info):
            raise BackupError("Backup archive symlinks are not allowed")
        if not info.is_dir():
            members[name] = info
    return members


def read_manifest(archive: zipfile.ZipFile, members: dict[str, zipfile.ZipInfo]) -> dict[str, object]:
    info = members.get("backup.json")
    if info is None:
        return {"format_version": 1}
    if info.file_size > MAX_BACKUP_MANIFEST_BYTES:
        raise BackupError("Backup manifest is too large", status_code=413)
    try:
        raw = archive.read(info)
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, KeyError) as exc:
        raise BackupError("Backup manifest is invalid") from exc
    if not isinstance(manifest, dict):
        raise BackupError("Backup manifest is invalid")

    try:
        format_version = int(manifest.get("format_version", 1) or 1)
    except (TypeError, ValueError) as exc:
        raise BackupError("Backup format version is invalid") from exc
    if format_version not in SUPPORTED_BACKUP_FORMATS:
        if format_version > BACKUP_FORMAT_VERSION:
            raise BackupError(
                f"Backup format {format_version} is newer than this VerbaNode build "
                f"({BACKUP_FORMAT_VERSION})",
                status_code=409,
            )
        raise BackupError(f"Unsupported backup format version: {format_version}")

    product = manifest.get("product")
    if product is not None and product != "VerbaNode":
        raise BackupError("Backup belongs to a different product")
    if format_version >= 3 and product != "VerbaNode":
        raise BackupError("Backup v3 manifest is missing the VerbaNode product identity")
    try:
        schema_version = int(manifest.get("schema_version", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise BackupError("Backup schema version is invalid") from exc
    if schema_version < 0:
        raise BackupError("Backup schema version is invalid")
    if schema_version > CURRENT_SCHEMA_VERSION:
        raise BackupError(
            f"Backup schema {schema_version} is newer than this VerbaNode installation "
            f"({CURRENT_SCHEMA_VERSION})",
            status_code=409,
        )
    if format_version >= 3:
        database = manifest.get("database")
        if not isinstance(database, dict):
            raise BackupError("Backup v3 database metadata is missing")
        if not str(database.get("name") or ""):
            raise BackupError("Backup v3 database name is missing")
        if database.get("size_bytes") is None or database.get("sha256") is None:
            raise BackupError("Backup v3 integrity metadata is incomplete")
    return manifest


def _database_metadata(manifest: dict[str, object]) -> tuple[str, int | None, str | None]:
    value = manifest.get("database")
    if isinstance(value, dict):
        name = str(value.get("name") or "")
        try:
            size = int(value["size_bytes"]) if value.get("size_bytes") is not None else None
        except (TypeError, ValueError) as exc:
            raise BackupError("Backup database size metadata is invalid") from exc
        checksum = str(value.get("sha256") or "").lower() or None
        if checksum is not None and (
            len(checksum) != 64 or any(ch not in "0123456789abcdef" for ch in checksum)
        ):
            raise BackupError("Backup database checksum metadata is invalid")
        return name, size, checksum
    if isinstance(value, str):
        return value, None, None
    return "", None, None


def database_member(
    members: dict[str, zipfile.ZipInfo], manifest: dict[str, object]
) -> tuple[zipfile.ZipInfo, int | None, str | None]:
    preferred, expected_size, expected_sha256 = _database_metadata(manifest)
    candidates = [preferred, "verbanode.db", "verbanode_standalone.db"]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        info = members.get(_safe_member_name(candidate))
        if info is None or info.is_dir():
            continue
        if info.file_size > MAX_BACKUP_DATABASE_BYTES:
            raise BackupError("Backup database is too large", status_code=413)
        if expected_size is not None and expected_size != info.file_size:
            raise BackupError("Backup database size does not match its manifest")
        return info, expected_size, expected_sha256
    raise BackupError("Backup database is missing")


def extract_member_verified(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    destination: Path,
    *,
    expected_sha256: str | None = None,
    max_bytes: int = MAX_BACKUP_DATABASE_BYTES,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info, "r") as source, destination.open("wb") as target:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                destination.unlink(missing_ok=True)
                raise BackupError("Backup database is too large", status_code=413)
            digest.update(chunk)
            target.write(chunk)
    checksum = digest.hexdigest()
    if expected_sha256 is not None and checksum != expected_sha256:
        destination.unlink(missing_ok=True)
        raise BackupError("Backup database checksum verification failed")
    return total, checksum


def validate_database(path: Path) -> int:
    try:
        with sqlite3.connect(path) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise BackupError("Backup database failed integrity check")
            tables = {
                str(row[0])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not {"settings", "agents"}.issubset(tables):
                raise BackupError("Backup is not a VerbaNode database")

            application_id = int(conn.execute("PRAGMA application_id").fetchone()[0])
            if application_id not in {0, VERBANODE_APPLICATION_ID}:
                raise BackupError("Backup database belongs to a different application")

            user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            try:
                row = conn.execute(
                    "SELECT value FROM settings WHERE key='schema_version'"
                ).fetchone()
                schema_version = int(row[0]) if row and row[0] is not None else 0
            except (sqlite3.DatabaseError, TypeError, ValueError):
                schema_version = 0

            if schema_version > CURRENT_SCHEMA_VERSION or user_version > CURRENT_SCHEMA_VERSION:
                newer = max(schema_version, user_version)
                raise BackupError(
                    f"Backup database schema {newer} is newer than this VerbaNode installation "
                    f"({CURRENT_SCHEMA_VERSION})",
                    status_code=409,
                )
            if user_version and schema_version and user_version != schema_version:
                raise BackupError("Backup database schema metadata is inconsistent")
            return max(schema_version, user_version)
    except sqlite3.DatabaseError as exc:
        raise BackupError("Backup database is not valid SQLite") from exc


def create_backup_archive(
    database_path: Path,
    output_path: Path,
    *,
    app_version: str,
    schema_version: int,
) -> dict[str, object]:
    database_path = Path(database_path)
    size_bytes = database_path.stat().st_size
    checksum = sha256_path(database_path)
    manifest: dict[str, object] = {
        "format_version": BACKUP_FORMAT_VERSION,
        "product": "VerbaNode",
        "app_version": app_version,
        "schema_version": int(schema_version),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "database": {
            "name": "verbanode.db",
            "size_bytes": size_bytes,
            "sha256": checksum,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(database_path, "verbanode.db")
        archive.writestr("backup.json", json.dumps(manifest, indent=2))
    return manifest


def validate_backup_archive(zip_path: Path, extract_dir: Path) -> ValidatedBackup:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            members = validate_archive_members(archive)
            manifest = read_manifest(archive, members)
            info, expected_size, expected_sha256 = database_member(members, manifest)
            restored = Path(extract_dir) / "restored.db"
            size_bytes, checksum = extract_member_verified(
                archive,
                info,
                restored,
                expected_sha256=expected_sha256,
            )
    except zipfile.BadZipFile as exc:
        raise BackupError("Invalid backup ZIP") from exc

    if expected_size is not None and size_bytes != expected_size:
        restored.unlink(missing_ok=True)
        raise BackupError("Backup database size does not match its manifest")

    schema_version = validate_database(restored)
    try:
        manifest_schema = int(manifest.get("schema_version", 0) or 0)
    except (TypeError, ValueError) as exc:  # guarded by read_manifest, retained defensively
        raise BackupError("Backup schema version is invalid") from exc
    if manifest_schema and schema_version and manifest_schema != schema_version:
        restored.unlink(missing_ok=True)
        raise BackupError("Backup manifest schema does not match the database")

    return ValidatedBackup(
        database_path=restored,
        manifest=manifest,
        schema_version=schema_version,
        sha256=checksum,
        size_bytes=size_bytes,
    )


def recovery_backups(backup_dir: Path) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for path in Path(backup_dir).glob("pre-*.db"):
        if not path.is_file():
            continue
        stat_result = path.stat()
        items.append(
            {
                "name": path.name,
                "size_bytes": stat_result.st_size,
                "modified_at": datetime.fromtimestamp(
                    stat_result.st_mtime, tz=timezone.utc
                ).isoformat(timespec="seconds"),
            }
        )
    items.sort(key=lambda item: str(item["modified_at"]), reverse=True)
    return items


__all__ = [
    "BACKUP_FORMAT_VERSION",
    "BackupError",
    "MAX_BACKUP_UPLOAD_BYTES",
    "ValidatedBackup",
    "create_backup_archive",
    "recovery_backups",
    "sha256_path",
    "validate_archive_members",
    "validate_backup_archive",
    "validate_database",
]
