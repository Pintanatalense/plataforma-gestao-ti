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
    # Para onde a Evolution entrega as mensagens recebidas: o backend, pela rede do Compose (nunca pelo Nginx/internet).
    EVOLUTION_WEBHOOK_URL: str = "http://backend:8000/api/v1/integrations/whatsapp/evolution/webhook"

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
    # Swagger/ReDoc/openapi.json: desligado por padrão (mapa completo da API para quem chegar). Ligue em desenvolvimento.
    ENABLE_API_DOCS: bool = False
    # De quem o backend aceita os cabeçalhos X-Real-IP/X-Forwarded-For (o Nginx do Compose fica numa rede privada do
    # Docker). Conexão vinda de fora dessas redes usa o IP da própria conexão: o cabeçalho é ignorado.
    TRUSTED_PROXIES: str = "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

    # --- Chamados ---
    TICKET_REOPEN_DAYS: int = 3

    # --- Central de Mensagens (ADR-025): tetos contra disparo em massa (o WhatsApp tem ainda o teto por pessoa) ---
    MESSAGES_MAX_RECIPIENTS: int = 50  # por envio
    MESSAGES_MAX_PER_HOUR: int = 20  # envios por pessoa por hora (testes contam à parte: 10 por hora)
    MESSAGES_MAX_ACTIVE_SCHEDULES: int = 20  # agendamentos ativos ou pausados por pessoa
    MESSAGES_SCHEDULE_TOLERANCE_MINUTES: int = 60  # ocorrência atrasada (worker parado) ainda sai dentro deste prazo

    # --- Backups ---
    BACKUP_STORAGE_PATH: str = "/data/backups"
    BACKUP_RETENTION_DAYS: int = 30
    BACKUP_MAX_KEEP: int = 15
    # Anexos e logomarca entram no backup (pacote .tar.gz ao lado do .sql.gz), só nos N mais recentes
    BACKUP_INCLUDE_FILES: bool = True
    BACKUP_FILES_MAX_KEEP: int = 3

    # --- Auditoria (retenção por categoria; job audit.retention, que arquiva antes de apagar) ---
    AUDIT_RETENTION_SECURITY_DAYS: int = 1825  # mínimo: 5 anos
    AUDIT_RETENTION_OPERATIONAL_DAYS: int = 730

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

    @field_validator("AUDIT_RETENTION_SECURITY_DAYS")
    @classmethod
    def _security_audit_keeps_five_years(cls, value: int) -> int:
        if value < 1825:
            raise ValueError("AUDIT_RETENTION_SECURITY_DAYS: a trilha de segurança é guardada por pelo menos 1825 dias (5 anos).")
        return value

    @field_validator("AUDIT_RETENTION_OPERATIONAL_DAYS")
    @classmethod
    def _operational_audit_positive(cls, value: int) -> int:
        if value < 30:
            raise ValueError("AUDIT_RETENTION_OPERATIONAL_DAYS: mínimo de 30 dias.")
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
