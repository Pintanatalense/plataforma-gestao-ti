"""
Configurações da aplicação via variáveis de ambiente.

Utiliza pydantic-settings para validação e tipagem das configurações.
Todas as variáveis podem ser definidas via .env ou variáveis de ambiente do sistema.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações globais da aplicação."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Aplicação ---
    APP_NAME: str = "Plataforma de Gestão de TI"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # --- Banco de Dados ---
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/gestao_ti"
    DATABASE_ECHO: bool = False

    # --- Segurança ---
    SECRET_KEY: str = "CHANGE-ME-IN-PRODUCTION-USE-STRONG-RANDOM-KEY"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 8

    # --- Anexos ---
    ATTACHMENT_STORAGE_PATH: str = "/data/attachments"
    ATTACHMENT_MAX_SIZE_MB: int = 100
    ATTACHMENT_ALLOWED_TYPES: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "image/jpeg",
        "image/png",
        "video/mp4",
    ]

    # --- Chamados ---
    TICKET_REOPEN_DAYS: int = 3

    # --- Backups ---
    BACKUP_STORAGE_PATH: str = "/data/backups"
    BACKUP_RETENTION_DAYS: int = 30
    BACKUP_MAX_KEEP: int = 15

    # --- CORS ---
    CORS_ORIGINS: list[str] = ["http://localhost:4200"]

    @property
    def attachment_max_size_bytes(self) -> int:
        """Tamanho máximo de anexo em bytes."""
        return self.ATTACHMENT_MAX_SIZE_MB * 1024 * 1024

    @property
    def attachment_storage_dir(self) -> Path:
        """Diretório de armazenamento de anexos como Path."""
        return Path(self.ATTACHMENT_STORAGE_PATH)

    @property
    def backup_storage_dir(self) -> Path:
        """Diretório de armazenamento de backups como Path."""
        return Path(self.BACKUP_STORAGE_PATH)


@lru_cache
def get_settings() -> Settings:
    """Retorna instância cacheada das configurações."""
    return Settings()
