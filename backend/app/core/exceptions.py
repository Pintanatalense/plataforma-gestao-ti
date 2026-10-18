"""
Hierarquia de exceções da aplicação e handlers para FastAPI.

Cada módulo pode definir suas próprias exceções herdando de AppException.
Os handlers convertem exceções em respostas HTTP padronizadas.
"""

from typing import Any

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


# =============================================================================
# Exceções Base
# =============================================================================


class AppException(Exception):
    """
    Exceção base da aplicação.

    Todas as exceções de negócio devem herdar desta classe.
    """

    def __init__(
        self,
        message: str,
        code: str = "APP_ERROR",
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class NotFoundException(AppException):
    """Recurso não encontrado."""

    def __init__(self, entity: str, identifier: Any) -> None:
        super().__init__(
            message=f"{entity} não encontrado(a): {identifier}",
            code="NOT_FOUND",
            status_code=404,
            details={"entity": entity, "identifier": str(identifier)},
        )


class ConflictException(AppException):
    """Conflito de dados (ex: registro duplicado)."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="CONFLICT",
            status_code=409,
            details=details,
        )


class ForbiddenException(AppException):
    """Acesso negado ao recurso."""

    def __init__(self, message: str = "Acesso negado") -> None:
        super().__init__(
            message=message,
            code="FORBIDDEN",
            status_code=403,
        )


class UnauthorizedException(AppException):
    """Autenticação necessária ou inválida."""

    def __init__(self, message: str = "Credenciais inválidas") -> None:
        super().__init__(
            message=message,
            code="UNAUTHORIZED",
            status_code=401,
        )


class ValidationException(AppException):
    """Erro de validação de dados de negócio."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            status_code=422,
            details=details,
        )


class BusinessRuleException(AppException):
    """Violação de regra de negócio."""

    def __init__(self, message: str, rule: str | None = None) -> None:
        super().__init__(
            message=message,
            code="BUSINESS_RULE_VIOLATION",
            status_code=400,
            details={"rule": rule} if rule else {},
        )


class StateTransitionException(AppException):
    """Transição de estado inválida."""

    def __init__(self, entity: str, current_state: str, target_state: str) -> None:
        super().__init__(
            message=f"Transição inválida para {entity}: {current_state} → {target_state}",
            code="INVALID_STATE_TRANSITION",
            status_code=400,
            details={
                "entity": entity,
                "current_state": current_state,
                "target_state": target_state,
            },
        )


# =============================================================================
# Exception Handlers para FastAPI
# =============================================================================


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handler para exceções da aplicação."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handler para exceções não tratadas — retorna erro genérico e evita vazamento de dados."""
    import logging
    logger = logging.getLogger(__name__)
    logger.exception("Unhandled Exception")
    
    # Se for uma exceção já tratada pelo framework (como 404 rotas não encontradas), 
    # mantemos seu comportamento (ou poderíamos retornar a mensagem dela limpa)
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Erro interno do servidor",
                "details": {},
            }
        },
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "HTTP_ERROR",
                "message": str(exc.detail),
                "details": {}
            }
        },
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Erro de validação nos dados enviados",
                # ctx pode conter a exceção original (ValueError de field_validator): não é serializável.
                "details": jsonable_encoder(exc.errors(), custom_encoder={Exception: str})
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Registra todos os exception handlers na aplicação FastAPI."""
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
