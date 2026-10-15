"""
MOD-14 — Backups do Banco de Dados (Services)

Geração, verificação de integridade (SHA-256), download e política de retenção de backups.
"""

import asyncio
import gzip
import hashlib
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import NotFoundException, BusinessRuleException
from app.backup.models import DatabaseBackup

logger = logging.getLogger(__name__)
settings = get_settings()


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

            backup = DatabaseBackup(
                filename=filename,
                size_bytes=size_bytes,
                checksum_sha256=checksum,
                status="SUCCESS",
                created_by_id=user_id,
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
            raise BusinessRuleException(f"Não foi possível gerar o backup: {exc}")

    async def _execute_database_dump(self) -> tuple[bool, bytes]:
        """Executa pg_dump real ou dump SQLite (em ambiente de teste), evitando backups vazios."""
        db_url = settings.DATABASE_URL
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
                logger.warning("pg_dump local retornou código %d: %s", proc.returncode, stderr.decode(errors="ignore"))

            # 1.b) Fallback para docker exec se pg_dump não estiver no PATH local mas o container gestao-ti-db estiver acessível
            docker_bin = shutil.which("docker")
            if docker_bin:
                cmd = [docker_bin, "exec", "gestao-ti-db", "pg_dump", "-U", user, "-d", dbname, "--clean", "--if-exists"]
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await proc.communicate()
                    if proc.returncode == 0 and stdout:
                        return True, stdout
                    logger.warning("docker exec pg_dump falhou: %s", stderr.decode(errors="ignore"))
                except Exception as exc:
                    logger.debug("docker exec indisponível: %s", exc)

            raise RuntimeError("Utilitário pg_dump não encontrado e container gestao-ti-db inacessível.")

        # Cenário 2: SQLite (Ambiente isolado de testes automatizados)
        if "sqlite" in parsed.scheme:
            sqlite_path = parsed.path.lstrip("/")
            dump_lines = [
                f"-- DUMP SQLITE - PLATAFORMA DE GESTÃO DE TI",
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

        return {
            "backup_id": str(backup.id),
            "filename": backup.filename,
            "exists": True,
            "is_valid": is_valid,
            "expected_sha256": backup.checksum_sha256,
            "calculated_sha256": current_hash,
            "size_bytes": len(content)
        }

    async def restore_backup(self, backup_id: uuid.UUID) -> dict:
        """Restaura o banco de dados a partir do arquivo de backup compactado."""
        integrity = await self.validate_backup_integrity(backup_id)
        if not integrity["is_valid"]:
            raise BusinessRuleException(f"Falha de integridade no backup: {integrity.get('error', 'Hash SHA-256 divergente')}")

        backup = await self.get_backup(backup_id)
        target_file = self.storage_dir / backup.filename

        with open(target_file, "rb") as f:
            compressed_bytes = f.read()

        raw_sql = gzip.decompress(compressed_bytes)

        db_url = settings.DATABASE_URL
        parsed = urlparse(db_url.replace("postgresql+asyncpg://", "postgresql://").replace("sqlite+aiosqlite://", "sqlite://"))

        if "postgresql" in parsed.scheme:
            host = parsed.hostname or "localhost"
            port = str(parsed.port or 5432)
            user = parsed.username or "postgres"
            password = parsed.password or "postgres"
            dbname = parsed.path.lstrip("/") or "gestao_ti"

            env = os.environ.copy()
            env["PGPASSWORD"] = password

            psql_bin = shutil.which("psql")
            if psql_bin:
                cmd = [psql_bin, "-h", host, "-p", port, "-U", user, "-d", dbname]
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env
                )
                stdout, stderr = await proc.communicate(input=raw_sql)
                if proc.returncode != 0:
                    raise BusinessRuleException(f"Erro ao restaurar banco com psql: {stderr.decode(errors='ignore')}")
            else:
                docker_bin = shutil.which("docker")
                if docker_bin:
                    cmd = [docker_bin, "exec", "-i", "gestao-ti-db", "psql", "-U", user, "-d", dbname]
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await proc.communicate(input=raw_sql)
                    if proc.returncode != 0:
                        raise BusinessRuleException(f"Erro ao restaurar banco via docker exec: {stderr.decode(errors='ignore')}")
                else:
                    raise RuntimeError("Nem psql nativo nem docker foram encontrados para restauração.")

        elif "sqlite" in parsed.scheme:
            sqlite_path = parsed.path.lstrip("/")
            import sqlite3
            con = sqlite3.connect(sqlite_path)
            con.executescript(raw_sql.decode("utf-8"))
            con.close()

        logger.info("Backup %s restaurado com sucesso.", backup.filename)
        return {
            "success": True,
            "backup_id": str(backup.id),
            "filename": backup.filename,
            "restored_at": datetime.now(timezone.utc).isoformat(),
        }

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
                await self.session.delete(old_b)
            logger.info("Política de retenção removeu %d backups antigos.", len(to_remove))

    async def delete_backup(self, backup_id: uuid.UUID) -> None:
        backup = await self.get_backup(backup_id)
        target_file = self.storage_dir / backup.filename
        if target_file.exists():
            try:
                target_file.unlink()
            except Exception:
                pass
        await self.session.delete(backup)
        await self.session.commit()
