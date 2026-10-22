"""
Testes automatizados para MOD-14 — Backups do Banco de Dados
"""

import pytest
import uuid
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.organization.models import Company, Unit, Sector, Employee
from app.identity.models import UserAccount, Role, Permission
from tests.conftest import make_auth_headers

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def fake_pg_dump(monkeypatch):
    """O dump real exige pg_dump + PostgreSQL; aqui isolamos o serviço da infraestrutura."""
    from app.backup.services import BackupService

    async def _fake(self):
        return True, b"-- dump de teste\nSELECT 1;\n"

    monkeypatch.setattr(BackupService, "_execute_database_dump", _fake)


async def setup_backup_fixtures(db_session: AsyncSession):
    company = Company(name="Backup Corp", cnpj="33.444.555/0001-66")
    db_session.add(company)
    await db_session.flush()

    unit = Unit(company_id=company.id, name="Datacenter", code="DC-01", type="MATRIZ")
    db_session.add(unit)
    await db_session.flush()

    sector = Sector(unit_id=unit.id, name="Operações", code="OPS-01")
    db_session.add(sector)
    await db_session.flush()

    emp_admin = Employee(unit_id=unit.id, sector_id=sector.id, name="SysAdmin", registration_number="SA-001")
    emp_regular = Employee(unit_id=unit.id, sector_id=sector.id, name="User Normal", registration_number="UN-002")
    db_session.add_all([emp_admin, emp_regular])
    await db_session.flush()

    perm_manage = Permission(code="system.backup.manage", description="Gerenciar Backups")
    perm_download = Permission(code="system.backup.download", description="Baixar Backups")
    db_session.add_all([perm_manage, perm_download])
    await db_session.flush()

    role_admin = Role(name="BackupAdminRole", description="Admin de Backups")
    role_admin.permissions = [perm_manage, perm_download]
    db_session.add(role_admin)
    await db_session.flush()

    user_admin = UserAccount(email="backup_admin@ti.com", hashed_password=hash_password("123"), employee_id=emp_admin.id)
    user_admin.roles = [role_admin]

    user_regular = UserAccount(email="regular_user@ti.com", hashed_password=hash_password("123"), employee_id=emp_regular.id)
    db_session.add_all([user_admin, user_regular])
    await db_session.commit()

    return {
        "admin_headers": make_auth_headers(str(user_admin.id), is_admin=False, permissions=["system.backup.manage", "system.backup.download"]),
        "regular_headers": make_auth_headers(str(user_regular.id), is_admin=False, permissions=[]),
        "user_admin": user_admin,
    }


async def test_generate_and_list_backup(client: AsyncClient, db_session: AsyncSession):
    """Testa geração de backup completo com integridade SHA-256 e listagem."""
    fixtures = await setup_backup_fixtures(db_session)
    headers = fixtures["admin_headers"]

    # 1. Gera backup
    gen_resp = await client.post("/api/v1/system/backups/generate", headers=headers)
    assert gen_resp.status_code == 201, gen_resp.text
    b_data = gen_resp.json()
    assert b_data["status"] == "SUCCESS"
    assert b_data["filename"].endswith(".sql.gz")
    assert b_data["size_bytes"] > 0
    assert len(b_data["checksum_sha256"]) == 64
    backup_id = b_data["id"]

    # 2. Lista histórico
    list_resp = await client.get("/api/v1/system/backups", headers=headers)
    assert list_resp.status_code == 200
    backups = list_resp.json()
    assert len(backups) >= 1
    found = next((b for b in backups if b["id"] == backup_id), None)
    assert found is not None
    assert found["checksum_sha256"] == b_data["checksum_sha256"]


async def test_download_and_delete_backup(client: AsyncClient, db_session: AsyncSession):
    """Testa download autenticado com hash no header e exclusão de arquivo."""
    fixtures = await setup_backup_fixtures(db_session)
    headers = fixtures["admin_headers"]

    # 1. Gera backup
    gen_resp = await client.post("/api/v1/system/backups/generate", headers=headers)
    assert gen_resp.status_code == 201
    backup_id = gen_resp.json()["id"]
    checksum = gen_resp.json()["checksum_sha256"]

    # 2. Download do arquivo
    dl_resp = await client.get(f"/api/v1/system/backups/{backup_id}/download", headers=headers)
    assert dl_resp.status_code == 200
    assert dl_resp.headers["content-type"] == "application/gzip"
    assert dl_resp.headers["x-checksum-sha256"] == checksum
    assert len(dl_resp.content) > 0

    # 3. Exclui o backup
    del_resp = await client.delete(f"/api/v1/system/backups/{backup_id}", headers=headers)
    assert del_resp.status_code == 200

    # 4. Tenta baixar novamente -> 404
    dl_after = await client.get(f"/api/v1/system/backups/{backup_id}/download", headers=headers)
    assert dl_after.status_code == 404


async def test_backup_permissions_isolation(client: AsyncClient, db_session: AsyncSession):
    """Testa que usuários sem permissão não conseguem gerar ou baixar backups."""
    fixtures = await setup_backup_fixtures(db_session)
    reg_headers = fixtures["regular_headers"]

    # Bloqueio de geração
    gen_resp = await client.post("/api/v1/system/backups/generate", headers=reg_headers)
    assert gen_resp.status_code == 403

    # Bloqueio de listagem
    list_resp = await client.get("/api/v1/system/backups", headers=reg_headers)
    assert list_resp.status_code == 403

    # Bloqueio de download
    fake_id = str(uuid.uuid4())
    dl_resp = await client.get(f"/api/v1/system/backups/{fake_id}/download", headers=reg_headers)
    assert dl_resp.status_code == 403
