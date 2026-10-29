"""Очередь на живом Postgres: docker compose up -d db. Без базы тесты пропускаются."""
import os

import asyncpg
import pytest

from app import db
from app.deeplink import parse_start

DSN = os.getenv("TEST_DATABASE_URL", "postgresql://funnel:funnel@localhost:5432/funnel")
UID = 7_000_000_001


@pytest.fixture
async def pool():
    try:
        p = await db.connect(DSN)
    except (OSError, asyncpg.PostgresError):
        pytest.skip("postgres недоступен")
    for t in ("jobs", "users"):
        await p.execute(f"DELETE FROM {t} WHERE tg_id BETWEEN $1 AND $1 + 10", UID)
    yield p
    for t in ("jobs", "users"):
        await p.execute(f"DELETE FROM {t} WHERE tg_id BETWEEN $1 AND $1 + 10", UID)
    await p.close()


async def test_phone_once_and_ticket(pool):
    await db.register_start(pool, UID, "Тест", None, parse_start("reg_tgc_oldmero_1_2710_ut"))
    first = await db.set_phone(pool, UID, "+79990000000")
    assert first["ticket"] and first["src_slot"] == "ut"
    assert await db.set_phone(pool, UID, "+79990000001") is None


async def test_source_is_first_touch(pool):
    await db.register_start(pool, UID, "Тест", None, parse_start("reg_tgc_a_1_0101_ut"))
    user, is_new = await db.register_start(pool, UID, "Тест", None, parse_start("reg_vk_b_2_0202_ve"))
    assert not is_new and user["src_channel"] == "tgc"


async def test_self_referral_ignored_and_friend_counted(pool):
    await db.register_start(pool, UID, "A", None, parse_start(f"ref_{UID}"))
    assert (await db.get_user(pool, UID))["ref_by"] is None
    await db.set_phone(pool, UID, "+79990000000")
    await db.register_start(pool, UID + 1, "B", None, parse_start(f"ref_{UID}"))
    assert await db.tickets_count(pool, UID) == 1
    await db.set_phone(pool, UID + 1, "+79990000002")
    assert await db.tickets_count(pool, UID) == 2


async def test_schedule_is_idempotent_and_survives_crash(pool):
    await db.register_start(pool, UID, "Тест", None, parse_start(None))
    await db.schedule(pool, UID, "program", 0)
    await db.schedule(pool, UID, "program", 0)
    jobs = [j for j in await db.claim_due(pool) if j["tg_id"] == UID]
    assert len(jobs) == 1
    # Процесс упал между claim и отправкой: задача висит в processing.
    await pool.execute("UPDATE jobs SET updated_at = now() - interval '2 minutes' WHERE id = $1", jobs[0]["id"])
    assert await db.recover_stale(pool) >= 1
    again = [j for j in await db.claim_due(pool) if j["tg_id"] == UID]
    assert [j["id"] for j in again] == [jobs[0]["id"]]


async def test_blocked_skips_pending(pool):
    await db.register_start(pool, UID, "Тест", None, parse_start(None))
    await db.schedule(pool, UID, "ticket", 60)
    await db.mark_blocked(pool, UID)
    status = await pool.fetchval("SELECT status FROM jobs WHERE tg_id = $1", UID)
    assert status == "skipped"
