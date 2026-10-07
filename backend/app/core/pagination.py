"""
Esquemas de paginação reutilizáveis para toda a aplicação.

Fornece PaginatedResponse genérico e parâmetros de paginação como dependency.
"""

from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Parâmetros de paginação extraídos da query string."""

    page: int = Field(default=1, ge=1, description="Número da página (1-indexed)")
    page_size: int = Field(default=20, ge=1, le=100, description="Itens por página")

    @property
    def offset(self) -> int:
        """Calcula o offset para a query SQL."""
        return (self.page - 1) * self.page_size


def get_pagination_params(
    page: int = Query(default=1, ge=1, description="Número da página"),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize", description="Itens por página"),
) -> PaginationParams:
    """Dependency injection para parâmetros de paginação nos routers."""
    return PaginationParams(page=page, page_size=page_size)


class PaginatedResponse(BaseModel, Generic[T]):
    """
    Resposta paginada genérica.

    Uso:
        @router.get("/items", response_model=PaginatedResponse[ItemOut])
        async def list_items(...):
            return PaginatedResponse(
                items=items,
                total=total,
                page=params.page,
                page_size=params.page_size,
            )
    """

    items: list[T]
    total: int = Field(description="Total de registros")
    page: int = Field(description="Página atual")
    page_size: int = Field(description="Itens por página")

    @property
    def total_pages(self) -> int:
        """Total de páginas calculado."""
        if self.page_size == 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size

    @property
    def has_next(self) -> bool:
        """Indica se existe próxima página."""
        return self.page < self.total_pages

    @property
    def has_previous(self) -> bool:
        """Indica se existe página anterior."""
        return self.page > 1
