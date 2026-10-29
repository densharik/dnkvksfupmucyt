import asyncpg

from app.config import LaunchConfig
from app.deeplink import SLOTS
from app.render import mask_phone

SMALL_N = 30  # ниже этого конверсию показываем с пометкой "мало данных"


def rate(k: int, n: int) -> dict:
    return {"k": k, "n": n, "p": k / n if n else 0.0, "small": n < SMALL_N}


async def collect(pool: asyncpg.Pool, cfg: LaunchConfig) -> dict:
    totals = await pool.fetchrow(
        """
        SELECT count(*) AS starts,
               count(phone) AS phones,
               count(blocked_at) AS blocked,
               count(*) FILTER (WHERE started_at > now() - interval '24 hours') AS starts_24h,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM phone_at - started_at))
                   AS median_phone_sec
        FROM users
        """
    )
    sent = {r["key"]: r["n"] for r in await pool.fetch(
        "SELECT key, count(*) AS n FROM jobs WHERE status = 'sent' GROUP BY key"
    )}

    steps = [("Старт", totals["starts"]), ("Телефон", totals["phones"])]
    for i, m in enumerate(cfg.messages, 1):
        steps.append((f"Сообщение {i} (+{m.delay_seconds}с)", sent.get(m.key, 0)))
    funnel = []
    for i, (label, n) in enumerate(steps):
        prev = steps[i - 1][1] if i else n
        funnel.append({"label": label, "n": n, "from_prev": rate(n, prev)})

    sources = [
        {"channel": r["src_channel"], "audience": r["src_audience"], "starts": r["starts"],
         "phones": r["phones"], "conv": rate(r["phones"], r["starts"])}
        for r in await pool.fetch(
            """
            SELECT src_channel, src_audience, count(*) AS starts, count(phone) AS phones
            FROM users GROUP BY 1, 2 ORDER BY starts DESC
            """
        )
    ]

    posts = [
        {"post": f"#{r['src_post']} {r['src_date']}", "source": f"{r['src_channel']}/{r['src_audience']}",
         "slot": SLOTS.get(r["src_slot"], r["src_slot"]), "starts": r["starts"], "phones": r["phones"],
         "conv": rate(r["phones"], r["starts"])}
        for r in await pool.fetch(
            """
            SELECT src_channel, src_audience, src_post, src_date, src_slot,
                   count(*) AS starts, count(phone) AS phones
            FROM users WHERE src_post IS NOT NULL
            GROUP BY 1, 2, 3, 4, 5 ORDER BY phones DESC, starts DESC LIMIT 12
            """
        )
    ]

    slots = [
        {"slot": SLOTS.get(r["src_slot"], r["src_slot"]), "starts": r["starts"], "phones": r["phones"],
         "conv": rate(r["phones"], r["starts"])}
        for r in await pool.fetch(
            """
            SELECT src_slot, count(*) AS starts, count(phone) AS phones
            FROM users WHERE src_slot <> '' GROUP BY 1
            ORDER BY array_position(ARRAY['ut','ob','ve'], src_slot)
            """
        )
    ]

    daily = [
        {"day": r["day"].strftime("%d.%m"), "starts": r["starts"], "phones": r["phones"]}
        for r in await pool.fetch(
            """
            SELECT d::date AS day,
                   (SELECT count(*) FROM users WHERE (started_at AT TIME ZONE 'Europe/Moscow')::date = d::date) AS starts,
                   (SELECT count(*) FROM users WHERE (phone_at AT TIME ZONE 'Europe/Moscow')::date = d::date) AS phones
            FROM generate_series((now() AT TIME ZONE 'Europe/Moscow')::date - 13,
                                 (now() AT TIME ZONE 'Europe/Moscow')::date, interval '1 day') AS d
            """
        )
    ]

    referrers = [
        {"name": r["first_name"], "username": r["username"], "friends": r["friends"]}
        for r in await pool.fetch(
            """
            SELECT r.first_name, r.username, count(*) AS friends
            FROM users f JOIN users r ON r.tg_id = f.ref_by
            WHERE f.phone IS NOT NULL
            GROUP BY r.tg_id ORDER BY friends DESC LIMIT 5
            """
        )
    ]
    ref_total = await pool.fetchval("SELECT count(*) FROM users WHERE ref_by IS NOT NULL AND phone IS NOT NULL")

    recent = [
        {"name": r["first_name"], "phone": mask_phone(r["phone"]), "source": r["start_param"] or "organic",
         "at": r["started_at"].isoformat(), "blocked": r["blocked_at"] is not None}
        for r in await pool.fetch("SELECT * FROM users ORDER BY started_at DESC LIMIT 10")
    ]

    queue = {r["status"]: r["n"] for r in await pool.fetch(
        "SELECT status, count(*) AS n FROM jobs GROUP BY status"
    )}
    errors = [
        {"key": r["key"], "error": r["last_error"], "at": r["updated_at"].isoformat()}
        for r in await pool.fetch(
            """
            SELECT key, last_error, updated_at FROM jobs
            WHERE status = 'failed' AND last_error <> 'blocked' ORDER BY updated_at DESC LIMIT 5
            """
        )
    ]

    return {
        "launch": cfg.launch.name,
        "totals": {
            "starts": totals["starts"], "phones": totals["phones"], "blocked": totals["blocked"],
            "starts_24h": totals["starts_24h"], "median_phone_sec": totals["median_phone_sec"],
            "ref_total": ref_total,
        },
        "funnel": funnel,
        "sources": sources,
        "posts": posts,
        "slots": slots,
        "daily": daily,
        "referrers": referrers,
        "recent": recent,
        "queue": queue,
        "errors": errors,
    }
