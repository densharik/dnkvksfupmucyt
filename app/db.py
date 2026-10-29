import asyncpg

from app.deeplink import Source

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id        BIGINT PRIMARY KEY,
    first_name   TEXT NOT NULL DEFAULT '',
    username     TEXT,
    phone        TEXT,
    start_param  TEXT NOT NULL DEFAULT '',
    src_channel  TEXT NOT NULL DEFAULT 'organic',
    src_audience TEXT NOT NULL DEFAULT '',
    src_post     INT,
    src_date     TEXT NOT NULL DEFAULT '',
    src_slot     TEXT NOT NULL DEFAULT '',
    ref_by       BIGINT,
    ticket       INT UNIQUE,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    phone_at     TIMESTAMPTZ,
    blocked_at   TIMESTAMPTZ
);
CREATE SEQUENCE IF NOT EXISTS ticket_seq START 1001;

-- Отложенные сообщения живут в базе, а не в памяти: перезапуск бота их не теряет.
CREATE TABLE IF NOT EXISTS jobs (
    id         BIGSERIAL PRIMARY KEY,
    tg_id      BIGINT NOT NULL,
    key        TEXT NOT NULL,
    run_at     TIMESTAMPTZ NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    attempts   INT NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tg_id, key)
);
CREATE INDEX IF NOT EXISTS jobs_due ON jobs (run_at) WHERE status = 'pending';
"""


async def connect(dsn: str) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)
    return pool


async def register_start(pool: asyncpg.Pool, tg_id: int, first_name: str, username: str | None, src: Source):
    """Возвращает (user, is_new). Источник фиксируется по первому касанию."""
    ref_by = src.ref_by if src.ref_by != tg_id else None
    row = await pool.fetchrow(
        """
        INSERT INTO users (tg_id, first_name, username, start_param, src_channel, src_audience,
                           src_post, src_date, src_slot, ref_by)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (tg_id) DO NOTHING
        RETURNING *
        """,
        tg_id, first_name, username, src.raw, src.channel, src.audience,
        src.post, src.post_date, src.slot, ref_by,
    )
    if row:
        return row, True
    row = await pool.fetchrow(
        "UPDATE users SET first_name = $2, username = $3, blocked_at = NULL WHERE tg_id = $1 RETURNING *",
        tg_id, first_name, username,
    )
    return row, False


async def get_user(pool: asyncpg.Pool, tg_id: int):
    return await pool.fetchrow("SELECT * FROM users WHERE tg_id = $1", tg_id)


async def set_phone(pool: asyncpg.Pool, tg_id: int, phone: str):
    """Пишет телефон и выдаёт билет только один раз. None - телефон уже был."""
    return await pool.fetchrow(
        """
        UPDATE users SET phone = $2, phone_at = now(), ticket = nextval('ticket_seq')
        WHERE tg_id = $1 AND phone IS NULL
        RETURNING *
        """,
        tg_id, phone,
    )


async def tickets_count(pool: asyncpg.Pool, tg_id: int) -> int:
    refs = await pool.fetchval(
        "SELECT count(*) FROM users WHERE ref_by = $1 AND phone IS NOT NULL", tg_id
    )
    return 1 + refs


async def schedule(pool: asyncpg.Pool, tg_id: int, key: str, delay_seconds: int) -> None:
    await pool.execute(
        """
        INSERT INTO jobs (tg_id, key, run_at) VALUES ($1, $2, now() + make_interval(secs => $3))
        ON CONFLICT (tg_id, key) DO NOTHING
        """,
        tg_id, key, delay_seconds,
    )


async def claim_due(pool: asyncpg.Pool, limit: int = 25):
    # SKIP LOCKED: два экземпляра бота не возьмут одно и то же сообщение.
    return await pool.fetch(
        """
        UPDATE jobs SET status = 'processing', updated_at = now()
        WHERE id IN (
            SELECT id FROM jobs WHERE status = 'pending' AND run_at <= now()
            ORDER BY run_at LIMIT $1 FOR UPDATE SKIP LOCKED
        )
        RETURNING *
        """,
        limit,
    )


async def finish_job(pool: asyncpg.Pool, job_id: int, status: str, error: str | None = None) -> None:
    await pool.execute(
        "UPDATE jobs SET status = $2, last_error = $3, attempts = attempts + 1, updated_at = now() WHERE id = $1",
        job_id, status, error,
    )


async def retry_job(pool: asyncpg.Pool, job_id: int, delay_seconds: float, error: str) -> None:
    await pool.execute(
        """
        UPDATE jobs SET status = 'pending', run_at = now() + make_interval(secs => $2),
                        attempts = attempts + 1, last_error = $3, updated_at = now()
        WHERE id = $1
        """,
        job_id, delay_seconds, error,
    )


async def recover_stale(pool: asyncpg.Pool) -> int:
    """Задачи, зависшие в processing после падения процесса, возвращаются в очередь."""
    res = await pool.execute(
        "UPDATE jobs SET status = 'pending' WHERE status = 'processing' AND updated_at < now() - interval '1 minute'"
    )
    return int(res.split()[-1])


async def mark_blocked(pool: asyncpg.Pool, tg_id: int) -> None:
    await pool.execute(
        "UPDATE users SET blocked_at = now() WHERE tg_id = $1 AND blocked_at IS NULL", tg_id
    )
    await pool.execute(
        "UPDATE jobs SET status = 'skipped', last_error = 'blocked' WHERE tg_id = $1 AND status = 'pending'",
        tg_id,
    )
