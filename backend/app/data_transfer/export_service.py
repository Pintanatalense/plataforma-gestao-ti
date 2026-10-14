"""
MOD-13 — Data Transfer (Export Service)

Exportação de dados em CSV com:
- Sanitização rigorosa contra CSV Formula Injection (=, +, -, @)
- Codificação UTF-8 com BOM para abertura perfeita no Microsoft Excel
- Omissão estrita de senhas, hashes e tokens de segurança
- Suporte a filtros por período e status
"""

import csv
import io
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BusinessRuleException
from app.data_transfer.schemas import ExportFilterParams


def sanitize_csv_cell(val: Any) -> str:
    """Prevenção contra CSV Formula Injection."""
    if val is None:
        return ""
    text = str(val).strip()
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{text}"
    return text


class DataExportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def generate_csv(self, params: ExportFilterParams) -> tuple[str, bytes]:
        """Gera o arquivo CSV em memória com UTF-8 BOM e retorna (filename, bytes)."""
        entity = params.entity.lower()
        delimiter = params.delimiter if params.delimiter in (";", ",") else ";"

        if entity == "tickets":
            headers, rows = await self._export_tickets(params)
        elif entity == "users":
            headers, rows = await self._export_users(params)
        elif entity == "employees":
            headers, rows = await self._export_employees(params)
        elif entity == "categories":
            headers, rows = await self._export_categories(params)
        elif entity == "stock_items":
            headers, rows = await self._export_stock_items(params)
        elif entity == "units":
            headers, rows = await self._export_units(params)
        elif entity == "sectors":
            headers, rows = await self._export_sectors(params)
        else:
            raise BusinessRuleException(f"Entidade '{params.entity}' não suportada para exportação.")

        output = io.StringIO()
        writer = csv.writer(output, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)

        for row in rows:
            sanitized = [sanitize_csv_cell(cell) for cell in row]
            writer.writerow(sanitized)

        # UTF-8 BOM + Conteúdo codificado em UTF-8
        csv_bytes = b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")
        filename = f"export_{entity}.csv"
        return filename, csv_bytes

    async def _export_tickets(self, params: ExportFilterParams) -> tuple[list[str], list[list[Any]]]:
        from app.service_desk.models import Ticket
        stmt = (
            select(Ticket)
            .options(
                selectinload(Ticket.category),
                selectinload(Ticket.requester),
                selectinload(Ticket.assignee),
            )
            .order_by(Ticket.created_at.desc())
        )

        if params.status:
            stmt = stmt.where(Ticket.status == params.status)
        if params.category_id:
            stmt = stmt.where(Ticket.category_id == params.category_id)
        if params.start_date:
            stmt = stmt.where(Ticket.created_at >= params.start_date)
        if params.end_date:
            stmt = stmt.where(Ticket.created_at <= params.end_date)

        result = await self.session.execute(stmt)
        tickets = result.scalars().all()

        headers = [
            "ID", "Título", "Descrição", "Prioridade", "Status",
            "Categoria", "Solicitante", "Responsável", "Data Abertura"
        ]
        rows = []
        for t in tickets:
            cat_name = t.category.name if t.category else "Sem Categoria"
            req_name = t.requester.name if t.requester else "Não identificado"
            ass_name = t.assignee_name or "Não atribuído"
            created_str = t.created_at.strftime("%d/%m/%Y %H:%M:%S") if t.created_at else ""
            rows.append([
                str(t.id), t.title, t.description, t.priority, t.status,
                cat_name, req_name, ass_name, created_str
            ])
        return headers, rows

    async def _export_users(self, params: ExportFilterParams) -> tuple[list[str], list[list[Any]]]:
        from app.identity.models import UserAccount
        stmt = select(UserAccount).options(selectinload(UserAccount.employee), selectinload(UserAccount.roles)).order_by(UserAccount.created_at.desc())
        result = await self.session.execute(stmt)
        users = result.scalars().all()

        headers = ["ID", "E-mail", "Nome Colaborador", "Perfis", "É Administrador", "Data Cadastro"]
        rows = []
        for u in users:
            emp_name = u.employee.name if u.employee else "Sem vínculo"
            roles_str = ", ".join(r.name for r in u.roles) if u.roles else "Sem perfil"
            dt_str = u.created_at.strftime("%d/%m/%Y %H:%M:%S") if u.created_at else ""
            rows.append([
                str(u.id), u.email, emp_name, roles_str, "Sim" if u.is_admin else "Não", dt_str
            ])
        return headers, rows

    async def _export_employees(self, params: ExportFilterParams) -> tuple[list[str], list[list[Any]]]:
        from app.organization.models import Employee
        stmt = select(Employee).options(selectinload(Employee.unit), selectinload(Employee.sector)).order_by(Employee.name.asc())
        result = await self.session.execute(stmt)
        employees = result.scalars().all()

        headers = ["ID", "Nome", "Matrícula", "Cargo", "Status", "Unidade", "Setor"]
        rows = []
        for e in employees:
            unit_name = e.unit.name if e.unit else ""
            sec_name = e.sector.name if e.sector else ""
            rows.append([
                str(e.id), e.name, e.registration_number, e.position or "", e.status, unit_name, sec_name
            ])
        return headers, rows

    async def _export_categories(self, params: ExportFilterParams) -> tuple[list[str], list[list[Any]]]:
        from app.service_desk.models import TicketCategory
        stmt = select(TicketCategory).order_by(TicketCategory.name.asc())
        result = await self.session.execute(stmt)
        categories = result.scalars().all()

        headers = ["ID", "Nome", "Descrição", "Ativo", "Pré-requisitos Cadastrados"]
        rows = []
        for c in categories:
            fields_count = len(c.form_schema) if c.form_schema else 0
            rows.append([
                str(c.id), c.name, c.description or "", "Sim" if c.is_active else "Não", fields_count
            ])
        return headers, rows

    async def _export_stock_items(self, params: ExportFilterParams) -> tuple[list[str], list[list[Any]]]:
        from app.stock.models import StockItem
        stmt = select(StockItem).options(selectinload(StockItem.category), selectinload(StockItem.unit)).order_by(StockItem.name.asc())
        result = await self.session.execute(stmt)
        items = result.scalars().all()

        headers = ["ID", "Nome", "Descrição", "Categoria", "Unidade", "Saldo Atual", "Estoque Mínimo"]
        rows = []
        for i in items:
            cat_name = i.category.name if i.category else "Sem Categoria"
            unit_name = i.unit.name if i.unit else ""
            rows.append([
                str(i.id), i.name, i.description or "", cat_name, unit_name, i.quantity, i.min_quantity
            ])
        return headers, rows

    async def _export_units(self, params: ExportFilterParams) -> tuple[list[str], list[list[Any]]]:
        from app.organization.models import Unit
        stmt = select(Unit).order_by(Unit.name.asc())
        result = await self.session.execute(stmt)
        units = result.scalars().all()

        headers = ["ID", "Nome", "Código", "Tipo", "Endereço"]
        rows = []
        for u in units:
            rows.append([str(u.id), u.name, u.code, u.type, u.address or ""])
        return headers, rows

    async def _export_sectors(self, params: ExportFilterParams) -> tuple[list[str], list[list[Any]]]:
        from app.organization.models import Sector
        stmt = select(Sector).options(selectinload(Sector.unit)).order_by(Sector.name.asc())
        result = await self.session.execute(stmt)
        sectors = result.scalars().all()

        headers = ["ID", "Nome", "Código", "Unidade"]
        rows = []
        for s in sectors:
            unit_name = s.unit.name if s.unit else ""
            rows.append([str(s.id), s.name, s.code, unit_name])
        return headers, rows
