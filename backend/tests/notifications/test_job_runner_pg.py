"""Agenda do worker contra PostgreSQL real (ADR-024; Plano de Evolução, Fase 0 PR 12)."""

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.identity.models import UserAccount
from app.notifications import job_runner
from app.notifications.dispatcher import Dispatcher
from app.notifications.fanout import fan_out_batch
from app.notifications.job_runner import run_due_jobs
from app.notifications.models import DomainEvent, JobRun, Notification, NotificationRule, ScheduledJob
from app.worker import jobs_loop
from tests.notifications import fake_jobs

pytestmark = [pytest.mark.pg, pytest.mark.asyncio]


@pytest.fixture
async def maker():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _past() -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=5)


async def _schedule(maker, name: str, schedule: str = "every:60") -> None:
    async with maker() as s:
        s.add(ScheduledJob(name=name, schedule=schedule, next_run_at=_past()))
        await s.commit()


async def _job(maker, name: str) -> ScheduledJob:
    async with maker() as s:
        return await s.get(ScheduledJob, name)


async def _runs(maker, name: str) -> list[JobRun]:
    async with maker() as s:
        return list((await s.execute(select(JobRun).where(JobRun.job_name == name).order_by(JobRun.started_at))).scalars())


async def _make_due(maker, name: str) -> None:
    async with maker() as s:
        (await s.get(ScheduledJob, name)).next_run_at = _past()
        await s.commit()


async def test_blocking_isolated_job_is_killed_at_max_time_with_its_children(maker, tmp_path, monkeypatch):
    pid_file = tmp_path / "neto.pid"
    monkeypatch.setenv("GTI_TEST_PID_FILE", str(pid_file))
    await _schedule(maker, "t.block")
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.1)
            ticks += 1

    tick_task = asyncio.create_task(ticker())
    started = time.monotonic()
    with patch.dict("app.notifications.jobs.JOBS", {"t.block": fake_jobs.block_forever}), \
         patch.object(job_runner, "ISOLATED_JOBS", {"t.block"}), patch.dict(job_runner.JOB_MAX_SECONDS, {"t.block": 8}):
        assert await run_due_jobs(maker) == 1
    elapsed = time.monotonic() - started
    tick_task.cancel()

    run = (await _runs(maker, "t.block"))[0]
    assert (run.status, run.isolated) == ("timeout", True) and "tempo máximo" in run.error
    assert elapsed < 25 and ticks >= 50  # o laço do worker seguiu respondendo enquanto o job travava
    if os.name == "posix":  # o neto (o "pg_dump") morreu junto
        grandchild = int(pid_file.read_text())
        await asyncio.sleep(0.5)
        with pytest.raises(ProcessLookupError):
            os.kill(grandchild, 0)
    job = await _job(maker, "t.block")
    assert (job.last_status, job.retry_attempt) == ("timeout", 1)


async def test_isolated_job_error_comes_back_from_the_subprocess_and_is_retried(maker):
    await _schedule(maker, "t.fail")
    with patch.dict("app.notifications.jobs.JOBS", {"t.fail": fake_jobs.fail_with_disk_full}), \
         patch.object(job_runner, "ISOLATED_JOBS", {"t.fail"}):
        assert await run_due_jobs(maker) == 1
    run = (await _runs(maker, "t.fail"))[0]
    assert run.status == "error" and "disco cheio" in run.error
    job = await _job(maker, "t.fail")
    wait = job.next_run_at - datetime.now(timezone.utc)
    assert job.retry_attempt == 1 and timedelta(seconds=30) < wait <= timedelta(minutes=1)


async def test_retries_back_off_then_return_to_the_normal_schedule(maker):
    async def failing(_factory):
        raise RuntimeError("serviço fora")

    await _schedule(maker, "t.flaky", "every:600")
    waits = []
    with patch.dict("app.notifications.jobs.JOBS", {"t.flaky": failing}):
        for _ in range(3):
            await _make_due(maker, "t.flaky")
            assert await run_due_jobs(maker) == 1
            job = await _job(maker, "t.flaky")
            waits.append((job.retry_attempt, round((job.next_run_at - datetime.now(timezone.utc)).total_seconds() / 60)))
    assert waits == [(1, 1), (2, 2), (0, 600)]  # 1 min, 2 min e, na 3ª falha, a agenda normal
    assert [r.attempt for r in await _runs(maker, "t.flaky")] == [1, 2, 3]


async def test_one_run_at_a_time_and_a_crashed_run_is_recovered_and_retried(maker):
    calls = []

    async def ok(_factory):
        calls.append(1)

    await _schedule(maker, "t.once")
    async with maker() as s:  # um worker que caiu deixou esta execução "running"
        s.add(JobRun(job_name="t.once", status="running", attempt=1,
                     lease_until=datetime.now(timezone.utc) + timedelta(seconds=30)))
        await s.commit()
    with patch.dict("app.notifications.jobs.JOBS", {"t.once": ok}):
        assert await run_due_jobs(maker) == 0  # ainda tem concessão: não roda em dobro
        async with maker() as s:
            run = (await s.execute(select(JobRun).where(JobRun.job_name == "t.once"))).scalar_one()
            run.lease_until = _past()  # o batimento parou: concessão venceu
            await s.commit()
        assert await run_due_jobs(maker) == 0  # vira "interrupted" e a nova tentativa vai para daqui a 1 min
        job = await _job(maker, "t.once")
        assert (job.last_status, job.retry_attempt) == ("interrupted", 1)
        await _make_due(maker, "t.once")
        assert await run_due_jobs(maker) == 1
    statuses = [(r.status, r.attempt) for r in await _runs(maker, "t.once")]
    assert statuses == [("interrupted", 1), ("ok", 2)] and calls == [1]


async def test_a_slow_job_does_not_delay_a_notification(maker):
    async def slow(_factory):
        await asyncio.sleep(600)

    async with maker() as s:
        user = UserAccount(email="u@x.y", hashed_password="x")
        s.add(user)
        await s.flush()
        s.add(NotificationRule(name="r", event_type="x.*", audience=[f"user:{user.id}"], channels=["in_app"],
                               template_code="generic"))
        s.add(ScheduledJob(name="t.slow", schedule="every:60", next_run_at=_past()))
        await s.commit()

    stop = asyncio.Event()
    with patch.dict("app.notifications.jobs.JOBS", {"t.slow": slow}):
        loop_task = asyncio.create_task(jobs_loop(stop, maker, poll_seconds=0.1))
        for _ in range(50):
            if await _runs(maker, "t.slow"):
                break
            await asyncio.sleep(0.1)
        async with maker() as s:
            s.add(DomainEvent(event_type="x.happened", entity_type="x", payload={"title": "alerta"}))
            await s.commit()
        started = time.monotonic()
        async with maker() as s:
            await fan_out_batch(s)
            await s.commit()
        await Dispatcher(maker).run_once()
        delivered_in = time.monotonic() - started
        async with maker() as s:
            notified = (await s.execute(select(Notification))).scalars().all()
        running = [r.status for r in await _runs(maker, "t.slow")]
        stop.set()
        await asyncio.wait_for(loop_task, timeout=10)
    assert len(notified) == 1 and delivered_in < 5 and running == ["running"]
