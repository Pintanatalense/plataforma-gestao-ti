"""Backup completo (Plano de Evolução, Fase 0 PR 13; S10): anexos e logomarca ao lado do dump."""

import asyncio
import os
import tarfile

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.backup.models import DatabaseBackup
from app.backup.services import BackupService
from app.config import get_settings
from tests.conftest import make_auth_headers
from tests.factories import make_user

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def fake_pg_dump(monkeypatch):
    async def _fake(self):
        return True, b"-- dump de teste\nSELECT 1;\n"

    monkeypatch.setattr(BackupService, "_execute_database_dump", _fake)


@pytest.fixture
def volumes(tmp_path, monkeypatch):
    settings = get_settings()
    attachments, static, backups = tmp_path / "attachments", tmp_path / "static", tmp_path / "backups"
    for d in (attachments, static, backups):
        d.mkdir()
    (attachments / "2026" / "10").mkdir(parents=True)
    (attachments / "2026" / "10" / "laudo.pdf").write_bytes(b"%PDF-1.4 laudo")
    (static / "logo.png").write_bytes(b"\x89PNG logo")
    if os.name == "posix":  # link simbólico apontando para fora do volume não entra no pacote
        (attachments / "senhas").symlink_to("/etc/passwd")
    monkeypatch.setattr(settings, "ATTACHMENT_STORAGE_PATH", str(attachments))
    monkeypatch.setattr(settings, "STATIC_DIR", str(static))
    monkeypatch.setattr(settings, "BACKUP_STORAGE_PATH", str(backups))
    return backups


async def test_backup_packs_attachments_and_logo_in_the_restore_format(db_session: AsyncSession, volumes):
    backup = await BackupService(db_session).create_backup()
    assert backup.files_filename.startswith("arquivos_gestao_ti_") and backup.files_count == 2
    archive = volumes / backup.files_filename
    with tarfile.open(archive, "r:gz") as tar:
        names = set(tar.getnames())
        assert "data/attachments/2026/10/laudo.pdf" in names and "app/static/logo.png" in names
        assert "data/attachments/senhas" not in names
        assert all(n.split("/")[0] in ("data", "app") for n in names)  # o restore-backup.sh só aceita esses
    result = await BackupService(db_session).validate_backup_integrity(backup.id)
    assert result["is_valid"] and result["files_valid"]

    archive.write_bytes(archive.read_bytes() + b"x")  # pacote adulterado
    result = await BackupService(db_session).validate_backup_integrity(backup.id)
    assert result["is_valid"] is False and result["files_valid"] is False


async def test_only_the_most_recent_backups_keep_the_files_archive(db_session: AsyncSession, volumes, monkeypatch):
    monkeypatch.setattr(get_settings(), "BACKUP_FILES_MAX_KEEP", 1)
    first = await BackupService(db_session).create_backup()
    first_archive = first.files_filename
    await asyncio.sleep(1.1)  # o nome do arquivo tem precisão de segundos
    second = await BackupService(db_session).create_backup()
    await db_session.refresh(first)
    assert first.files_filename is None and not (volumes / first_archive).exists()
    assert (volumes / first.filename).exists()  # o banco continua
    assert second.files_filename and (volumes / second.files_filename).exists()

    await BackupService(db_session).delete_backup(second.id)
    assert not (volumes / second.filename).exists() and not (volumes / str(second.files_filename or "x")).exists()


async def test_download_files_requires_permission_and_returns_the_archive(client: AsyncClient, db_session: AsyncSession, volumes):
    backup = await BackupService(db_session).create_backup()
    uid = str((await make_user(db_session)).id)
    url = f"/api/v1/system/backups/{backup.id}/download-files"
    assert (await client.get(url, headers=make_auth_headers(uid, permissions=["system.backup.manage"]))).status_code == 403
    resp = await client.get(url, headers=make_auth_headers(uid, permissions=["system.backup.download"]))
    assert resp.status_code == 200 and resp.headers["x-checksum-sha256"] == backup.files_checksum_sha256
    listed = (await client.get("/api/v1/system/backups", headers=make_auth_headers(uid, permissions=["system.backup.manage"]))).json()
    assert listed[0]["files_count"] == 2


async def test_files_can_be_turned_off(db_session: AsyncSession, volumes, monkeypatch):
    monkeypatch.setattr(get_settings(), "BACKUP_INCLUDE_FILES", False)
    backup = await BackupService(db_session).create_backup()
    assert backup.files_filename is None
    assert await db_session.get(DatabaseBackup, backup.id)
