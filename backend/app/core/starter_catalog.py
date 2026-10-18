"""
Catálogo inicial mínimo, criado na configuração inicial (modo limpo ou demonstração).

Sem ele a instalação "limpa" não abre um único chamado: toda categoria de chamado precisa apontar para um
setor responsável, e nenhum setor nem categoria existia. Tudo aqui é editável pela tela e NÃO é marcado
como demonstração (a limpeza de dados de exemplo não o remove). Idempotente: o que já existe é preservado.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import AssetCategory
from app.organization.models import Company, Sector, Unit
from app.service_desk.models import TicketCategory

TI_SECTOR_CODE = "TI-00"
TI_SECTOR_NAME = "Tecnologia da Informação"

TICKET_CATEGORIES: list[tuple[str, str]] = [
    ("Hardware e equipamentos", "Computador, monitor, periféricos e outros equipamentos."),
    ("Software e sistemas", "Instalação, erro ou dúvida em programas e sistemas."),
    ("Rede e internet", "Sem conexão, lentidão, Wi-Fi e acesso a servidores."),
    ("Acessos e contas", "Criação, bloqueio e redefinição de senha ou permissões."),
    ("Impressão", "Impressoras, toner e filas de impressão."),
    ("Outros", "Solicitações que não se encaixam nas demais categorias."),
]

ASSET_CATEGORIES: list[tuple[str, str]] = [
    ("Computadores", "Desktops, notebooks e all-in-one."),
    ("Monitores", "Monitores e telas."),
    ("Impressoras", "Impressoras e multifuncionais."),
    ("Rede", "Switches, roteadores, access points e firewalls."),
    ("Celulares e tablets", "Smartphones e tablets corporativos."),
]


async def seed_starter_catalog(session: AsyncSession) -> dict[str, int]:
    """Cria o setor de TI, categorias de chamado e de ativo que faltarem (sem commit)."""
    created = {"sectors": 0, "ticket_categories": 0, "asset_categories": 0}

    sector = (await session.execute(select(Sector).where(Sector.code == TI_SECTOR_CODE))).scalar_one_or_none()
    if sector is None:
        unit = (await session.execute(select(Unit).order_by(Unit.created_at).limit(1))).scalars().first()
        if unit is None:
            company = (await session.execute(select(Company).order_by(Company.created_at).limit(1))).scalars().first()
            if company is None:  # base totalmente vazia (seed não executado): não inventa empresa
                return created
            unit = Unit(company_id=company.id, name="Matriz", code="MAT-01", type="MATRIZ")
            session.add(unit)
            await session.flush()
        sector = Sector(unit_id=unit.id, name=TI_SECTOR_NAME, code=TI_SECTOR_CODE, is_demo=False)
        session.add(sector)
        await session.flush()
        created["sectors"] = 1

    existing_ticket = set((await session.execute(select(TicketCategory.name))).scalars())
    for name, description in TICKET_CATEGORIES:
        if name not in existing_ticket:
            session.add(TicketCategory(name=name, description=description, is_active=True, default_sector_id=sector.id))
            created["ticket_categories"] += 1

    existing_asset = set((await session.execute(select(AssetCategory.name))).scalars())
    for name, description in ASSET_CATEGORIES:
        if name not in existing_asset:
            session.add(AssetCategory(name=name, description=description, spec_schema={}))
            created["asset_categories"] += 1

    await session.flush()
    return created
