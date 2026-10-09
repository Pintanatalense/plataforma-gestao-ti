"""
Script de seed para a Plataforma de Gestão de TI.
Cria a empresa padrão, permissões e o perfil de administrador.

O primeiro usuário administrador NÃO é criado aqui: ele é definido por quem
instala o sistema, na tela de configuração inicial (primeiro acesso).
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
import app.main  # Import all modules to avoid SQLAlchemy mapper errors
from app.identity.models import Permission, Role
from app.organization.models import Company, Unit


# Import all models to ensure SQLAlchemy registers them before creating relationships
import app.stock.models
import app.assets.models
import app.movements.models
import app.service_desk.models


async def seed() -> None:
    print("Iniciando seed...")
    async with AsyncSessionLocal() as session:
        # 1. Criar Empresa
        stmt = select(Company).where(Company.name == "Empresa Padrão")
        result = await session.execute(stmt)
        company = result.scalar_one_or_none()
        
        if not company:
            company = Company(name="Empresa Padrão", cnpj="00.000.000/0001-00")
            session.add(company)
            await session.flush()
            print(f"Empresa '{company.name}' criada.")
        else:
            print(f"Empresa '{company.name}' já existe.")

        # 2. Criar Unidade Matriz
        stmt = select(Unit).where(Unit.company_id == company.id, Unit.type == "MATRIZ")
        result = await session.execute(stmt)
        matriz = result.scalar_one_or_none()
        
        if not matriz:
            matriz = Unit(company_id=company.id, name="Matriz", code="MAT-01", type="MATRIZ")
            session.add(matriz)
            await session.flush()
            print(f"Unidade '{matriz.name}' criada.")

        # 3. Criar Permissões Iniciais
        permissions_data = [
            # Organization
            {"code": "organization.company.read", "description": "Ler dados da empresa"},
            {"code": "organization.company.create", "description": "Inicializar a empresa"},
            {"code": "organization.company.update", "description": "Editar dados da empresa"},
            {"code": "organization.units.read", "description": "Ler unidades"},
            {"code": "organization.units.create", "description": "Criar unidades"},
            {"code": "organization.units.update", "description": "Editar unidades"},
            {"code": "organization.sectors.read", "description": "Ler setores"},
            {"code": "organization.sectors.create", "description": "Criar setores"},
            {"code": "organization.sectors.update", "description": "Editar setores"},
            {"code": "organization.employees.read", "description": "Ler colaboradores"},
            {"code": "organization.employees.create", "description": "Criar colaboradores"},
            {"code": "organization.employees.update", "description": "Editar colaboradores"},
            
            # Identity
            {"code": "identity.users.read", "description": "Ler usuários"},
            {"code": "identity.users.create", "description": "Criar usuários"},
            {"code": "identity.users.update", "description": "Editar usuários"},
            {"code": "identity.roles.read", "description": "Ler perfis"},
            {"code": "identity.roles.create", "description": "Criar perfis"},
            {"code": "identity.roles.update", "description": "Editar perfis"},
        ]
        
        for p_data in permissions_data:
            stmt = select(Permission).where(Permission.code == p_data["code"])
            result = await session.execute(stmt)
            if not result.scalar_one_or_none():
                permission = Permission(**p_data)
                session.add(permission)
        await session.flush()
        print("Permissões sincronizadas.")

        # 4. Criar Admin Role (e mantê-lo com todas as permissões a cada execução)
        stmt_all_perms = select(Permission)
        all_perms = list((await session.execute(stmt_all_perms)).scalars().all())

        stmt = select(Role).options(selectinload(Role.permissions)).where(Role.name == "Administrador")
        result = await session.execute(stmt)
        admin_role = result.scalar_one_or_none()
        
        if not admin_role:
            admin_role = Role(name="Administrador", description="Acesso total ao sistema.")
            admin_role.permissions = all_perms
            session.add(admin_role)
            await session.flush()
            print(f"Perfil '{admin_role.name}' criado com {len(all_perms)} permissões.")
        else:
            admin_role.permissions = all_perms
            await session.flush()
            print(f"Perfil '{admin_role.name}' sincronizado com {len(all_perms)} permissões.")

        # 5. Usuário administrador: criado no primeiro acesso (tela de setup).
        print("Primeiro administrador: acesse o sistema para concluir a configuração inicial.")

        await session.commit()
        print("Seed finalizado com sucesso!")


if __name__ == "__main__":
    asyncio.run(seed())
