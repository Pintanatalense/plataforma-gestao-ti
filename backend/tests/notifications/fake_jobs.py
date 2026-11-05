"""Jobs de teste executados no SUBPROCESSO do worker (importados por ``--target tests.notifications.fake_jobs:...``)."""

import os
import subprocess
import time
from pathlib import Path


async def block_forever(_session_factory) -> None:
    """Trava sem ceder o laço (como um cliente síncrono preso) e deixa um neto rodando (como o pg_dump)."""
    pid_file = os.environ.get("GTI_TEST_PID_FILE")
    if pid_file and os.name == "posix":
        child = subprocess.Popen(["sleep", "300"])
        Path(pid_file).write_text(str(child.pid), encoding="utf-8")
    time.sleep(300)


async def fail_with_disk_full(_session_factory) -> None:
    raise RuntimeError("disco cheio em /data/backups")
