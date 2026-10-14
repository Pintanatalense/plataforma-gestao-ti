"""
MOD-13 — Data Transfer (Import Service)

Importação de dados em CSV com:
- Análise de cabeçalhos e detecção de delimitador (, ou ;)
- Sugestão inteligente de mapeamento
- Pré-visualização das primeiras linhas
- Execução transacional com validação de chaves e integridade referencial
- Relatório detalhado de sucessos, falhas e linhas rejeitadas
"""

import csv
import io
import uuid
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleException
from app.data_transfer.schemas import (
    ImportAnalyzeResponse,
    ImportExecuteResponse,
    ImportErrorDetail,
)


class DataImportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def analyze_csv(self, content_str: str, filename: str) -> ImportAnalyzeResponse:
        """Analisa o arquivo CSV enviado, detecta delimitador e retorna prévia."""
        # Remove eventual BOM
        if content_str.startswith("\ufeff"):
            content_str = content_str[1:]

        # Detectar delimitador
        first_line = content_str.split("\n")[0] if content_str else ""
        delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","

        reader = csv.reader(io.StringIO(content_str), delimiter=delimiter)
        try:
            headers = next(reader)
        except StopIteration:
            raise BusinessRuleException("O arquivo CSV enviado está vazio.")

        headers = [h.strip() for h in headers if h.strip()]
        if not headers:
            raise BusinessRuleException("Não foi possível identificar os cabeçalhos do CSV.")

        preview_rows: list[dict[str, str]] = []
        total_estimate = 0
        for i, row in enumerate(reader):
            total_estimate += 1
            if i < 5:
                row_dict = {}
                for idx, h in enumerate(headers):
                    row_dict[h] = row[idx].strip() if idx < len(row) else ""
                preview_rows.append(row_dict)

        # Sugestão de mapeamento automático
        suggested = self._suggest_mappings(headers)

        return ImportAnalyzeResponse(
            filename=filename,
            detected_delimiter=delimiter,
            total_rows_estimate=total_estimate,
            headers=headers,
            preview_rows=preview_rows,
            suggested_mappings=suggested,
        )

    def _suggest_mappings(self, headers: list[str]) -> dict[str, str]:
        mapping: dict[str, str] = {}
        alias_map = {
            "name": ["nome", "name", "titulo", "descrição", "categoria"],
            "description": ["descricao", "description", "obs", "observacoes"],
            "registration_number": ["matricula", "registro", "codigo_colaborador", "registration_number"],
            "position": ["cargo", "funcao", "posicao", "position"],
            "unit_code": ["unidade", "codigo_unidade", "unit_code", "unit"],
            "sector_code": ["setor", "codigo_setor", "sector_code", "sector"],
            "quantity": ["quantidade", "saldo", "qtd", "quantity"],
            "min_quantity": ["minimo", "estoque_minimo", "min_quantity"],
            "code": ["codigo", "code", "sigla"],
        }
        for field, aliases in alias_map.items():
            for h in headers:
                h_norm = h.lower().replace("_", "").replace(" ", "").replace("-", "")
                for alias in aliases:
                    alias_norm = alias.replace("_", "").replace(" ", "")
                    if alias_norm in h_norm or h_norm in alias_norm:
                        mapping[field] = h
                        break
                if field in mapping:
                    break
        return mapping

    async def execute_import(
        self,
        content_str: str,
        entity: str,
        column_mapping: dict[str, str],
        delimiter: str = ";"
    ) -> ImportExecuteResponse:
        """Executa a importação dos registros de forma transacional e segura."""
        if content_str.startswith("\ufeff"):
            content_str = content_str[1:]

        reader = csv.reader(io.StringIO(content_str), delimiter=delimiter)
        try:
            headers = [h.strip() for h in next(reader)]
        except StopIteration:
            raise BusinessRuleException("O arquivo CSV está vazio.")

        header_indices = {h: idx for idx, h in enumerate(headers)}
        entity_lower = entity.lower()

        if entity_lower == "categories":
            return await self._import_categories(reader, header_indices, column_mapping)
        elif entity_lower == "units":
            return await self._import_units(reader, header_indices, column_mapping)
        elif entity_lower == "sectors":
            return await self._import_sectors(reader, header_indices, column_mapping)
        elif entity_lower == "employees":
            return await self._import_employees(reader, header_indices, column_mapping)
        elif entity_lower == "stock_items":
            return await self._import_stock_items(reader, header_indices, column_mapping)
        else:
            raise BusinessRuleException(f"Importação para a entidade '{entity}' não é suportada.")

    async def _import_categories(
        self, reader, header_indices: dict[str, int], mapping: dict[str, str]
    ) -> ImportExecuteResponse:
        from app.service_desk.models import TicketCategory

        name_col = mapping.get("name")
        desc_col = mapping.get("description")
        if not name_col or name_col not in header_indices:
            raise BusinessRuleException("Mapeamento da coluna obrigatória 'name' (Nome da Categoria) não configurado.")

        name_idx = header_indices[name_col]
        desc_idx = header_indices.get(desc_col) if desc_col else None

        # Carregar existentes para evitar duplicidade
        stmt = select(TicketCategory.name)
        existing_names = set((await self.session.execute(stmt)).scalars().all())

        success_count = 0
        rejected_lines: list[ImportErrorDetail] = []
        line_num = 1

        for row in reader:
            line_num += 1
            if not row or not any(row):
                continue

            name_val = row[name_idx].strip() if name_idx < len(row) else ""
            if not name_val:
                rejected_lines.append(ImportErrorDetail(
                    line_number=line_num, raw_data={"row": row}, error_message="Nome da categoria vazio."
                ))
                continue

            if name_val in existing_names:
                rejected_lines.append(ImportErrorDetail(
                    line_number=line_num, raw_data={"row": row}, error_message=f"Categoria '{name_val}' já existe no sistema."
                ))
                continue

            desc_val = row[desc_idx].strip() if (desc_idx is not None and desc_idx < len(row)) else None
            cat = TicketCategory(name=name_val, description=desc_val, is_active=True)
            self.session.add(cat)
            existing_names.add(name_val)
            success_count += 1

        await self.session.commit()
        return ImportExecuteResponse(
            entity="categories",
            total_rows=line_num - 1,
            success_count=success_count,
            error_count=len(rejected_lines),
            rejected_lines=rejected_lines,
            summary_message=f"{success_count} categoria(s) importada(s) com sucesso. {len(rejected_lines)} linha(s) rejeitada(s)."
        )

    async def _import_units(
        self, reader, header_indices: dict[str, int], mapping: dict[str, str]
    ) -> ImportExecuteResponse:
        from app.organization.models import Company, Unit

        name_col = mapping.get("name")
        code_col = mapping.get("code")
        if not name_col or not code_col:
            raise BusinessRuleException("Campos 'name' e 'code' são obrigatórios para importar unidades.")

        name_idx = header_indices[name_col]
        code_idx = header_indices[code_col]

        stmt_comp = select(Company.id).limit(1)
        comp_id = (await self.session.execute(stmt_comp)).scalar_one_or_none()
        if not comp_id:
            raise BusinessRuleException("Nenhuma empresa cadastrada para vincular as unidades.")

        stmt = select(Unit.code)
        existing_codes = set((await self.session.execute(stmt)).scalars().all())

        success_count = 0
        rejected_lines: list[ImportErrorDetail] = []
        line_num = 1

        for row in reader:
            line_num += 1
            if not row or not any(row):
                continue
            name_val = row[name_idx].strip() if name_idx < len(row) else ""
            code_val = row[code_idx].strip() if code_idx < len(row) else ""

            if not name_val or not code_val:
                rejected_lines.append(ImportErrorDetail(
                    line_number=line_num, raw_data={"row": row}, error_message="Nome ou Código da unidade ausente."
                ))
                continue

            if code_val in existing_codes:
                rejected_lines.append(ImportErrorDetail(
                    line_number=line_num, raw_data={"row": row}, error_message=f"Código de unidade '{code_val}' já existe."
                ))
                continue

            unit = Unit(company_id=comp_id, name=name_val, code=code_val, type="FILIAL")
            self.session.add(unit)
            existing_codes.add(code_val)
            success_count += 1

        await self.session.commit()
        return ImportExecuteResponse(
            entity="units",
            total_rows=line_num - 1,
            success_count=success_count,
            error_count=len(rejected_lines),
            rejected_lines=rejected_lines,
            summary_message=f"{success_count} unidade(s) importada(s) com sucesso. {len(rejected_lines)} rejeitada(s)."
        )

    async def _import_sectors(
        self, reader, header_indices: dict[str, int], mapping: dict[str, str]
    ) -> ImportExecuteResponse:
        from app.organization.models import Unit, Sector

        name_col = mapping.get("name")
        code_col = mapping.get("code")
        unit_col = mapping.get("unit_code")
        if not name_col or not code_col or not unit_col:
            raise BusinessRuleException("Campos 'name', 'code' e 'unit_code' são obrigatórios para importar setores.")

        name_idx = header_indices[name_col]
        code_idx = header_indices[code_col]
        unit_idx = header_indices[unit_col]

        stmt_units = select(Unit)
        units_by_code = {u.code: u.id for u in (await self.session.execute(stmt_units)).scalars().all()}

        stmt_sec = select(Sector.code)
        existing_codes = set((await self.session.execute(stmt_sec)).scalars().all())

        success_count = 0
        rejected_lines: list[ImportErrorDetail] = []
        line_num = 1

        for row in reader:
            line_num += 1
            if not row or not any(row):
                continue
            name_val = row[name_idx].strip() if name_idx < len(row) else ""
            code_val = row[code_idx].strip() if code_idx < len(row) else ""
            unit_val = row[unit_idx].strip() if unit_idx < len(row) else ""

            if not name_val or not code_val:
                rejected_lines.append(ImportErrorDetail(
                    line_number=line_num, raw_data={"row": row}, error_message="Nome ou Código de setor ausente."
                ))
                continue

            if code_val in existing_codes:
                rejected_lines.append(ImportErrorDetail(
                    line_number=line_num, raw_data={"row": row}, error_message=f"Código de setor '{code_val}' já existe."
                ))
                continue

            if unit_val not in units_by_code:
                rejected_lines.append(ImportErrorDetail(
                    line_number=line_num, raw_data={"row": row}, error_message=f"Unidade '{unit_val}' não encontrada."
                ))
                continue

            sec = Sector(name=name_val, code=code_val, unit_id=units_by_code[unit_val])
            self.session.add(sec)
            existing_codes.add(code_val)
            success_count += 1

        await self.session.commit()
        return ImportExecuteResponse(
            entity="sectors",
            total_rows=line_num - 1,
            success_count=success_count,
            error_count=len(rejected_lines),
            rejected_lines=rejected_lines,
            summary_message=f"{success_count} setor(es) importado(s) com sucesso. {len(rejected_lines)} rejeitado(s)."
        )

    async def _import_employees(
        self, reader, header_indices: dict[str, int], mapping: dict[str, str]
    ) -> ImportExecuteResponse:
        from app.organization.models import Unit, Sector, Employee

        name_col = mapping.get("name")
        reg_col = mapping.get("registration_number")
        unit_col = mapping.get("unit_code")
        sec_col = mapping.get("sector_code")
        pos_col = mapping.get("position")

        if not name_col or not reg_col or not unit_col or not sec_col:
            raise BusinessRuleException("Campos 'name', 'registration_number', 'unit_code' e 'sector_code' são obrigatórios.")

        name_idx = header_indices[name_col]
        reg_idx = header_indices[reg_col]
        unit_idx = header_indices[unit_col]
        sec_idx = header_indices[sec_col]
        pos_idx = header_indices.get(pos_col) if pos_col else None

        stmt_units = select(Unit)
        units_by_code = {u.code: u.id for u in (await self.session.execute(stmt_units)).scalars().all()}

        stmt_sec = select(Sector)
        sectors_by_code = {s.code: s.id for s in (await self.session.execute(stmt_sec)).scalars().all()}

        stmt_emp = select(Employee.registration_number)
        existing_regs = set((await self.session.execute(stmt_emp)).scalars().all())

        success_count = 0
        rejected_lines: list[ImportErrorDetail] = []
        line_num = 1

        for row in reader:
            line_num += 1
            if not row or not any(row):
                continue

            name_val = row[name_idx].strip() if name_idx < len(row) else ""
            reg_val = row[reg_idx].strip() if reg_idx < len(row) else ""
            unit_val = row[unit_idx].strip() if unit_idx < len(row) else ""
            sec_val = row[sec_idx].strip() if sec_idx < len(row) else ""
            pos_val = row[pos_idx].strip() if (pos_idx is not None and pos_idx < len(row)) else ""

            if not name_val or not reg_val:
                rejected_lines.append(ImportErrorDetail(
                    line_number=line_num, raw_data={"row": row}, error_message="Nome ou Matrícula em branco."
                ))
                continue

            if reg_val in existing_regs:
                rejected_lines.append(ImportErrorDetail(
                    line_number=line_num, raw_data={"row": row}, error_message=f"Matrícula '{reg_val}' já cadastrada."
                ))
                continue

            if unit_val not in units_by_code:
                rejected_lines.append(ImportErrorDetail(
                    line_number=line_num, raw_data={"row": row}, error_message=f"Unidade '{unit_val}' não encontrada."
                ))
                continue

            if sec_val not in sectors_by_code:
                rejected_lines.append(ImportErrorDetail(
                    line_number=line_num, raw_data={"row": row}, error_message=f"Setor '{sec_val}' não encontrado."
                ))
                continue

            emp = Employee(
                name=name_val,
                registration_number=reg_val,
                unit_id=units_by_code[unit_val],
                sector_id=sectors_by_code[sec_val],
                position=pos_val or None,
                status="ATIVO"
            )
            self.session.add(emp)
            existing_regs.add(reg_val)
            success_count += 1

        await self.session.commit()
        return ImportExecuteResponse(
            entity="employees",
            total_rows=line_num - 1,
            success_count=success_count,
            error_count=len(rejected_lines),
            rejected_lines=rejected_lines,
            summary_message=f"{success_count} colaborador(es) importado(s) com sucesso. {len(rejected_lines)} rejeitado(s)."
        )

    async def _import_stock_items(
        self, reader, header_indices: dict[str, int], mapping: dict[str, str]
    ) -> ImportExecuteResponse:
        from app.organization.models import Unit
        from app.stock.models import StockItem

        name_col = mapping.get("name")
        unit_col = mapping.get("unit_code")
        qtd_col = mapping.get("quantity")
        min_col = mapping.get("min_quantity")
        desc_col = mapping.get("description")

        if not name_col or not unit_col:
            raise BusinessRuleException("Campos 'name' e 'unit_code' são obrigatórios para importar itens de estoque.")

        name_idx = header_indices[name_col]
        unit_idx = header_indices[unit_col]
        qtd_idx = header_indices.get(qtd_col) if qtd_col else None
        min_idx = header_indices.get(min_col) if min_col else None
        desc_idx = header_indices.get(desc_col) if desc_col else None

        stmt_units = select(Unit)
        units_by_code = {u.code: u.id for u in (await self.session.execute(stmt_units)).scalars().all()}

        success_count = 0
        rejected_lines: list[ImportErrorDetail] = []
        line_num = 1

        for row in reader:
            line_num += 1
            if not row or not any(row):
                continue

            name_val = row[name_idx].strip() if name_idx < len(row) else ""
            unit_val = row[unit_idx].strip() if unit_idx < len(row) else ""

            if not name_val:
                rejected_lines.append(ImportErrorDetail(
                    line_number=line_num, raw_data={"row": row}, error_message="Nome do item em branco."
                ))
                continue

            if unit_val not in units_by_code:
                rejected_lines.append(ImportErrorDetail(
                    line_number=line_num, raw_data={"row": row}, error_message=f"Unidade '{unit_val}' não encontrada."
                ))
                continue

            qty = 0
            if qtd_idx is not None and qtd_idx < len(row):
                try:
                    qty = int(row[qtd_idx].strip() or 0)
                except ValueError:
                    qty = 0

            min_qty = 0
            if min_idx is not None and min_idx < len(row):
                try:
                    min_qty = int(row[min_idx].strip() or 0)
                except ValueError:
                    min_qty = 0

            desc_val = row[desc_idx].strip() if (desc_idx is not None and desc_idx < len(row)) else None

            item = StockItem(
                name=name_val,
                unit_id=units_by_code[unit_val],
                quantity=qty,
                min_quantity=min_qty,
                description=desc_val,
            )
            self.session.add(item)
            success_count += 1

        await self.session.commit()
        return ImportExecuteResponse(
            entity="stock_items",
            total_rows=line_num - 1,
            success_count=success_count,
            error_count=len(rejected_lines),
            rejected_lines=rejected_lines,
            summary_message=f"{success_count} item(ns) de estoque importado(s) com sucesso. {len(rejected_lines)} rejeitado(s)."
        )
