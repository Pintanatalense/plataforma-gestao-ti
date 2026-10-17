"""Garante que o histórico do Alembic tenha uma única cabeça (instalação limpa sobe)."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_has_single_head() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, f"Múltiplas cabeças no Alembic: {heads}"
