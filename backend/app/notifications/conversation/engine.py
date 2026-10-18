"""
Camada conversacional independente de transporte (ADR-013 §7).

Recebe (canal, remetente, texto) e devolve as respostas. Não conhece HTTP, Telegram nem WhatsApp.
Age COMO O USUÁRIO VINCULADO: permissões e escopo vêm do banco (perfis do usuário), e as mesmas
regras de acesso da API web são aplicadas pelo ServiceDeskService — o chat não dá acesso extra.

Remetente não vinculado só recebe instruções de vínculo: nada de nomes, chamados ou se o
número/chat existe.
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import AppException
from app.identity.models import Permission, Role, UserAccount
from app.notifications.linking import LinkResult, redeem_link_code, unlink
from app.notifications.models import ConversationSession, UserChannelAddress
from app.organization.models import Employee
from app.service_desk.models import Ticket, TicketCategory
from app.service_desk.schemas import TicketCreate, TicketInteractionCreate
from app.service_desk.services import ServiceDeskService

logger = logging.getLogger(__name__)

MAX_LINK_FAILURES = 5
LINK_LOCK = timedelta(minutes=15)
MAX_TITLE = 120
MAX_TEXT = 3000
MENU_WORDS = {"0", "menu", "/menu", "cancelar", "ajuda", "/ajuda", "inicio", "voltar"}

UNLINKED_REPLY = (
    "Olá! Para usar este atendimento, vincule sua conta do sistema:\n"
    "1. Entre no sistema e abra Notificações > Minhas preferências.\n"
    "2. Gere o código de vínculo deste canal.\n"
    "3. Envie aqui: /vincular SEU_CODIGO"
)
INVALID_CODE_REPLY = "Código inválido ou expirado. Gere um novo no sistema e tente de novo."
LOCKED_REPLY = "Muitas tentativas incorretas. Aguarde alguns minutos e tente novamente."


@dataclass
class UserCtx:
    user_id: uuid.UUID
    employee_id: uuid.UUID | None
    unit_id: uuid.UUID | None
    sector_id: uuid.UUID | None
    name: str
    is_admin: bool
    permissions: set[str] = field(default_factory=set)

    @property
    def is_technician(self) -> bool:
        return self.is_admin or "service_desk.tickets.manage" in self.permissions

    @property
    def can_read_all(self) -> bool:
        return self.is_admin or "service_desk.tickets.read_all" in self.permissions


async def load_user_ctx(session: AsyncSession, user_id: uuid.UUID) -> UserCtx | None:
    """Permissões ATUAIS do usuário (banco), não as de um token antigo. Usuário inativo => None."""
    user = (await session.execute(select(UserAccount).where(UserAccount.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    codes = (
        await session.execute(
            select(Permission.code).join(Permission.roles).join(Role.users).where(UserAccount.id == user_id)
        )
    ).scalars()
    employee = None
    if user.employee_id:
        employee = (await session.execute(select(Employee).where(Employee.id == user.employee_id))).scalar_one_or_none()
    return UserCtx(
        user_id=user.id,
        employee_id=employee.id if employee else None,
        unit_id=employee.unit_id if employee else None,
        sector_id=employee.sector_id if employee else None,
        name=(employee.name if employee else user.email.split("@")[0]),
        is_admin=bool(user.is_admin),
        permissions=set(codes),
    )


class ConversationEngine:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.service = ServiceDeskService(session)

    # --- Entrada -----------------------------------------------------------------------------

    async def handle(self, channel: str, external_id: str, text: str) -> tuple[list[str], uuid.UUID | None]:
        """Processa uma mensagem. Retorna (respostas, user_id vinculado ou None). O commit fica com o chamador."""
        conv = await self._get_session(channel, external_id)
        conv.last_interaction_at = datetime.now(timezone.utc)
        message = (text or "").strip()[:MAX_TEXT]
        lowered = message.lower()

        command, _, argument = message.partition(" ")
        command = command.lower().split("@")[0]  # "/start@MeuBot" no Telegram em grupos
        word = command.lstrip("/")
        # No WhatsApp não há "/comando": "vincular ABC234" também vale — mas só fora de um diálogo em
        # andamento, senão o título de um chamado que comece com "vincular" viraria tentativa de vínculo.
        is_command = command.startswith("/") or conv.state == "IDLE" or conv.user_id is None

        if is_command and word in ("vincular", "start") and argument.strip():
            return await self._link(conv, channel, external_id, argument.strip())

        ctx = await load_user_ctx(self.session, conv.user_id) if conv.user_id else None
        if ctx is None and conv.user_id is not None:
            conv.user_id = None  # conta desativada ou removida: perde o acesso na hora
            self._reset(conv)
        if ctx is None:
            ctx = await self._ctx_from_address(conv, channel, external_id)
        if ctx is None:
            return [UNLINKED_REPLY], None

        if is_command and word == "desvincular":
            await unlink(self.session, ctx.user_id, channel)
            conv.user_id = None
            self._reset(conv)
            return ["Canal desvinculado. Você não receberá mais avisos por aqui."], None

        if lowered in MENU_WORDS or (is_command and word == "start"):
            self._reset(conv)
            return [self._menu(ctx)], ctx.user_id

        try:
            reply = await self._route(conv, ctx, message)
        except AppException as exc:
            self._reset(conv)
            reply = f"Não foi possível concluir: {exc.message}\n\n{self._menu(ctx)}"
        return [reply], ctx.user_id

    # --- Sessão e vínculo --------------------------------------------------------------------

    async def _get_session(self, channel: str, external_id: str) -> ConversationSession:
        conv = (
            await self.session.execute(
                select(ConversationSession).where(
                    ConversationSession.channel == channel, ConversationSession.external_id == external_id
                )
            )
        ).scalar_one_or_none()
        if conv is None:
            conv = ConversationSession(channel=channel, external_id=external_id, state="IDLE", context={})
            self.session.add(conv)
            await self.session.flush()
        return conv

    async def _ctx_from_address(self, conv: ConversationSession, channel: str, external_id: str) -> UserCtx | None:
        """Sessão nova de quem já tem endereço verificado (ex.: sessão apagada): reata ao usuário."""
        address = (
            await self.session.execute(
                select(UserChannelAddress).where(
                    UserChannelAddress.channel == channel,
                    UserChannelAddress.address == external_id,
                    UserChannelAddress.verified_at.is_not(None),
                )
            )
        ).scalar_one_or_none()
        if address is None:
            return None
        ctx = await load_user_ctx(self.session, address.user_id)
        if ctx is not None:
            conv.user_id = ctx.user_id
        return ctx

    async def _link(self, conv: ConversationSession, channel: str, external_id: str, code: str):
        now = datetime.now(timezone.utc)
        context = dict(conv.context or {})
        locked_until = context.get("locked_until")
        if locked_until and datetime.fromisoformat(locked_until) > now:
            return [LOCKED_REPLY], None

        result, user_id = await redeem_link_code(self.session, channel, external_id, code)
        if result == LinkResult.OK and user_id is not None:
            conv.user_id = user_id
            conv.context = {}
            conv.state = "IDLE"
            ctx = await load_user_ctx(self.session, user_id)
            greeting = f"Canal vinculado, {ctx.name}! Você receberá avisos por aqui.\n\n" if ctx else ""
            return [greeting + (self._menu(ctx) if ctx else "")], user_id

        if result == LinkResult.ALREADY_LINKED_ELSEWHERE:
            return ["Este chat já está vinculado a outra conta. Peça o desvínculo na conta atual primeiro."], None

        fails = int(context.get("link_fails", 0)) + 1
        if fails >= MAX_LINK_FAILURES:
            context = {"link_fails": 0, "locked_until": (now + LINK_LOCK).isoformat()}
        else:
            context["link_fails"] = fails
        conv.context = context
        flag_modified(conv, "context")
        return [INVALID_CODE_REPLY], None

    # --- Menu e estados ----------------------------------------------------------------------

    def _reset(self, conv: ConversationSession) -> None:
        conv.state = "IDLE"
        conv.context = {}
        flag_modified(conv, "context")

    def _menu(self, ctx: UserCtx) -> str:
        return (
            f"Olá, {ctx.name}! Como podemos ajudar?\n\n"
            "[1] Abrir novo chamado\n"
            "[2] Consultar meus chamados\n"
            "[3] Responder a um chamado\n\n"
            "Digite o número da opção, ou 0 a qualquer momento para voltar ao menu.\n"
            "/desvincular remove este canal."
        )

    async def _tickets(self, ctx: UserCtx) -> list[Ticket]:
        tickets = await self.service.list_tickets_for_user(
            user_employee_id=ctx.employee_id,
            user_id=ctx.user_id,
            sector_id=ctx.sector_id,
            is_technician=ctx.is_technician,
            can_read_all=ctx.can_read_all,
        )
        return sorted(tickets, key=lambda t: t.created_at, reverse=True)

    async def _route(self, conv: ConversationSession, ctx: UserCtx, text: str) -> str:
        state = conv.state or "IDLE"
        context = dict(conv.context or {})

        if state == "IDLE":
            if text in ("1", "abrir", "novo"):
                if not ctx.employee_id:
                    return "Sua conta não está ligada a um colaborador, então não pode abrir chamados por aqui."
                categories = list(
                    (
                        await self.session.execute(
                            select(TicketCategory).where(TicketCategory.is_active.is_(True)).order_by(TicketCategory.name)
                        )
                    ).scalars()
                )
                if not categories:
                    return "No momento não há categorias ativas para abrir chamados."
                conv.state = "AWAITING_CATEGORY"
                context["categories"] = [{"id": str(c.id), "name": c.name} for c in categories]
                self._save(conv, context)
                lines = [f"[{i + 1}] {c.name}" for i, c in enumerate(categories)]
                return "Escolha a categoria:\n\n" + "\n".join(lines) + "\n\nDigite o número (ou 0 para cancelar)."

            if text in ("2", "consultar", "meus"):
                tickets = (await self._tickets(ctx))[:5]
                if not tickets:
                    return "Você não tem chamados visíveis no momento.\n\n" + self._menu(ctx)
                lines = ["Chamados recentes:\n"]
                for t in tickets:
                    lines.append(
                        f"• #{str(t.id)[:8]} — {t.title}\n  Situação: {self.service._translate_status(t.status)} | Prioridade: {t.priority}"
                    )
                lines.append("\nDigite 3 para responder a um chamado ou 0 para o menu.")
                return "\n".join(lines)

            if text in ("3", "responder", "interagir"):
                conv.state = "AWAITING_INTERACTION_TICKET"
                return "Digite o início do número do chamado (mínimo 4 caracteres), por exemplo: a1b2c3d4"

            return "Opção não reconhecida.\n\n" + self._menu(ctx)

        if state == "AWAITING_CATEGORY":
            categories = context.get("categories", [])
            if not text.isdigit() or not 1 <= int(text) <= len(categories):
                return "Opção inválida. Digite o número da categoria (ou 0 para cancelar)."
            chosen = categories[int(text) - 1]
            context["category_id"], context["category_name"] = chosen["id"], chosen["name"]
            context.pop("categories", None)
            conv.state = "AWAITING_TITLE"
            self._save(conv, context)
            return f"Categoria: {chosen['name']}.\n\nDigite um título resumido para o chamado:"

        if state == "AWAITING_TITLE":
            context["title"] = text[:MAX_TITLE]
            conv.state = "AWAITING_DESCRIPTION"
            self._save(conv, context)
            return f"Título: {context['title']}\n\nAgora descreva o que está acontecendo:"

        if state == "AWAITING_DESCRIPTION":
            ticket = await self.service.create_ticket(
                schema=TicketCreate(
                    title=context.get("title", "Chamado"),
                    description=f"[Aberto via chat]\n{text}",
                    priority="MEDIUM",
                    category_id=uuid.UUID(context["category_id"]),
                ),
                requester_id=ctx.employee_id,
                origin_unit_id=ctx.unit_id,
                origin_sector_id=ctx.sector_id,
                user_id=ctx.user_id,
            )
            self._reset(conv)
            return (
                f"Chamado criado!\n\n• Número: #{str(ticket.id)[:8]}\n• Título: {ticket.title}\n"
                "• Situação: Aberto\n\nVocê receberá as atualizações por aqui.\n\n" + self._menu(ctx)
            )

        if state == "AWAITING_INTERACTION_TICKET":
            search = text.replace("#", "").strip().lower()
            if len(search) < 4:
                return "Informe pelo menos 4 caracteres do número do chamado (ou 0 para cancelar)."
            matches = [t for t in await self._tickets(ctx) if str(t.id).lower().startswith(search)]
            if not matches:
                return "Chamado não encontrado entre os que você pode acessar. Confira o número ou digite 0."
            if len(matches) > 1:
                return "Mais de um chamado corresponde. Digite mais caracteres do número."
            context["ticket_id"], context["ticket_title"] = str(matches[0].id), matches[0].title
            conv.state = "AWAITING_INTERACTION_MSG"
            self._save(conv, context)
            return f"Chamado: {matches[0].title} (#{str(matches[0].id)[:8]}).\n\nDigite a mensagem para o atendimento:"

        if state == "AWAITING_INTERACTION_MSG":
            await self.service.add_interaction(
                ticket_id=uuid.UUID(context["ticket_id"]),
                schema=TicketInteractionCreate(message=f"[Via chat] {text}", is_internal=False),
                author_id=ctx.user_id,
                user_employee_id=ctx.employee_id,
                is_technician=ctx.is_technician,
                can_read_all=ctx.can_read_all,
                can_internal_notes=False,  # nota interna só pela web, onde a visibilidade é explícita
                sector_id=ctx.sector_id,
            )
            self._reset(conv)
            return "Mensagem registrada no chamado.\n\n" + self._menu(ctx)

        self._reset(conv)
        return self._menu(ctx)

    def _save(self, conv: ConversationSession, context: dict) -> None:
        conv.context = context
        flag_modified(conv, "context")
