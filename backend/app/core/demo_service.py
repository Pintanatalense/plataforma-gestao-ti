"""
MOD-01 — Gestão de Ambientes e Demonstração (Services)

Gerenciamento seguro de ciclo de vida de dados demonstrativos:
- Rastreamento Demo vs Produção (system_mode, is_demo)
- Preview e validação de requisitos de segurança (backup recente obrigatório)
- Limpeza seletiva transacional preservando administradores, configurações e auditoria
- Carga idempotente de dados modelo
"""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetCategory, AssetStatus
from app.attachments.models import Attachment
from app.audit.models import AuditLog
from app.backup.models import DatabaseBackup
from app.backup.services import BackupService
from app.config import get_settings
from app.core.exceptions import BusinessRuleException, ForbiddenException
from app.core.security import hash_password
from app.core.settings_model import SystemSetting
from app.identity.models import Permission, Role, UserAccount, user_role_association
from app.movements.models import AssetMovement, MovementType
from app.organization.models import Company, Employee, Sector, Unit
from app.service_desk.models import (
    Ticket,
    TicketCategory,
    TicketInteraction,
    TicketMaterial,
    ticket_assets,
)
from app.stock.models import StockCategory, StockItem, StockMovement

logger = logging.getLogger(__name__)
settings = get_settings()

REQUIRED_CONFIRMATION_PHRASE = "LIMPAR DADOS DE DEMONSTRACAO"


