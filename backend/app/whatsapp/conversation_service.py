"""
MOD-15 — WhatsApp Integration (Conversation Service)

Máquina de estados para atendimento receptivo via WhatsApp:
- Identificação e vinculação de colaboradores
- Abertura conversacional de chamados
- Consulta de status de chamados
- Envio de interações e respostas
"""

from datetime import datetime, timezone
import logging
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.organization.models import Employee
from app.service_desk.models import Ticket, TicketCategory
from app.service_desk.schemas import TicketCreate, TicketInteractionCreate
from app.service_desk.services import ServiceDeskService
from app.whatsapp.models import WhatsAppConfig, WhatsAppSession
from app.whatsapp.adapter import get_whatsapp_adapter

logger = logging.getLogger(__name__)


class WhatsAppConversationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_config(self) -> WhatsAppConfig:
        stmt = select(WhatsAppConfig).limit(1)
        config = (await self.session.execute(stmt)).scalar_one_or_none()
        if not config:
            config = WhatsAppConfig(provider="MOCK", is_enabled=True)
            self.session.add(config)
            await self.session.flush()
        return config

    async def process_incoming_message(self, from_phone: str, text: str) -> str:
        """Processa a mensagem recebida e retorna a resposta gerada."""
        clean_phone = "".join(ch for ch in from_phone if ch.isdigit())
        config = await self.get_config()
        adapter = get_whatsapp_adapter(config)
        msg_clean = text.strip()

        # Buscar ou criar sessão
        stmt_s = select(WhatsAppSession).where(WhatsAppSession.phone == clean_phone)
        wa_session = (await self.session.execute(stmt_s)).scalar_one_or_none()
        if not wa_session:
            wa_session = WhatsAppSession(phone=clean_phone, state="IDLE", context_data={})
            self.session.add(wa_session)
            await self.session.flush()

        wa_session.last_interaction_at = datetime.now(timezone.utc)

        # 1. Identificar colaborador
        if not wa_session.employee_id:
            stmt_e = select(Employee).where(Employee.phone == clean_phone)
            employee = (await self.session.execute(stmt_e)).scalar_one_or_none()
            if employee:
                wa_session.employee_id = employee.id
                await self.session.flush()

        # Se ainda não estiver vinculado
        if not wa_session.employee_id:
            return await self._handle_unlinked_user(wa_session, msg_clean, adapter)

        # Buscar colaborador vinculado
        stmt_emp = (
            select(Employee)
            .options(selectinload(Employee.unit), selectinload(Employee.sector), selectinload(Employee.user_account))
            .where(Employee.id == wa_session.employee_id)
        )
        employee = (await self.session.execute(stmt_emp)).scalar_one_or_none()
        if not employee:
            wa_session.employee_id = None
            await self.session.commit()
            return await self._handle_unlinked_user(wa_session, msg_clean, adapter)

        # Comandos de escape universal
        if msg_clean.lower() in ("0", "cancelar", "menu", "ajuda", "inicio", "voltar"):
            wa_session.state = "IDLE"
            wa_session.context_data = {}
            wa_session.current_ticket_id = None
            wa_session.current_category_id = None
            await self.session.commit()
            reply = self._get_main_menu(employee.name)
            await adapter.send_message(clean_phone, reply)
            return reply

        # Processamento baseado no estado atual
        reply = await self._route_state(wa_session, employee, msg_clean, adapter)
        await self.session.commit()
        await adapter.send_message(clean_phone, reply)
        return reply

    def _get_main_menu(self, employee_name: str) -> str:
        return (
            f"Olá, *{employee_name}*! 👋\n"
            f"Como podemos te ajudar hoje na TI?\n\n"
            f"[1] 📝 Abrir Novo Chamado\n"
            f"[2] 📋 Consultar Meus Chamados\n"
            f"[3] 💬 Responder a um Chamado\n\n"
            f"_(Digite o número da opção desejada ou '0' a qualquer momento para voltar ao menu)_"
        )

    async def _handle_unlinked_user(self, wa_session: WhatsAppSession, text: str, adapter) -> str:
        if wa_session.state == "AWAITING_REGISTRATION_LINK":
            stmt = select(Employee).where(Employee.registration_number == text)
            emp = (await self.session.execute(stmt)).scalar_one_or_none()
            if emp:
                emp.phone = wa_session.phone
                wa_session.employee_id = emp.id
                wa_session.state = "IDLE"
                await self.session.commit()
                reply = (
                    f"✅ Número vinculado com sucesso a *{emp.name}*!\n\n"
                    + self._get_main_menu(emp.name)
                )
                await adapter.send_message(wa_session.phone, reply)
                return reply
            else:
                reply = "❌ Matrícula funcional não encontrada. Por favor, digite uma matrícula válida ou procure o suporte de TI:"
                await adapter.send_message(wa_session.phone, reply)
                return reply

        wa_session.state = "AWAITING_REGISTRATION_LINK"
        await self.session.commit()
        reply = (
            "Olá! Não identificamos o seu número de WhatsApp no cadastro da empresa.\n\n"
            "Por favor, digite a sua *Matrícula Funcional* para vincularmos seu acesso:"
        )
        await adapter.send_message(wa_session.phone, reply)
        return reply

    async def _route_state(self, wa_session: WhatsAppSession, employee: Employee, text: str, adapter) -> str:
        state = wa_session.state

        if state == "IDLE":
            if text in ("1", "abrir", "novo"):
                # Carregar categorias ativas
                stmt_c = select(TicketCategory).where(TicketCategory.is_active.is_(True)).order_by(TicketCategory.name.asc())
                cats = list((await self.session.execute(stmt_c)).scalars().all())
                if not cats:
                    return "No momento não há categorias ativas disponíveis para abertura de chamados."

                wa_session.state = "AWAITING_CATEGORY"
                new_ctx = dict(wa_session.context_data or {})
                new_ctx["available_categories"] = [
                    {"id": str(c.id), "name": c.name} for c in cats
                ]
                wa_session.context_data = new_ctx
                flag_modified(wa_session, "context_data")
                cat_list_str = "\n".join([f"[{i+1}] {c.name}" for i, c in enumerate(cats)])
                return (
                    "Selecione a categoria do seu chamado:\n\n"
                    + cat_list_str
                    + "\n\n_(Digite o número correspondente ou '0' para cancelar)_"
                )

            elif text in ("2", "consultar", "meus"):
                sd_service = ServiceDeskService(self.session)
                tickets = await sd_service.list_tickets_for_user(user_employee_id=employee.id, is_technician=False)
                if not tickets:
                    return "Você não possui nenhum chamado registrado no momento.\n\n" + self._get_main_menu(employee.name)

                recent = tickets[:5]
                lines = ["📋 *Seus Chamados Recentes:*\n"]
                for t in recent:
                    status_pt = sd_service._translate_status(t.status)
                    prio_pt = t.priority
                    short_id = str(t.id)[:8]
                    lines.append(f"• *#{short_id}* — {t.title}\n   Status: _{status_pt}_ | Prioridade: {prio_pt}")
                lines.append("\n_(Digite [3] para responder a um chamado ou [0] para o menu principal)_")
                return "\n".join(lines)

            elif text in ("3", "responder", "interagir"):
                wa_session.state = "AWAITING_INTERACTION_TICKET"
                return (
                    "Por favor, digite os primeiros dígitos ou o ID completo do chamado que deseja responder:\n"
                    "_(Exemplo: a1b2c3d4)_"
                )

            else:
                return "Opção não reconhecida.\n\n" + self._get_main_menu(employee.name)

        elif state == "AWAITING_CATEGORY":
            avail = wa_session.context_data.get("available_categories", [])
            selected_cat = None
            if text.isdigit():
                idx = int(text) - 1
                if 0 <= idx < len(avail):
                    selected_cat = avail[idx]

            if not selected_cat:
                return "Opção inválida. Por favor, digite o número da categoria correspondente (ou '0' para cancelar)."

            wa_session.current_category_id = uuid.UUID(selected_cat["id"])
            wa_session.state = "AWAITING_TITLE"
            return (
                f"Categoria selecionada: *{selected_cat['name']}*.\n\n"
                f"Agora, digite um *Título Resumido* para o chamado:"
            )

        elif state == "AWAITING_TITLE":
            new_ctx = dict(wa_session.context_data or {})
            new_ctx["ticket_title"] = text
            wa_session.context_data = new_ctx
            flag_modified(wa_session, "context_data")
            wa_session.state = "AWAITING_DESCRIPTION"
            return (
                f"Título: *{text}*\n\n"
                f"Por favor, descreva detalhadamente o ocorrido:"
            )

        elif state == "AWAITING_DESCRIPTION":
            title = wa_session.context_data.get("ticket_title", "Chamado via WhatsApp")
            desc = text

            sd_service = ServiceDeskService(self.session)
            ticket_in = TicketCreate(
                title=title,
                description=f"[Aberto via WhatsApp]\n{desc}",
                priority="MEDIUM",
                category_id=wa_session.current_category_id
            )

            # Usuário do employee se existir
            author_user_id = employee.user_account.id if employee.user_account else None

            created_ticket = await sd_service.create_ticket(
                schema=ticket_in,
                requester_id=employee.id,
                origin_unit_id=employee.unit_id,
                origin_sector_id=employee.sector_id,
                user_id=author_user_id
            )

            wa_session.state = "IDLE"
            wa_session.context_data = {}
            wa_session.current_category_id = None
            wa_session.current_ticket_id = None

            short_id = str(created_ticket.id)[:8]
            return (
                f"🎉 *Chamado criado com sucesso!*\n\n"
                f"• *Número:* #{short_id}\n"
                f"• *Título:* {created_ticket.title}\n"
                f"• *Status:* Aberto\n\n"
                f"Nossa equipe técnica já recebeu sua solicitação e você receberá atualizações por aqui.\n\n"
                f"_(Digite '0' a qualquer momento para voltar ao menu)_"
            )

        elif state == "AWAITING_INTERACTION_TICKET":
            stmt_t = select(Ticket).where(Ticket.requester_id == employee.id)
            user_tickets = list((await self.session.execute(stmt_t)).scalars().all())

            matched = None
            search = text.replace("#", "").strip().lower()
            for t in user_tickets:
                if str(t.id).lower().startswith(search) or search in str(t.id).lower():
                    matched = t
                    break

            if not matched:
                return "Chamado não encontrado em sua lista. Verifique os dígitos informados ou digite '0' para cancelar."

            wa_session.current_ticket_id = matched.id
            wa_session.state = "AWAITING_INTERACTION_MSG"
            short_id = str(matched.id)[:8]
            return (
                f"Chamado selecionado: *{matched.title}* (#{short_id})\n\n"
                f"Digite a mensagem ou informação que deseja enviar para o atendimento:"
            )

        elif state == "AWAITING_INTERACTION_MSG":
            ticket_id = wa_session.current_ticket_id
            author_user_id = employee.user_account.id if employee.user_account else None

            # Se não tiver user_account, podemos associar ao user do admin ou gerar interação
            if not author_user_id:
                # busca qualquer user para autor de auditoria
                stmt_u = select(Employee.id).limit(1)
                # se não houver user_account, author_user_id = None

            sd_service = ServiceDeskService(self.session)
            await sd_service.add_interaction(
                ticket_id=ticket_id,
                schema=TicketInteractionCreate(
                    message=f"[Via WhatsApp] {text}",
                    is_internal=False
                ),
                author_id=author_user_id or employee.id,
                user_employee_id=employee.id,
                is_technician=False
            )

            wa_session.state = "IDLE"
            wa_session.current_ticket_id = None
            wa_session.context_data = {}

            return (
                "✅ *Mensagem enviada com sucesso!*\n\n"
                "Sua resposta foi registrada no chamado e o técnico responsável foi notificado.\n\n"
                + self._get_main_menu(employee.name)
            )

        wa_session.state = "IDLE"
        return self._get_main_menu(employee.name)
