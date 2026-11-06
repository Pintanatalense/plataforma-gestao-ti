"""
Testes automatizados para MOD-13 — Data Transfer (CSV Import & Export)
"""

import pytest
import io
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.security import hash_password
from app.organization.models import Company, Unit, Sector, Employee
from app.identity.models import UserAccount, Role, Permission
from app.service_desk.models import Ticket, TicketCategory
from tests.conftest import make_auth_headers

pytestmark = pytest.mark.asyncio


async def setup_data_transfer_fixtures(db_session: AsyncSession):
    company = Company(name="Data Transfer Corp", cnpj="11.222.333/0001-44")
    db_session.add(company)
    await db_session.flush()

    unit = Unit(company_id=company.id, name="Matriz SP", code="SP-01", type="MATRIZ")
    db_session.add(unit)
    await db_session.flush()

    sector = Sector(unit_id=unit.id, name="Suporte", code="SUP-01")
    db_session.add(sector)
    await db_session.flush()

    emp = Employee(unit_id=unit.id, sector_id=sector.id, name="João Silva", registration_number="JS-001")
    db_session.add(emp)
    await db_session.flush()

    # Permissões
    perm_export = Permission(code="system.data.export", description="Exportar")
    perm_import = Permission(code="system.data.import", description="Importar")
    db_session.add_all([perm_export, perm_import])
    await db_session.flush()

    role_admin = Role(name="DataAdmin", description="Admin de Dados")
    role_admin.permissions = [perm_export, perm_import]
    db_session.add(role_admin)
    await db_session.flush()

    emp2 = Employee(unit_id=unit.id, sector_id=sector.id, name="Maria Souza", registration_number="MS-002")
    db_session.add(emp2)
    await db_session.flush()

    user_admin = UserAccount(email="data_admin@empresa.com", hashed_password=hash_password("123"), employee_id=emp.id)
    user_admin.roles = [role_admin]

    user_regular = UserAccount(email="regular@empresa.com", hashed_password=hash_password("123"), employee_id=emp2.id)
    db_session.add_all([user_admin, user_regular])
    await db_session.flush()

    cat = TicketCategory(name="Redes & Infra", description="Problemas de rede", default_sector_id=sector.id)
    db_session.add(cat)
    await db_session.flush()

    # Ticket com tentativa de CSV injection na descrição e título
    t1 = Ticket(
        title="=SUM(A1:A10)",
        description="+cmd|' /C calc'!A0",
        priority="HIGH",
        status="OPENED",
        requester_id=emp.id,
        created_by_user_id=user_admin.id,
        origin_unit_id=unit.id,
        origin_sector_id=sector.id,
        responsible_sector_id=sector.id,
        category_id=cat.id
    )
    db_session.add(t1)
    await db_session.commit()

    return {
        "admin_headers": make_auth_headers(str(user_admin.id), is_admin=False, permissions=["system.data.export", "system.data.import"]),
        "regular_headers": make_auth_headers(str(user_regular.id), is_admin=False, permissions=[]),
        "unit": unit,
        "sector": sector,
    }


async def test_export_csv_tickets_and_injection_defense(client: AsyncClient, db_session: AsyncSession):
    """Testa exportação de chamados, UTF-8 BOM e sanitização de fórmulas perigosas."""
    fixtures = await setup_data_transfer_fixtures(db_session)
    headers = fixtures["admin_headers"]

    payload = {
        "entity": "tickets",
        "delimiter": ";"
    }
    resp = await client.post("/api/v1/system/export", json=payload, headers=headers)
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "attachment; filename=\"export_tickets.csv\"" in resp.headers["content-disposition"]

    content = resp.content
    # Verifica presença do UTF-8 BOM
    assert content.startswith(b"\xef\xbb\xbf")

    text = content.decode("utf-8")
    assert "ID;Título;Descrição;Prioridade;Status" in text
    # Verifica que as células perigosas foram sanitizadas com apóstrofo
    assert "'=SUM(A1:A10)" in text
    assert "'+cmd|' /C calc'!A0" in text


async def test_export_requires_permission(client: AsyncClient, db_session: AsyncSession):
    """Testa que exportação é bloqueada para usuários sem a permissão system.data.export."""
    fixtures = await setup_data_transfer_fixtures(db_session)
    reg_headers = fixtures["regular_headers"]

    resp = await client.post("/api/v1/system/export", json={"entity": "tickets"}, headers=reg_headers)
    assert resp.status_code == 403


async def test_import_analyze_csv(client: AsyncClient, db_session: AsyncSession):
    """Testa o endpoint de análise inicial do Wizard de importação CSV."""
    fixtures = await setup_data_transfer_fixtures(db_session)
    headers = fixtures["admin_headers"]

    csv_data = "Nome;Descricao\nSuporte N1;Atendimento inicial\nSistemas;Manutenção de ERP"
    files = {"file": ("categorias.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}

    resp = await client.post("/api/v1/system/import/analyze", files=files, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"] == "categorias.csv"
    assert data["detected_delimiter"] == ";"
    assert "Nome" in data["headers"]
    assert "Descricao" in data["headers"]
    assert len(data["preview_rows"]) == 2
    assert data["preview_rows"][0]["Nome"] == "Suporte N1"


async def test_import_execute_categories_and_duplicate_handling(client: AsyncClient, db_session: AsyncSession):
    """Testa a execução de importação de categorias com tratamento de duplicidades."""
    fixtures = await setup_data_transfer_fixtures(db_session)
    headers = fixtures["admin_headers"]

    csv_data = (
        "Categoria;Detalhes\n"
        "Segurança da Informação;Políticas e Acessos\n"
        "Impressoras & Scanners;Manutenção de periféricos de impressão\n"
    )
    files = {"file": ("novas_categorias.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    form_data = {
        "entity": "categories",
        "mapping": '{"name": "Categoria", "description": "Detalhes"}',
        "delimiter": ";"
    }

    # 1. Primeira importação -> Sucesso
    resp = await client.post("/api/v1/system/import/execute", files=files, data=form_data, headers=headers)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["success_count"] == 2
    assert res_data["error_count"] == 0

    # Verifica no banco
    stmt = select(TicketCategory).where(TicketCategory.name == "Segurança da Informação")
    cat_db = (await db_session.execute(stmt)).scalar_one_or_none()
    assert cat_db is not None
    assert cat_db.description == "Políticas e Acessos"

    # 2. Re-importar o mesmo CSV -> Deve identificar duplicidades e rejeitar linhas sem quebrar
    files2 = {"file": ("novas_categorias.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    resp_dup = await client.post("/api/v1/system/import/execute", files=files2, data=form_data, headers=headers)
    assert resp_dup.status_code == 200
    res_dup = resp_dup.json()
    assert res_dup["success_count"] == 0
    assert res_dup["error_count"] == 2
    assert len(res_dup["rejected_lines"]) == 2
    assert "já existe" in res_dup["rejected_lines"][0]["error_message"]
