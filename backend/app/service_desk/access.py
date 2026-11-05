"""
Regra única de acesso a um chamado (chamados vinculados, PR 1).

Antes as condições viviam espalhadas em ``get_ticket_for_user`` e ``update_ticket``. Aqui ficam num lugar só, como
função pura sobre o chamado e o escopo de quem pede (``AccessContext.ticket_scope()``), para que toda rota e os
próximos níveis (acompanhamento de subchamados, anexos restritos) usem a mesma decisão.

Papéis de quem pede, em relação ao chamado:
- **solicitante**: o colaborador para quem o pedido foi feito (``requester_id``);
- **criador**: o usuário que abriu (``created_by_user_id``); pode ser diferente do solicitante;
- **atendente**: tem ``tickets.manage`` e o chamado é do setor dele ou está atribuído a ele;
- **gestão**: ``read_all`` vê qualquer chamado.

Solicitante e criador podem o mesmo no chamado: ver, comentar em público e finalizar ou encerrar.
"""

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class TicketAccess:
    can_view: bool
    is_requester: bool
    is_creator: bool
    # Atende o chamado: altera campos, atribui, cria nota interna (com is_technician).
    is_sector_attendant: bool

    @property
    def is_requester_or_creator(self) -> bool:
        return self.is_requester or self.is_creator


def evaluate_ticket_access(
    ticket,
    *,
    user_employee_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    sector_id: uuid.UUID | None,
    is_technician: bool,
    can_read_all: bool,
) -> TicketAccess:
    """``sector_id`` já resolvido (o serviço busca o do colaborador quando não veio)."""
    is_requester = user_employee_id is not None and ticket.requester_id == user_employee_id
    is_creator = user_id is not None and ticket.created_by_user_id == user_id
    in_sector_or_assigned = (sector_id is not None and ticket.responsible_sector_id == sector_id) or (
        user_id is not None and ticket.assignee_id == user_id
    )
    is_sector_attendant = is_technician and (can_read_all or in_sector_or_assigned)
    can_view = can_read_all or is_sector_attendant or is_requester or is_creator
    return TicketAccess(
        can_view=can_view,
        is_requester=is_requester,
        is_creator=is_creator,
        is_sector_attendant=is_sector_attendant,
    )
