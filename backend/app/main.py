"""
Ponto de entrada da aplicação FastAPI.

Responsabilidades:
- Criação da app via factory pattern
- Montagem de routers de todos os módulos
- Registro de exception handlers
- Configuração de CORS
- Endpoint de healthcheck
"""

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.database import engine, AsyncSessionLocal
from app.audit.listener import setup_audit_listener

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Gerencia o ciclo de vida da aplicação."""
    logger.info("Iniciando %s v%s", settings.APP_NAME, settings.APP_VERSION)

    # Verificar conexão com o banco
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))
        logger.info("Conexão com banco de dados estabelecida")

    setup_audit_listener()

    yield

    # Shutdown
    await engine.dispose()
    logger.info("Aplicação encerrada")


def create_app() -> FastAPI:
    """Factory da aplicação FastAPI."""

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs_url=f"{settings.API_V1_PREFIX}/docs",
        redoc_url=f"{settings.API_V1_PREFIX}/redoc",
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        lifespan=lifespan,
    )

    # --- CORS ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    import os
    static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
    if not os.path.exists(static_dir):
        os.makedirs(static_dir)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # --- Exception Handlers ---
    register_exception_handlers(app)

    # --- Routers ---
    _mount_routers(app)

    return app


def _mount_routers(app: FastAPI) -> None:
    """
    Monta os routers de todos os módulos.

    Cada módulo é montado sob seu prefixo em /api/v1/.
    Novos módulos devem ser adicionados aqui conforme são desenvolvidos.
    """
    prefix = settings.API_V1_PREFIX

    # --- Healthcheck (sempre disponível) ---
    @app.get(
        f"{prefix}/health",
        tags=["Sistema"],
        summary="Verificação de saúde da aplicação",
    )
    async def healthcheck() -> dict:
        """Retorna status de saúde da aplicação e conexão com o banco."""
        db_status = "healthy"
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            db_status = "unhealthy"

        return {
            "status": "healthy" if db_status == "healthy" else "degraded",
            "version": settings.APP_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {
                "database": db_status,
            },
        }

    # -----------------------------------------------------------------
    # Módulos — serão montados à medida que forem implementados
    # -----------------------------------------------------------------
    from app.organization.router import router as organization_router
    app.include_router(organization_router, prefix=prefix)

    from app.identity.router import router as identity_router
    app.include_router(identity_router, prefix=prefix)

    from app.service_desk.router import router as service_desk_router
    app.include_router(service_desk_router, prefix=f"{prefix}/tickets", tags=["Service Desk"])

    from app.assets.router import router as assets_router
    app.include_router(assets_router, prefix=f"{prefix}/assets", tags=["Ativos"])

    from app.movements.router import router as movements_router
    app.include_router(movements_router, prefix=f"{prefix}/movements", tags=["Movimentações"])

    from app.stock.router import router as stock_router
    app.include_router(stock_router, prefix=f"{prefix}/stock", tags=["Estoque"])

    from app.inventory_audit.router import router as inventory_router
    app.include_router(inventory_router, prefix=f"{prefix}/inventory")

    # from app.access_control.router import router as access_control_router
    # app.include_router(access_control_router, prefix=f"{prefix}/accounts", tags=["Contas e Acessos"])

    from app.attachments.router import router as attachments_router
    app.include_router(attachments_router, prefix=f"{prefix}")

    from app.notifications.router import router as notifications_router
    app.include_router(notifications_router, prefix=prefix)

    from app.audit.router import router as audit_router
    app.include_router(audit_router, prefix=prefix)

    from app.data_transfer.router import router as data_transfer_router
    app.include_router(data_transfer_router, prefix=prefix)

    from app.backup.router import router as backup_router
    app.include_router(backup_router, prefix=prefix)

    from app.whatsapp.router import router as whatsapp_router
    app.include_router(whatsapp_router, prefix=prefix)


# Instância da aplicação
app = create_app()
