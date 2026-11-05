"""
MOD-14 — Backups do Banco de Dados (Services)

Geração, verificação de integridade (SHA-256), download e política de retenção de backups.

Cada backup tem duas partes (Plano de Evolução, Fase 0 PR 13; S10):
- ``backup_gestao_ti_<data>.sql.gz``: o banco inteiro (inclui o schema da Evolution);
- ``arquivos_gestao_ti_<data>.tar.gz``: anexos (``data/attachments``) e logomarca (``app/static``), no mesmo
  formato que ``scripts/restore-backup.sh`` aceita. Só os ``BACKUP_FILES_MAX_KEEP`` backups mais recentes guardam
  esta parte (anexos ocupam espaço); os mais antigos ficam só com o banco.
O ``.env`` (senhas e APP_ENCRYPTION_KEY) NUNCA entra aqui: ``scripts/backup-secrets.sh`` faz a cópia cifrada à parte.
"""

import asyncio
import gzip
import hashlib
import logging
import os
import shutil
import tarfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import NotFoundException, BusinessRuleException
from app.backup.models import DatabaseBackup

logger = logging.getLogger(__name__)
settings = get_settings()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_files_archive(target: Path) -> tuple[int, str, int]:
    """Empacota anexos e logomarca (sem links simbólicos). Retorna (bytes, SHA-256, arquivos incluídos)."""
    count = 0

    def _only_regular(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        nonlocal count
        if info.issym() or info.islnk() or not (info.isfile() or info.isdir()):
            return None
        if info.isfile():
            count += 1
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        return info

    with tarfile.open(target, "w:gz", compresslevel=6) as tar:
        for arcname, root in (("data/attachments", settings.attachment_storage_dir), ("app/static", settings.static_dir)):
            if root.is_dir():
                tar.add(str(root), arcname=arcname, filter=_only_regular)
    return target.stat().st_size, _sha256_file(target), count


class BackupService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.storage_dir = settings.backup_storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    async def list_backups(self) -> list[DatabaseBackup]:
        stmt = select(DatabaseBackup).order_by(DatabaseBackup.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_backup(self, backup_id: uuid.UUID) -> DatabaseBackup:
        stmt = select(DatabaseBackup).where(DatabaseBackup.id == backup_id)
        backup = (await self.session.execute(stmt)).scalar_one_or_none()
        if not backup:
            raise NotFoundException("Backup", backup_id)
        return backup

    async def create_backup(self, user_id: uuid.UUID | None = None) -> DatabaseBackup:
        """Gera um novo backup compactado (.sql.gz) com cálculo de hash SHA-256."""
        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"backup_gestao_ti_{now_str}.sql.gz"
        file_path = self.storage_dir / filename
        files_name = f"arquivos_gestao_ti_{now_str}.tar.gz"
        files_path = self.storage_dir / files_name

        success = False
        error_msg = None

        try:
            success, raw_bytes = await self._execute_database_dump()
            if not success or not raw_bytes:
                raise RuntimeError(error_msg or "Falha ao extrair dump do banco de dados.")

            # Compactar com gzip
            compressed_bytes = gzip.compress(raw_bytes, compresslevel=6)
            with open(file_path, "wb") as f:
                f.write(compressed_bytes)

            size_bytes = len(compressed_bytes)
            checksum = hashlib.sha256(compressed_bytes).hexdigest()

            files_fields: dict = {}
            if settings.BACKUP_INCLUDE_FILES:
                files_size, files_checksum, files_count = await asyncio.to_thread(write_files_archive, files_path)
                files_fields = {
                    "files_filename": files_name,
                    "files_size_bytes": files_size,
                    "files_checksum_sha256": files_checksum,
                    "files_count": files_count,
                }

            backup = DatabaseBackup(
                filename=filename,
                size_bytes=size_bytes,
                checksum_sha256=checksum,
                status="SUCCESS",
                created_by_id=user_id,
                **files_fields,
            )
            self.session.add(backup)
            await self.session.flush()

            # Executa política de retenção
            await self._apply_retention_policy()

            await self.session.commit()
            logger.info("Backup gerado com sucesso: %s (%d bytes, SHA256: %s)", filename, size_bytes, checksum)
            return backup

        except Exception as exc:
            logger.exception("Erro ao gerar backup do banco de dados: %s", exc)
            if files_path.exists():
                files_path.unlink(missing_ok=True)
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception:
                    pass

            backup_err = DatabaseBackup(
                filename=filename,
                size_bytes=0,
                checksum_sha256="",
                status="FAILED",
                error_message=str(exc),
                created_by_id=user_id,
            )
            self.session.add(backup_err)
            await self.session.commit()
            raise BusinessRuleException(f"Não foi possível gerar o backup: {exc}") from exc

    def _get_active_db_url(self) -> str:
        try:
            bind = self.session.get_bind()
            if bind is not None and bind.url:
                # str(url) mascara a senha ("***"): o pg_dump precisaria dela em claro.
                return bind.url.render_as_string(hide_password=False)
        except Exception:
            pass
        return settings.DATABASE_URL

    async def _execute_database_dump(self) -> tuple[bool, bytes]:
        """Executa pg_dump real ou dump SQLite (em ambiente de teste), evitando backups vazios."""
        db_url = self._get_active_db_url()
        parsed = urlparse(db_url.replace("postgresql+asyncpg://", "postgresql://").replace("sqlite+aiosqlite://", "sqlite://"))

        # Cenário 1: PostgreSQL
        if "postgresql" in parsed.scheme:
            host = parsed.hostname or "localhost"
            port = str(parsed.port or 5432)
            user = parsed.username or "postgres"
            password = parsed.password or "postgres"
            dbname = parsed.path.lstrip("/") or "gestao_ti"

            env = os.environ.copy()
            env["PGPASSWORD"] = password

            # 1.a) Tenta usar o binário nativo pg_dump instalado no container ou host
            pg_dump_bin = shutil.which("pg_dump")
            if pg_dump_bin:
                cmd = [pg_dump_bin, "-h", host, "-p", port, "-U", user, "-d", dbname, "--clean", "--if-exists"]
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode == 0 and stdout:
                    return True, stdout
                detail = stderr.decode(errors="ignore").strip()
                logger.warning("pg_dump local retornou código %d: %s", proc.returncode, detail)
                raise RuntimeError(f"pg_dump falhou (código {proc.returncode}): {detail[:300]}")

            raise RuntimeError("Utilitário pg_dump não encontrado; verifique o postgresql-client na imagem.")

        # Cenário 2: SQLite (Ambiente isolado de testes automatizados)
        if "sqlite" in parsed.scheme:
            sqlite_path = parsed.path.lstrip("/")
            dump_lines = [
                "-- DUMP SQLITE - PLATAFORMA DE GESTÃO DE TI",
                f"-- Gerado em: {datetime.now(timezone.utc).isoformat()}",
                "PRAGMA foreign_keys=OFF;",
                "BEGIN TRANSACTION;",
            ]
            if os.path.exists(sqlite_path):
                import sqlite3
                con = sqlite3.connect(sqlite_path)
                for line in con.iterdump():
                    dump_lines.append(line)
                con.close()
            dump_lines.append("COMMIT;")
            return True, "\n".join(dump_lines).encode("utf-8")

        raise RuntimeError(f"Engine de banco de dados não suportado para dump: {parsed.scheme}")

    async def validate_backup_integrity(self, backup_id: uuid.UUID) -> dict:
        """Verifica se o arquivo existe fisicamente e se seu hash SHA-256 confere com o registrado."""
        backup = await self.get_backup(backup_id)
        target_file = self.storage_dir / backup.filename

        if not target_file.exists():
            return {
                "backup_id": str(backup.id),
                "filename": backup.filename,
                "exists": False,
                "is_valid": False,
                "error": "Arquivo físico não encontrado no disco."
            }

        with open(target_file, "rb") as f:
            content = f.read()

        current_hash = hashlib.sha256(content).hexdigest()
        is_valid = (current_hash == backup.checksum_sha256)
        result = {
            "backup_id": str(backup.id),
            "filename": backup.filename,
            "exists": True,
            "is_valid": is_valid,
            "expected_sha256": backup.checksum_sha256,
            "calculated_sha256": current_hash,
            "size_bytes": len(content)
        }
        if backup.files_filename:
            files_file = self.storage_dir / backup.files_filename
            files_ok = files_file.exists() and _sha256_file(files_file) == backup.files_checksum_sha256
            result.update(files_filename=backup.files_filename, files_valid=files_ok, is_valid=is_valid and files_ok)
            if not files_ok:
                result["error"] = "O pacote de anexos e logomarca não existe ou não confere com o SHA-256 registrado."
        return result

    async def get_recent_valid_backup(self, max_age_hours: int = 24) -> tuple[bool, DatabaseBackup | None]:
        """Verifica se existe ao menos um backup com status SUCCESS gerado nas últimas N horas."""
        stmt = (
            select(DatabaseBackup)
            .where(DatabaseBackup.status == "SUCCESS")
            .order_by(DatabaseBackup.created_at.desc())
        )
        result = await self.session.execute(stmt)
        latest = result.scalars().first()

        if not latest:
            return False, None

        age = datetime.now(timezone.utc) - latest.created_at.replace(tzinfo=timezone.utc) if latest.created_at.tzinfo is None else datetime.now(timezone.utc) - latest.created_at
        if age.total_seconds() > (max_age_hours * 3600):
            return False, latest

        integrity = await self.validate_backup_integrity(latest.id)
        if not integrity["is_valid"]:
            return False, latest

        return True, latest

    async def _apply_retention_policy(self) -> None:
        """Mantém apenas a quantidade máxima estipulada em configurações (default 15)."""
        stmt = (
            select(DatabaseBackup)
            .where(DatabaseBackup.status == "SUCCESS")
            .order_by(DatabaseBackup.created_at.desc())
        )
        backups = list((await self.session.execute(stmt)).scalars().all())

        # anexos e logo só nos mais recentes (ocupam espaço); o banco continua nos BACKUP_MAX_KEEP
        for old_b in backups[max(settings.BACKUP_FILES_MAX_KEEP, 1):]:
            self._drop_files_archive(old_b)

        max_keep = settings.BACKUP_MAX_KEEP
        if len(backups) > max_keep:
            to_remove = backups[max_keep:]
            for old_b in to_remove:
                old_file = self.storage_dir / old_b.filename
                if old_file.exists():
                    try:
                        old_file.unlink()
                    except Exception:
                        pass
                self._drop_files_archive(old_b)
                await self.session.delete(old_b)
            logger.info("Política de retenção removeu %d backups antigos.", len(to_remove))

    def _drop_files_archive(self, backup: DatabaseBackup) -> None:
        if not backup.files_filename:
            return
        (self.storage_dir / backup.files_filename).unlink(missing_ok=True)
        backup.files_filename = backup.files_checksum_sha256 = None
        backup.files_size_bytes = backup.files_count = None

    async def delete_backup(self, backup_id: uuid.UUID) -> None:
        backup = await self.get_backup(backup_id)
        target_file = self.storage_dir / backup.filename
        if target_file.exists():
            try:
                target_file.unlink()
            except Exception:
                pass
        self._drop_files_archive(backup)
        await self.session.delete(backup)
        await self.session.commit()
