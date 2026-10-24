"""
Configurações da aplicação via variáveis de ambiente.

Utiliza pydantic-settings para validação e tipagem das configurações.
Todas as variáveis podem ser definidas via .env ou variáveis de ambiente do sistema.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
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
    APP_VERSION: str = "0.1.1"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    API_V1_PREFIX: str = "/api/v1"

    # --- Banco de Dados ---
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/gestao_ti"
    DATABASE_ECHO: bool = False

    # --- Segurança ---
    # Obrigatória (sem padrão): gere com `openssl rand -hex 32`.
    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 8
    # Chave Fernet que cifra segredos de canais (senha SMTP, tokens). Obrigatória:
    # `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
    # Guarde-a fora do banco e do backup do banco: sem ela os segredos não podem ser lidos.
    APP_ENCRYPTION_KEY: str

    # --- Notificações ---
    APP_TIMEZONE: str = "America/Fortaleza"
    # WhatsApp pela Evolution API (ADR-019). Endereço e chave vêm do servidor, nunca da tela: o administrador
    # não escolhe para onde o backend manda requisições. Sem EVOLUTION_API_KEY o provedor fica indisponível.
    EVOLUTION_BASE_URL: str = "http://evolution:8080"
    EVOLUTION_API_KEY: str = ""

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

    # --- Arquivos públicos (logomarca) ---
    STATIC_DIR: str | None = None  # padrão: backend/static (no container: /app/static)

    # --- Segurança operacional ---
    # Carga de QA cria o usuário admin@teste.local com senha conhecida: nunca ligar em produção.
    ENABLE_QA_SEED: bool = False
    # Swagger/ReDoc/openapi.json. Em produção exposta à internet, desligue.
    ENABLE_API_DOCS: bool = True

    # --- Chamados ---
    TICKET_REOPEN_DAYS: int = 3

    # --- Backups ---
    BACKUP_STORAGE_PATH: str = "/data/backups"
    BACKUP_RETENTION_DAYS: int = 30
    BACKUP_MAX_KEEP: int = 15

    # --- CORS ---
    CORS_ORIGINS: list[str] = ["http://localhost:4200"]

    @field_validator("SECRET_KEY")
    @classmethod
    def _reject_weak_secret_key(cls, value: str) -> str:
        """Impede subir com chave de exemplo ou curta (tokens JWT seriam forjáveis)."""
        if len(value) < 32 or "change-me" in value.lower():
            raise ValueError(
                "SECRET_KEY inválida: use um valor aleatório com pelo menos 32 caracteres "
                "(ex.: openssl rand -hex 32) e sem o texto 'CHANGE-ME'."
            )
        return value

    @field_validator("APP_ENCRYPTION_KEY")
    @classmethod
    def _validate_encryption_key(cls, value: str) -> str:
        from cryptography.fernet import Fernet

        try:
            Fernet(value.encode())
        except Exception as exc:
            raise ValueError(
                "APP_ENCRYPTION_KEY inválida: gere com "
                "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`."
            ) from exc
        return value

    @property
    def attachment_max_size_bytes(self) -> int:
        """Tamanho máximo de anexo em bytes."""
        return self.ATTACHMENT_MAX_SIZE_MB * 1024 * 1024

    @property
    def static_dir(self) -> Path:
        """Diretório dos arquivos públicos servidos em /static."""
        return Path(self.STATIC_DIR) if self.STATIC_DIR else Path(__file__).resolve().parent.parent / "static"

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