class DemoManagementService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.backup_service = BackupService(session)

    async def get_system_mode(self) -> str:
        stmt = select(SystemSetting).where(SystemSetting.key == "system_mode")
        res = (await self.session.execute(stmt)).scalar_one_or_none()
        return res.value if res and res.value else "PRODUCTION"

    async def set_system_mode(self, mode: str) -> None:
        stmt = select(SystemSetting).where(SystemSetting.key == "system_mode")
        setting = (await self.session.execute(stmt)).scalar_one_or_none()
        if not setting:
            setting = SystemSetting(key="system_mode", value=mode)
            self.session.add(setting)
        else:
            setting.value = mode
        await self.session.flush()

    async def get_demo_status(self) -> dict:
        mode = await self.get_system_mode()

        counts = {}
        for name, model in [
            ("companies", Company),
            ("units", Unit),
            ("sectors", Sector),
            ("employees", Employee),
            ("users", UserAccount),
            ("assets", Asset),
            ("stock_items", StockItem),
            ("tickets", Ticket),
            ("attachments", Attachment),
        ]:
            stmt = select(func.count()).select_from(model).where(model.is_demo == True)
            counts[name] = (await self.session.execute(stmt)).scalar() or 0

        has_backup, recent_backup = await self.backup_service.get_recent_valid_backup(max_age_hours=24)

        return {
            "system_mode": mode,
            "is_demo_mode": (mode == "DEMO" or any(v > 0 for v in counts.values())),
            "demo_records_count": counts,
            "total_demo_records": sum(counts.values()),
            "has_recent_valid_backup": has_backup,
            "latest_backup": {
                "id": str(recent_backup.id),
                "filename": recent_backup.filename,
                "created_at": recent_backup.created_at.isoformat() if recent_backup.created_at else None,
                "size_bytes": recent_backup.size_bytes,
            } if recent_backup else None,
        }

    async def get_preview_clean(self) -> dict:
        status_info = await self.get_demo_status()

        return {
            "demo_records": status_info["demo_records_count"],
            "total_to_remove": status_info["total_demo_records"],
            "has_valid_backup": status_info["has_recent_valid_backup"],
            "latest_backup": status_info["latest_backup"],
            "required_confirmation_phrase": REQUIRED_CONFIRMATION_PHRASE,
            "preserved_elements": [
                "Usuários administradores reais e credenciais ativas",
                "Perfis de acesso RBAC e permissões granulares do sistema",
                "Configurações e templates de mensageria WhatsApp",
                "Parâmetros de envio de e-mail SMTP",
                "Trilha histórica e logs de auditoria (AuditLog)",
                "Histórico e arquivos físicos de backup do banco de dados",
                "Arquivos anexos corporativos reais (não-demonstrativos)",
            ],
            "security_conditions": {
                "admin_permission_required": True,
                "backup_required": True,
                "confirmation_phrase_required": True,
                "atomic_transaction": True,
            }
        }

    async def clean_demo_data(
        self,
        admin_user_id: uuid.UUID,
        confirmation_phrase: str,
        ip_address: str = "127.0.0.1"
    ) -> dict:
        """Executa a limpeza cirúrgica de todos os dados marcados com is_demo == True."""
        clean_phrase = (confirmation_phrase or "").strip().upper()
        if clean_phrase != REQUIRED_CONFIRMATION_PHRASE:
            raise BusinessRuleException(
                f"Confirmação inválida. Digite exatamente '{REQUIRED_CONFIRMATION_PHRASE}' para prosseguir."
            )

        # 1. Validação ou Criação de Backup Pré-Limpeza
        has_backup, recent_b = await self.backup_service.get_recent_valid_backup(max_age_hours=24)
        safety_backup = None
        if not has_backup:
            logger.info("Nenhum backup recente encontrado. Gerando snapshot de segurança pré-limpeza...")
            safety_backup = await self.backup_service.create_backup(user_id=admin_user_id)
        else:
            safety_backup = recent_b

        # 2. Levantamento dos registros a excluir
        demo_emp_stmt = select(Employee.id).where(Employee.is_demo == True)
        demo_emp_ids = list((await self.session.execute(demo_emp_stmt)).scalars().all())

        demo_tickets_stmt = select(Ticket.id).where(
            or_(Ticket.is_demo == True, Ticket.requester_id.in_(demo_emp_ids))
        )
        demo_ticket_ids = list((await self.session.execute(demo_tickets_stmt)).scalars().all())

        demo_assets_stmt = select(Asset.id).where(Asset.is_demo == True)
        demo_asset_ids = list((await self.session.execute(demo_assets_stmt)).scalars().all())

        demo_stock_stmt = select(StockItem.id).where(StockItem.is_demo == True)
        demo_stock_ids = list((await self.session.execute(demo_stock_stmt)).scalars().all())

        demo_users_stmt = select(UserAccount.id).where(
            UserAccount.is_demo == True,
            UserAccount.id != admin_user_id,
            UserAccount.is_admin == False
        )
        demo_user_ids = list((await self.session.execute(demo_users_stmt)).scalars().all())

        # Excluir arquivos físicos de anexos demo
        demo_att_stmt = select(Attachment).where(
            or_(
                Attachment.is_demo == True,
                and_(Attachment.entity_type == "ticket", Attachment.entity_id.in_(demo_ticket_ids))
            )
        )
        demo_attachments = list((await self.session.execute(demo_att_stmt)).scalars().all())
        removed_files_count = 0
        for att in demo_attachments:
            physical_file = settings.attachment_storage_dir / att.file_path
            if physical_file.exists():
                try:
                    physical_file.unlink()
                    removed_files_count += 1
                except Exception as err:
                    logger.warning("Falha ao remover arquivo de anexo demo %s: %s", physical_file, err)

        # 3. Exclusão em ordem estrita de dependências (Cascade-safe)
        if demo_ticket_ids:
            await self.session.execute(delete(ticket_assets).where(ticket_assets.c.ticket_id.in_(demo_ticket_ids)))
            await self.session.execute(delete(TicketMaterial).where(TicketMaterial.ticket_id.in_(demo_ticket_ids)))
            await self.session.execute(delete(TicketInteraction).where(TicketInteraction.ticket_id.in_(demo_ticket_ids)))
            await self.session.execute(delete(Ticket).where(Ticket.id.in_(demo_ticket_ids)))

        if demo_asset_ids:
            await self.session.execute(delete(AssetMovement).where(AssetMovement.asset_id.in_(demo_asset_ids)))
            await self.session.execute(delete(Asset).where(Asset.id.in_(demo_asset_ids)))

        if demo_stock_ids:
            await self.session.execute(delete(StockMovement).where(StockMovement.item_id.in_(demo_stock_ids)))
            await self.session.execute(delete(StockItem).where(StockItem.id.in_(demo_stock_ids)))

        if demo_attachments:
            att_ids = [a.id for a in demo_attachments]
            await self.session.execute(delete(Attachment).where(Attachment.id.in_(att_ids)))

        # Desvincular admin de colaborador demo e limpar sessões do WhatsApp
        from app.whatsapp.models import WhatsAppSession
        await self.session.execute(update(UserAccount).where(UserAccount.id == admin_user_id).values(employee_id=None))
        await self.session.execute(update(WhatsAppSession).values(employee_id=None, current_ticket_id=None, current_category_id=None))
        await self.session.execute(update(TicketCategory).values(default_sector_id=None))
        await self.session.execute(update(Employee).values(manager_id=None))

        if demo_user_ids:
            await self.session.execute(delete(user_role_association).where(user_role_association.c.user_id.in_(demo_user_ids)))
            await self.session.execute(delete(UserAccount).where(UserAccount.id.in_(demo_user_ids)))

        # Excluir colaboradores demo
        await self.session.execute(delete(Employee).where(Employee.is_demo == True))

        # Excluir setores demo
        await self.session.execute(delete(Sector).where(Sector.is_demo == True))

        # Excluir unidades demo
        await self.session.execute(delete(Unit).where(Unit.is_demo == True))

        # Excluir empresas demo
        await self.session.execute(delete(Company).where(Company.is_demo == True))

        # 4. Transição de modo para PRODUÇÃO
        await self.set_system_mode("PRODUCTION")

        # 5. Auditoria da operação
        clean_summary = {
            "tickets_removed": len(demo_ticket_ids),
            "assets_removed": len(demo_asset_ids),
            "stock_items_removed": len(demo_stock_ids),
            "users_removed": len(demo_user_ids),
            "attachments_removed": len(demo_attachments),
            "physical_files_unlinked": removed_files_count,
            "safety_backup_used": safety_backup.filename if safety_backup else None,
            "ip_address": ip_address,
        }

        audit_entry = AuditLog(
            event_type="system.demo.cleaned",
            entity_type="SYSTEM",
            entity_id=uuid.uuid4(),
            data=clean_summary,
            user_id=admin_user_id,
        )
        self.session.add(audit_entry)

        await self.session.commit()
        logger.info("Limpeza de dados de demonstração concluída com sucesso pelo usuário %s: %s", admin_user_id, clean_summary)

        return {
            "success": True,
            "message": "Dados de demonstração removidos com sucesso. O sistema está agora em Modo Empresarial Limpo.",
            "system_mode": "PRODUCTION",
            "summary": clean_summary,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def seed_demo_data(self, admin_user_id: uuid.UUID) -> dict:
        """Carrega o ambiente modelo idempotentemente, marcando todos os registros como is_demo=True."""
        # Se houver dados de demonstração remanescentes, limpa antes para evitar conflitos de unique keys
        status_info = await self.get_demo_status()
        if status_info["total_demo_records"] > 0:
            await self.clean_demo_data(
                admin_user_id=admin_user_id,
                confirmation_phrase=REQUIRED_CONFIRMATION_PHRASE,
                ip_address="internal-seed"
            )

        # 1. Empresa Modelo
        company = Company(
            name="TechCorp Soluções Empresariais Ltda.",
            cnpj="12.345.678/0001-90",
            is_demo=True
        )
        self.session.add(company)
        await self.session.flush()

        # 2. Unidades
        matriz = Unit(
            company_id=company.id,
            name="Matriz Corporativa - SP",
            code="MAT-01",
            type="MATRIZ",
            address="Av. Paulista, 1000 - Bela Vista, São Paulo - SP",
            is_demo=True
        )
        filial = Unit(
            company_id=company.id,
            name="Filial Operacional - RN",
            code="FIL-01",
            type="FILIAL",
            address="Av. Hermes da Fonseca, 500 - Tirol, Natal - RN",
            is_demo=True
        )
        self.session.add_all([matriz, filial])
        await self.session.flush()

        # 3. Setores
        sectors_data = [
            ("Financeiro", "FIN-01", matriz.id),
            ("Comercial", "COM-01", matriz.id),
            ("Diretoria", "DIR-01", matriz.id),
            ("Recursos Humanos", "RH-01", matriz.id),
            ("Administrativo", "ADM-02", filial.id),
            ("Operacional", "OPE-02", filial.id),
            ("Manutenção", "MAN-02", filial.id),
            ("Tecnologia da Informação", "TI-02", filial.id),
        ]
        sectors = {}
        for s_name, s_code, u_id in sectors_data:
            sec = Sector(unit_id=u_id, name=s_name, code=s_code, is_demo=True)
            self.session.add(sec)
            sectors[s_code] = sec
        await self.session.flush()

        # Reconectar categorias de chamados aos setores correspondentes
        sec_ti = sectors["TI-02"]
        sec_fin = sectors["FIN-01"]
        sec_rh = sectors["RH-01"]
        sec_adm = sectors["ADM-02"]
        sec_ope = sectors["OPE-02"]
        sec_man = sectors["MAN-02"]
        sec_com = sectors["COM-01"]

        categories = list((await self.session.execute(select(TicketCategory))).scalars().all())
        for cat in categories:
            if not cat.default_sector_id:
                c_low = cat.name.lower()
                if "finan" in c_low:
                    cat.default_sector_id = sec_fin.id
                elif "rh" in c_low or "recursos" in c_low:
                    cat.default_sector_id = sec_rh.id
                elif "adm" in c_low:
                    cat.default_sector_id = sec_adm.id
                elif "oper" in c_low or "logís" in c_low:
                    cat.default_sector_id = sec_ope.id
                elif "manut" in c_low or "predial" in c_low:
                    cat.default_sector_id = sec_man.id
                elif "comercial" in c_low or "venda" in c_low:
                    cat.default_sector_id = sec_com.id
                else:
                    cat.default_sector_id = sec_ti.id
        await self.session.flush()

        # 4. Colaboradores e Usuários departamentais
        role_solic = (await self.session.execute(select(Role).where(Role.name == "Solicitante"))).scalar_one_or_none()
        role_atendente = (await self.session.execute(select(Role).where(Role.name == "Atendente"))).scalar_one_or_none()

        demo_users_data = [
            ("Lucas Financeiro", "lucas.financeiro@empresa.com.br", "FIN-01", "Analista Financeiro", role_solic),
            ("Mariana Comercial", "mariana.comercial@empresa.com.br", "COM-01", "Executiva de Contas", role_solic),
            ("Roberto Diretoria", "roberto.diretoria@empresa.com.br", "DIR-01", "Diretor de Operações", role_solic),
            ("Carla RH", "carla.rh@empresa.com.br", "RH-01", "Coordenadora de DHO", role_solic),
            ("Patricia Administrativo", "patricia.adm@empresa.com.br", "ADM-02", "Supervisora ADM", role_solic),
            ("Marcos Operacional", "marcos.operacional@empresa.com.br", "OPE-02", "Líder de Logística", role_solic),
            ("Felipe Manutenção", "felipe.manutencao@empresa.com.br", "MAN-02", "Especialista Predial", role_solic),
            ("Gabriel TI", "gabriel.ti@empresa.com.br", "TI-02", "Analista de Suporte e Infra", role_atendente),
        ]

        created_employees = []
        for idx, (u_name, u_email, s_code, u_pos, u_role) in enumerate(demo_users_data, 1):
            sec = sectors[s_code]
            emp = Employee(
                unit_id=sec.unit_id,
                sector_id=sec.id,
                name=u_name,
                registration_number=f"DEMO-{idx:03d}",
                position=u_pos,
                phone=f"+551198888{idx:04d}",
                status="ATIVO",
                is_demo=True
            )
            self.session.add(emp)
            await self.session.flush()

            usr = UserAccount(
                email=u_email,
                hashed_password=hash_password("Demo@2026"),
                must_change_password=False,
                is_admin=False,
                is_demo=True,
                employee_id=emp.id
            )
            if u_role:
                usr.roles = [u_role]
            self.session.add(usr)
            created_employees.append(emp)

        await self.session.flush()

        # Criar colaborador dedicado para o Administrador caso ele não possua
        stmt_adm = select(UserAccount).where(UserAccount.is_admin == True).limit(1)
        adm_usr = (await self.session.execute(stmt_adm)).scalar_one_or_none()
        if adm_usr and not adm_usr.employee_id:
            sec_ti = sectors["TI-02"]
            emp_admin = Employee(
                unit_id=sec_ti.unit_id,
                sector_id=sec_ti.id,
                name="Administrador da Plataforma",
                registration_number="ADM-001",
                position="Administrador Geral",
                phone="+5511999990001",
                status="ATIVO",
                is_demo=True
            )
            self.session.add(emp_admin)
            await self.session.flush()
            await self.session.execute(
                update(UserAccount).where(UserAccount.id == adm_usr.id).values(employee_id=emp_admin.id)
            )
            await self.session.flush()

        # 5. Ativos Patrimoniais de Demonstração
        cat_note = (await self.session.execute(select(AssetCategory).where(AssetCategory.name.ilike("%notebook%")))).scalars().first()
        if not cat_note:
            cat_note = AssetCategory(name="Notebooks Corporativos", description="Laptops de uso pessoal", spec_schema={})
            self.session.add(cat_note)
            await self.session.flush()

        assets_sample = [
            ("PAT-0001", "Dell Latitude 5420 - Financeiro", cat_note.id, matriz.id, created_employees[0].id),
            ("PAT-0002", "Lenovo ThinkPad T14 - Comercial", cat_note.id, matriz.id, created_employees[1].id),
            ("PAT-0003", "MacBook Pro 14 M2 - Diretoria", cat_note.id, matriz.id, created_employees[2].id),
            ("PAT-0004", "Dell Latitude 3420 - RH", cat_note.id, matriz.id, created_employees[3].id),
            ("PAT-0005", "HP ProBook 440 G8 - TI", cat_note.id, filial.id, created_employees[7].id),
        ]
        for tag, name, cat_id, u_id, emp_id in assets_sample:
            ast = Asset(
                tag=tag,
                name=name,
                category_id=cat_id,
                unit_id=u_id,
                employee_id=emp_id,
                status=AssetStatus.IN_USE.value,
                technical_specs={"processador": "Core i7 / Apple Silicon", "memoria_ram": "16GB", "armazenamento": "512GB SSD"},
                is_demo=True
            )
            self.session.add(ast)

        # 6. Atualizar modo para DEMO
        await self.set_system_mode("DEMO")

        # 7. Auditoria
        audit_entry = AuditLog(
            event_type="system.demo.seeded",
            entity_type="SYSTEM",
            entity_id=uuid.uuid4(),
            data={"company": company.name, "users_created": len(demo_users_data), "units": 2},
            user_id=admin_user_id,
        )
        self.session.add(audit_entry)

        await self.session.commit()
        logger.info("Carga de demonstração concluída com sucesso.")

        return {
            "success": True,
            "message": "Ambiente demonstrativo carregado com sucesso.",
            "system_mode": "DEMO",
            "company": company.name,
            "users_count": len(demo_users_data),
        }
