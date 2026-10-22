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
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.assets.models import Asset, AssetCategory, AssetStatus
from app.attachments.models import Attachment
from app.audit.models import AuditLog
from app.backup.services import BackupService
from app.config import get_settings
from app.core.exceptions import BusinessRuleException
from app.core.security import hash_password
from app.core.settings_model import SystemSetting
from app.inventory_audit.models import InventoryAudit, InventoryAuditItem
from app.identity.models import Role, UserAccount, user_role_association
from app.movements.models import AssetMovement
from app.notifications.models import AutomationMark, Delivery, DeliveryAttempt, DomainEvent, Notification
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
RESET_CONFIRMATION_PHRASE = "ZERAR TODA A BASE"


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
            stmt = select(func.count()).select_from(model).where(model.is_demo.is_(True))
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
                "is_usable": True,
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
        demo_emp_stmt = select(Employee.id).where(Employee.is_demo.is_(True))
        demo_emp_ids = list((await self.session.execute(demo_emp_stmt)).scalars().all())

        demo_tickets_stmt = select(Ticket.id).where(
            or_(Ticket.is_demo.is_(True), Ticket.requester_id.in_(demo_emp_ids))
        )
        demo_ticket_ids = list((await self.session.execute(demo_tickets_stmt)).scalars().all())

        demo_assets_stmt = select(Asset.id).where(Asset.is_demo.is_(True))
        demo_asset_ids = list((await self.session.execute(demo_assets_stmt)).scalars().all())

        demo_stock_stmt = select(StockItem.id).where(StockItem.is_demo.is_(True))
        demo_stock_ids = list((await self.session.execute(demo_stock_stmt)).scalars().all())

        demo_users_stmt = select(UserAccount.id).where(
            UserAccount.is_demo.is_(True),
            UserAccount.id != admin_user_id,
            UserAccount.is_admin.is_(False)
        )
        demo_user_ids = list((await self.session.execute(demo_users_stmt)).scalars().all())

        # Excluir arquivos físicos de anexos demo
        demo_att_stmt = select(Attachment).where(
            or_(
                Attachment.is_demo.is_(True),
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

        # Desvincular admin de colaborador demo
        await self.session.execute(update(UserAccount).where(UserAccount.id == admin_user_id).values(employee_id=None))
        # Categorias que apontavam para setores de exemplo voltam ao setor de TI real (catálogo inicial), se existir.
        from app.core.starter_catalog import TI_SECTOR_CODE

        real_ti_id = (
            await self.session.execute(select(Sector.id).where(Sector.code == TI_SECTOR_CODE, Sector.is_demo.is_(False)))
        ).scalar_one_or_none()
        demo_sector_ids = select(Sector.id).where(Sector.is_demo.is_(True))
        await self.session.execute(
            update(TicketCategory).where(TicketCategory.default_sector_id.in_(demo_sector_ids)).values(default_sector_id=real_ti_id)
        )
        await self.session.execute(update(Employee).values(manager_id=None))

        if demo_user_ids:
            await self.session.execute(delete(user_role_association).where(user_role_association.c.user_id.in_(demo_user_ids)))
            await self.session.execute(delete(UserAccount).where(UserAccount.id.in_(demo_user_ids)))

        # Excluir colaboradores demo
        await self.session.execute(delete(Employee).where(Employee.is_demo.is_(True)))

        # Excluir setores demo
        await self.session.execute(delete(Sector).where(Sector.is_demo.is_(True)))

        # Excluir unidades demo (menos as que ainda abrigam setores reais, como o de TI do catálogo inicial)
        await self.session.execute(
            delete(Unit).where(Unit.is_demo.is_(True), Unit.id.not_in(select(Sector.unit_id)))
        )

        # Excluir empresas demo
        await self.session.execute(delete(Company).where(Company.is_demo.is_(True)))

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

    async def reset_all_data(self, admin_user_id: uuid.UUID, confirmation_phrase: str, ip_address: str = "127.0.0.1") -> dict:
        """Apaga todos os dados de trabalho (importados, cadastrados ou de demonstração).

        Mantém o que faz o sistema funcionar: contas de usuário, perfis e permissões, categorias,
        configurações (SMTP, canais), empresa, a unidade e o setor de TI do catálogo inicial, a
        trilha de auditoria e os backups.
        """
        if (confirmation_phrase or "").strip().upper() != RESET_CONFIRMATION_PHRASE:
            raise BusinessRuleException(
                f"Confirmação inválida. Digite exatamente '{RESET_CONFIRMATION_PHRASE}' para prosseguir."
            )

        has_backup, recent = await self.backup_service.get_recent_valid_backup(max_age_hours=24)
        safety_backup = recent if has_backup else await self.backup_service.create_backup(user_id=admin_user_id)

        from app.core.starter_catalog import TI_SECTOR_CODE

        ti_sector = (
            await self.session.execute(select(Sector).where(Sector.code == TI_SECTOR_CODE))
        ).scalars().first()
        keep_sector_id = ti_sector.id if ti_sector else None
        keep_unit_id = ti_sector.unit_id if ti_sector else None

        async def count(model) -> int:
            return (await self.session.execute(select(func.count()).select_from(model))).scalar() or 0

        summary = {
            "tickets_removed": await count(Ticket),
            "assets_removed": await count(Asset),
            "stock_items_removed": await count(StockItem),
            "employees_removed": await count(Employee),
            "attachments_removed": await count(Attachment),
            "safety_backup_used": safety_backup.filename if safety_backup else None,
            "ip_address": ip_address,
        }

        files_removed = 0
        for att in (await self.session.execute(select(Attachment))).scalars().all():
            physical_file = settings.attachment_storage_dir / att.file_path
            if physical_file.exists():
                try:
                    physical_file.unlink()
                    files_removed += 1
                except OSError as err:
                    logger.warning("Falha ao remover arquivo de anexo %s: %s", physical_file, err)
        summary["physical_files_unlinked"] = files_removed

        # Ordem das dependências: filhos antes dos pais.
        await self.session.execute(delete(Notification))
        await self.session.execute(delete(DeliveryAttempt))
        await self.session.execute(delete(Delivery))
        await self.session.execute(delete(DomainEvent))
        await self.session.execute(delete(AutomationMark))
        await self.session.execute(delete(InventoryAuditItem))
        await self.session.execute(delete(InventoryAudit))
        await self.session.execute(delete(ticket_assets))
        await self.session.execute(delete(TicketMaterial))
        await self.session.execute(delete(TicketInteraction))
        await self.session.execute(delete(Ticket))
        await self.session.execute(delete(AssetMovement))
        await self.session.execute(delete(Asset))
        await self.session.execute(delete(StockMovement))
        await self.session.execute(delete(StockItem))
        await self.session.execute(delete(Attachment))

        await self.session.execute(update(UserAccount).values(employee_id=None))
        await self.session.execute(update(Employee).values(manager_id=None))
        await self.session.execute(delete(Employee))
        await self.session.execute(update(TicketCategory).values(default_sector_id=keep_sector_id))
        sector_stmt = delete(Sector)
        unit_stmt = delete(Unit)
        if keep_sector_id:
            sector_stmt = sector_stmt.where(Sector.id != keep_sector_id)
            unit_stmt = unit_stmt.where(Unit.id != keep_unit_id)
        await self.session.execute(sector_stmt)
        await self.session.execute(unit_stmt)

        await self.set_system_mode("PRODUCTION")
        self.session.add(
            AuditLog(
                event_type="system.data.reset",
                entity_type="SYSTEM",
                entity_id=uuid.uuid4(),
                data=summary,
                user_id=admin_user_id,
            )
        )
        await self.session.commit()
        logger.warning("Base zerada pelo usuário %s: %s", admin_user_id, summary)

        return {
            "success": True,
            "message": "Base zerada. Usuários, perfis, categorias, configurações e auditoria foram mantidos.",
            "system_mode": "PRODUCTION",
            "summary": summary,
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
        stmt_c = select(Company).where(Company.cnpj == "12.345.678/0001-90")
        company = (await self.session.execute(stmt_c)).scalar_one_or_none()
        if not company:
            company = Company(
                name="TechCorp Soluções Empresariais Ltda.",
                cnpj="12.345.678/0001-90",
                is_demo=True
            )
            self.session.add(company)
            await self.session.flush()
        else:
            company.is_demo = True

        # 2. Unidades
        stmt_m = select(Unit).where(Unit.code == "MAT-01")
        matriz = (await self.session.execute(stmt_m)).scalar_one_or_none()
        if not matriz:
            matriz = Unit(
                company_id=company.id,
                name="Matriz Corporativa - SP",
                code="MAT-01",
                type="MATRIZ",
                address="Av. Paulista, 1000 - Bela Vista, São Paulo - SP",
                is_demo=True
            )
            self.session.add(matriz)
            await self.session.flush()
        # A Matriz criada na instalação é a unidade real da empresa: continua sendo após limpar o exemplo.

        stmt_f = select(Unit).where(Unit.code == "FIL-01")
        filial = (await self.session.execute(stmt_f)).scalar_one_or_none()
        if not filial:
            filial = Unit(
                company_id=company.id,
                name="Filial Operacional - RN",
                code="FIL-01",
                type="FILIAL",
                address="Av. Hermes da Fonseca, 500 - Tirol, Natal - RN",
                is_demo=True
            )
            self.session.add(filial)
            await self.session.flush()
        else:
            filial.is_demo = True

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
            stmt_s = select(Sector).where(Sector.code == s_code)
            sec = (await self.session.execute(stmt_s)).scalar_one_or_none()
            if not sec:
                sec = Sector(unit_id=u_id, name=s_name, code=s_code, is_demo=True)
                self.session.add(sec)
                await self.session.flush()
            else:
                sec.is_demo = True
                sec.unit_id = u_id
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

        from app.core.starter_catalog import TI_SECTOR_CODE

        real_ti_id = (await self.session.execute(select(Sector.id).where(Sector.code == TI_SECTOR_CODE))).scalar_one_or_none()
        categories = list((await self.session.execute(select(TicketCategory))).scalars().all())
        for cat in categories:
            if not cat.default_sector_id or cat.default_sector_id == real_ti_id:
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
        created_users: list[UserAccount] = []
        for idx, (u_name, u_email, s_code, u_pos, u_role) in enumerate(demo_users_data, 1):
            sec = sectors[s_code]
            reg_num = f"DEMO-{idx:03d}"
            stmt_e = select(Employee).where(Employee.registration_number == reg_num)
            emp = (await self.session.execute(stmt_e)).scalar_one_or_none()
            if not emp:
                emp = Employee(
                    unit_id=sec.unit_id,
                    sector_id=sec.id,
                    name=u_name,
                    registration_number=reg_num,
                    position=u_pos,
                    phone=f"+551198888{idx:04d}",
                    status="ATIVO",
                    is_demo=True
                )
                self.session.add(emp)
                await self.session.flush()
            else:
                emp.is_demo = True
                emp.unit_id = sec.unit_id
                emp.sector_id = sec.id
                emp.phone = f"+551198888{idx:04d}"

            stmt_u = select(UserAccount).options(selectinload(UserAccount.roles)).where(UserAccount.email == u_email)
            usr = (await self.session.execute(stmt_u)).scalar_one_or_none()
            if not usr:
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
            else:
                usr.is_demo = True
                usr.employee_id = emp.id
            created_employees.append(emp)
            created_users.append(usr)

        await self.session.flush()

        # Criar colaborador dedicado para o Administrador caso ele não possua
        stmt_adm = select(UserAccount).where(UserAccount.is_admin.is_(True)).limit(1)
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
        warranty_days = {"PAT-0001": 20, "PAT-0002": 5, "PAT-0003": 400, "PAT-0004": 200, "PAT-0005": 90}
        for tag, name, cat_id, u_id, emp_id in assets_sample:
            stmt_a = select(Asset).where(Asset.tag == tag)
            ast = (await self.session.execute(stmt_a)).scalar_one_or_none()
            if not ast:
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
            else:
                ast.is_demo = True
                ast.unit_id = u_id
                ast.employee_id = emp_id
            # Duas garantias perto de vencer mostram o alerta automático do worker.
            ast.warranty_expires = date.today() + timedelta(days=warranty_days[tag])

        await self.session.flush()
        await self._seed_demo_stock(matriz.id)
        await self._seed_demo_tickets(sec_ti, created_employees, created_users, adm_usr)

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


    async def _seed_demo_stock(self, unit_id: uuid.UUID) -> None:
        """Insumos de exemplo; três ficam no mínimo ou abaixo, para ver o alerta de estoque baixo."""
        categories = {c.name: c.id for c in (await self.session.execute(select(StockCategory))).scalars()}
        sample = [
            ("Toner HP 85A (preto)", 2, 5, "Toners & Suprimentos"),
            ("Cabo HDMI 2 m", 15, 5, "Cabos & Conectores"),
            ("Mouse USB", 3, 10, "Periféricos & Acessórios"),
            ("SSD 480 GB", 8, 3, "Componentes & Peças"),
            ("Cabo de rede Cat6 5 m", 10, 10, "Cabos & Conectores"),
        ]
        for name, quantity, minimum, category in sample:
            exists = (
                await self.session.execute(select(StockItem.id).where(StockItem.name == name, StockItem.is_demo.is_(True)))
            ).first()
            if not exists:
                self.session.add(
                    StockItem(
                        name=name, unit_id=unit_id, quantity=quantity, min_quantity=minimum,
                        category_id=categories.get(category), technical_specs={}, is_demo=True,
                    )
                )

    async def _seed_demo_tickets(
        self, sector_ti: Sector, employees: list[Employee], users: list[UserAccount], admin: UserAccount | None
    ) -> None:
        """Chamados de exemplo em vários estágios, gravados direto (não disparam notificações)."""
        if not employees or not users:
            return
        categories = {c.name: c.id for c in (await self.session.execute(select(TicketCategory))).scalars()}
        technician = users[-1]  # "Gabriel TI", perfil Atendente
        sample = [
            ("Notebook não liga após atualização", "Depois da atualização de ontem o equipamento não inicia.", "HIGH", "IN_PROGRESS", 0, technician, "Hardware e equipamentos"),
            ("Sem acesso à pasta compartilhada do financeiro", "Aparece acesso negado ao abrir a pasta Financeiro.", "MEDIUM", "OPENED", 1, None, "Acessos e contas"),
            ("Impressora do RH com papel enroscando", "Trava a cada 3 ou 4 folhas.", "LOW", "PENDING", 3, technician, "Impressão"),
            ("Instalar o Office na máquina nova", "Preciso do pacote Office licenciado.", "LOW", "RESOLVED", 2, technician, "Software e sistemas"),
            ("Wi-Fi caindo na sala de reuniões", "Cai várias vezes durante as videochamadas.", "CRITICAL", "OPENED", 4, None, "Rede e internet"),
            ("Solicitação de mouse sem fio", "O atual está com o botão falhando.", "LOW", "CLOSED", 5, admin, "Outros"),
        ]
        for title, description, priority, status, requester_idx, assignee, category in sample:
            requester = employees[requester_idx]
            ticket = Ticket(
                title=title, description=description, priority=priority, status=status, custom_fields={},
                requester_id=requester.id, assignee_id=assignee.id if assignee else None,
                origin_unit_id=requester.unit_id, origin_sector_id=requester.sector_id,
                responsible_sector_id=sector_ti.id, category_id=categories.get(category), is_demo=True,
            )
            self.session.add(ticket)
            await self.session.flush()
            if assignee:
                self.session.add(
                    TicketInteraction(
                        ticket_id=ticket.id, author_id=assignee.id, message="Recebi o chamado e já estou verificando.", is_internal=False
                    )
                )
        await self.session.flush()
