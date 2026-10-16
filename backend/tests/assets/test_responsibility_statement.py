import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import headers_for, make_asset, make_asset_category, make_employee, make_org, make_user

pytestmark = pytest.mark.asyncio


async def test_statement_escapes_user_controlled_values(client: AsyncClient, db_session: AsyncSession):
    org = await make_org(db_session)
    cat = await make_asset_category(db_session)
    emp = await make_employee(db_session, org)
    emp.name = "<img src=x onerror=alert(3)>Fulano"
    asset = await make_asset(db_session, org, cat, status="IN_USE", employee=emp)
    asset.name = "<script>alert(1)</script>Dell"
    asset.technical_specs = {"<b>chave</b>": "<img src=x onerror=alert(2)>"}
    await db_session.commit()
    admin = await make_user(db_session, is_admin=True)

    resp = await client.get(f"/api/v1/assets/{asset.id}/responsibility-statement", headers=headers_for(admin))

    assert resp.status_code == 200
    body = resp.text
    assert "<script>alert(1)</script>" not in body
    assert "<img src=x" not in body.lower()
    assert "&lt;script&gt;alert(1)&lt;/script&gt;Dell" in body
    assert "&lt;img src=x onerror=alert(3)&gt;Fulano" in body
