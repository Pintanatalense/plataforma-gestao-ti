import asyncio
import os
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.future import select

from app.database import Base
from app.organization.models import Company, Unit, Sector
from app.service_desk.models import TicketCategory
from app.stock.models import StockItem
from app.assets.models import Asset
from app.identity.models import UserAccount

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@postgres:5432/gestao_ti")

engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def seed():
    async with AsyncSessionLocal() as session:
        # 1. Company
        result = await session.execute(select(Company))
        company = result.scalar_one_or_none()
        if not company:
            company = Company(name="Plataforma Gestão TI S.A.")
            session.add(company)
            await session.commit()
            print("Company created")

        # 2. Units
        result = await session.execute(select(Unit).where(Unit.name == "Matriz SP"))
        matriz = result.scalar_one_or_none()
        if not matriz:
            matriz = Unit(company_id=company.id, name="Matriz SP", code="SP-01", type="MATRIZ")
            session.add(matriz)
        
        result = await session.execute(select(Unit).where(Unit.name == "Filial RN"))
        filial = result.scalar_one_or_none()
        if not filial:
            filial = Unit(company_id=company.id, name="Filial RN", code="RN-01", type="FILIAL")
            session.add(filial)
            
        await session.commit()
        print("Units created/verified")

        # 3. Sectors (for Matriz SP)
        sectors_to_create = ["TI", "Financeiro", "Administrativo"]
        ti_sector = None
        for sec_name in sectors_to_create:
            result = await session.execute(select(Sector).where(Sector.name == sec_name, Sector.unit_id == matriz.id))
            sec = result.scalar_one_or_none()
            if not sec:
                sec = Sector(unit_id=matriz.id, name=sec_name, code=sec_name.upper())
                session.add(sec)
                await session.commit()
            
            if sec_name == "TI":
                ti_sector = sec

        print("Sectors created/verified")

        # 4. Ticket Categories
        categories = [
            {"name": "Suporte a Equipamentos", "desc": "Problemas físicos com notebook, desktop, monitor, etc."},
            {"name": "Acessos e Senhas", "desc": "Reset de senha, bloqueios de conta, novo acesso a sistema."},
            {"name": "Rede e Internet", "desc": "Lentidão, sem acesso a internet ou sistemas internos."}
        ]

        if ti_sector:
            for cat_data in categories:
                result = await session.execute(select(TicketCategory).where(TicketCategory.name == cat_data["name"]))
                cat = result.scalar_one_or_none()
                if not cat:
                    cat = TicketCategory(
                        name=cat_data["name"],
                        description=cat_data["desc"],
                        default_sector_id=ti_sector.id
                    )
                    session.add(cat)
            
            await session.commit()
            print("Categories created/verified")
        else:
            print("TI sector not found")

if __name__ == "__main__":
    asyncio.run(seed())
