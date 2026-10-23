"""Modelo editável do Termo de Responsabilidade: padrão preservado, edição segura e dados do ativo preenchidos."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.statement_template import (
    DEFAULT_TEMPLATE,
    StatementData,
    render_body,
    unknown_fields,
    validate_template,
)
from app.audit.models import AuditLog
from tests.factories import headers_for, make_asset, make_asset_category, make_employee, make_org, make_user

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/assets/statement-template"


def sample() -> StatementData:
    return StatementData(
        colaborador="Maria", matricula="123", cargo="Analista", setor="Financeiro", unidade="Matriz",
        patrimonio="PAT-1", categoria="Notebook", equipamento="Dell", empresa="Acme", data="23/10/2026",
        asset_id="id-1", specs={"ram": "16 GB"},
    )


# --- renderização (funções puras) ---------------------------------------------------------------------------

def test_default_template_keeps_the_original_sections_and_fills_the_asset_data():
    html = render_body(DEFAULT_TEMPLATE, sample())
    for text in (
        "Termo de Responsabilidade e Cautela de Equipamento de TI",
        "1. Dados do Colaborador (Responsável)",
        "2. Identificação do Equipamento (Patrimônio)",
        "3. Especificações Técnicas",
        "4. Declaração e Termos de Uso",
        "Maria", "123", "Financeiro", "Matriz", "PAT-1", "Notebook", "Dell", "RAM", "16 GB",
        "Colaborador Responsável", "Responsável de TI",
    ):
        assert text in html, text
    assert "<ol>" in html and html.count("<li>") == 6


def test_custom_text_uses_inline_fields_and_basic_markup():
    template = "# Termo da {{empresa}}\n> Setor {{setor}}\n\nEu, **{{colaborador}}**, recebi {{equipamento}} ({{patrimonio}}).\n- item um\n- item dois"
    html = render_body(template, sample())
    assert "<h1>Termo da Acme</h1>" in html
    assert 'class="subtitle">Setor Financeiro' in html
    assert "Eu, <strong>Maria</strong>, recebi Dell (PAT-1)." in html
    assert "<ul>" in html and html.count("<li>") == 2


def test_nothing_the_user_writes_becomes_html():
    template = "# <script>alert(1)</script>\n<img src=x onerror=alert(2)>\n{{colaborador}}"
    data = sample()
    data.colaborador = "<b>x</b>"
    html = render_body(template, data)
    assert "<script>" not in html and "<img" not in html and "<b>x</b>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


def test_unknown_fields_are_reported_and_left_visible():
    assert unknown_fields("oi {{colaborador}} {{matricula_errada}} {{x}}") == ["matricula_errada", "x"]
    assert "{{matricula_errada}}" in render_body("{{matricula_errada}}", sample())


def test_block_placeholder_only_counts_when_alone_on_the_line():
    html = render_body("antes {{assinaturas}} depois", sample())
    assert "sig-block" not in html and "{{assinaturas}}" in html


def test_validation_rejects_empty_and_huge_templates():
    with pytest.raises(ValueError):
        validate_template("  \n ")
    with pytest.raises(ValueError):
        validate_template("a" * 20001)
    assert validate_template("a\r\nb") == "a\nb"


# --- API ----------------------------------------------------------------------------------------------------

async def _manager(db: AsyncSession):
    user = await make_user(db)
    return user, headers_for(user, "organization.company.update", "assets.read")


async def test_default_is_served_until_a_company_template_is_saved(client: AsyncClient, db_session: AsyncSession):
    _, headers = await _manager(db_session)
    resp = await client.get(BASE, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_default"] is True and body["template"] == DEFAULT_TEMPLATE
    assert "colaborador" in body["fields"] and "assinaturas" in body["blocks"]


async def test_saved_template_is_used_by_the_statement_and_can_be_restored(client: AsyncClient, db_session: AsyncSession):
    user, headers = await _manager(db_session)
    org = await make_org(db_session)
    cat = await make_asset_category(db_session)
    emp = await make_employee(db_session, org)
    asset = await make_asset(db_session, org, cat, status="IN_USE", employee=emp)
    stmt = f"/api/v1/assets/{asset.id}/responsibility-statement"

    saved = await client.put(BASE, json={"template": "# Modelo da Acme\nRecebi {{patrimonio}} de {{colaborador}}."}, headers=headers)
    assert saved.status_code == 200 and saved.json()["is_default"] is False

    page = await client.get(stmt, headers=headers)
    assert "Modelo da Acme" in page.text
    assert f"Recebi {asset.tag} de {emp.name}." in page.text
    assert "Declaração e Termos de Uso" not in page.text

    restored = await client.delete(BASE, headers=headers)
    assert restored.status_code == 200 and restored.json()["is_default"] is True
    again = await client.get(stmt, headers=headers)
    assert "Declaração e Termos de Uso" in again.text

    events = (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "assets.statement_template_changed"))).scalars().all()
    assert len(events) == 2 and all(e.user_id == user.id for e in events)
    assert "Modelo da Acme" not in str([e.data for e in events])  # o texto do modelo não vai para a trilha


async def test_preview_does_not_save_anything(client: AsyncClient, db_session: AsyncSession):
    _, headers = await _manager(db_session)
    resp = await client.post(f"{BASE}/preview", json={"template": "# Prévia\n{{colaborador}} / {{patrimonio}}"}, headers=headers)
    assert resp.status_code == 200
    assert "Maria da Silva / PAT-0001" in resp.text
    assert (await client.get(BASE, headers=headers)).json()["is_default"] is True


async def test_empty_template_is_refused(client: AsyncClient, db_session: AsyncSession):
    _, headers = await _manager(db_session)
    resp = await client.put(BASE, json={"template": "   "}, headers=headers)
    assert resp.status_code in (400, 422)
    assert (await client.get(BASE, headers=headers)).json()["is_default"] is True


async def test_editing_needs_the_company_permission(client: AsyncClient, db_session: AsyncSession):
    user = await make_user(db_session)
    reader = headers_for(user, "assets.read", "assets.write")
    assert (await client.get(BASE, headers=reader)).status_code == 200
    assert (await client.put(BASE, json={"template": "x"}, headers=reader)).status_code == 403
    assert (await client.delete(BASE, headers=reader)).status_code == 403
    assert (await client.post(f"{BASE}/preview", json={"template": "x"}, headers=reader)).status_code == 403


async def test_own_asset_statement_works_with_read_own_and_the_custom_template(client: AsyncClient, db_session: AsyncSession):
    org = await make_org(db_session)
    cat = await make_asset_category(db_session)
    me = await make_employee(db_session, org)
    other = await make_employee(db_session, org)
    mine = await make_asset(db_session, org, cat, status="IN_USE", employee=me)
    theirs = await make_asset(db_session, org, cat, status="IN_USE", employee=other)
    user = await make_user(db_session, me)
    manager = await make_user(db_session)
    saved = await client.put(
        BASE, json={"template": "# Termo próprio de {{colaborador}}"}, headers=headers_for(manager, "organization.company.update")
    )
    assert saved.status_code == 200
    headers = headers_for(user, "assets.read_own")

    ok = await client.get(f"/api/v1/assets/{mine.id}/responsibility-statement", headers=headers)
    assert ok.status_code == 200 and f"Termo próprio de {me.name}" in ok.text

    denied = await client.get(f"/api/v1/assets/{theirs.id}/responsibility-statement", headers=headers)
    assert denied.status_code == 403


async def test_template_limit_is_enforced_by_the_api(client: AsyncClient, db_session: AsyncSession):
    _, headers = await _manager(db_session)
    too_big = {"template": "a" * 20001}
    assert (await client.put(BASE, json=too_big, headers=headers)).status_code in (400, 422)
    assert (await client.post(f"{BASE}/preview", json=too_big, headers=headers)).status_code in (400, 422)
