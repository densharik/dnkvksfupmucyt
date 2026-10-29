"""Демо-данные для дашборда: ~400 регистраций за 14 дней с метками в боевом формате.

uv run python -m scripts.seed           # добавить
uv run python -m scripts.seed --reset   # очистить демо и добавить заново
Демо-пользователи живут в диапазоне id 9_000_000_000+, реальных не трогают.
"""
import asyncio
import random
import sys
from datetime import datetime, timedelta, timezone

from app import db
from app.config import Settings, load_launch
from app.deeplink import parse_start

BASE_ID = 9_000_000_000
NAMES = ["Анна", "Дмитрий", "Ольга", "Сергей", "Мария", "Алексей", "Елена", "Иван", "Наталья", "Павел",
         "Юлия", "Андрей", "Татьяна", "Михаил", "Ксения", "Артём", "Светлана", "Никита", "Ирина", "Олег"]
# (метка, вес, вероятность оставить телефон)
SOURCES = [
    ("reg_tgc_oldmero_1_{d}_ut", 18, 0.62),
    ("reg_tgc_oldmero_2_{d}_ob", 14, 0.55),
    ("reg_tgc_oldmero_3_{d}_ve", 10, 0.47),
    ("reg_Site_Site_1_{d}_ob", 16, 0.71),
    ("reg_vk_target_1_{d}_ve", 12, 0.38),
    ("reg_ya_direct_2_{d}_ut", 8, 0.34),
    ("", 6, 0.52),
]


async def main(reset: bool) -> None:
    settings = Settings()
    cfg = load_launch(settings.launch_config)
    pool = await db.connect(settings.database_url)
    if reset:
        for table in ("jobs", "users"):
            await pool.execute(f"DELETE FROM {table} WHERE tg_id >= $1", BASE_ID)
    start_id = max(BASE_ID, (await pool.fetchval("SELECT max(tg_id) FROM users")) or 0) + 1

    rnd = random.Random(42)
    now = datetime.now(timezone.utc)
    phoned: list[int] = []
    weights = [w for _, w, _ in SOURCES]
    for i in range(400):
        tg_id = start_id + i
        day_ago = min(13, int(rnd.expovariate(0.25)))
        started = now - timedelta(days=day_ago, hours=rnd.uniform(0, 20), minutes=rnd.uniform(0, 59))
        tpl, _, p_phone = rnd.choices(SOURCES, weights)[0]
        param = tpl.format(d=(started - timedelta(hours=rnd.uniform(0, 30))).strftime("%d%m"))
        if phoned and rnd.random() < 0.08:
            param = f"ref_{rnd.choice(phoned)}"
            p_phone = 0.8
        src = parse_start(param)
        has_phone = rnd.random() < p_phone
        phone_at = started + timedelta(seconds=rnd.lognormvariate(3.2, 0.9)) if has_phone else None
        await pool.execute(
            """
            INSERT INTO users (tg_id, first_name, username, phone, start_param, src_channel, src_audience,
                               src_post, src_date, src_slot, ref_by, ticket, started_at, phone_at, blocked_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,
                    CASE WHEN $4::text IS NULL THEN NULL ELSE nextval('ticket_seq') END,$12,$13,$14)
            """,
            tg_id, rnd.choice(NAMES), None,
            f"+79{rnd.randint(100000000, 999999999)}" if has_phone else None,
            src.raw, src.channel, src.audience, src.post, src.post_date, src.slot, src.ref_by,
            started, phone_at,
            started + timedelta(hours=rnd.uniform(1, 48)) if rnd.random() < 0.06 else None,
        )
        if not has_phone:
            continue
        phoned.append(tg_id)
        for j, m in enumerate(cfg.messages):
            run_at = phone_at + timedelta(seconds=m.delay_seconds)
            pending = run_at > now
            failed = not pending and j > 0 and rnd.random() < 0.04
            await pool.execute(
                "INSERT INTO jobs (tg_id, key, run_at, status, last_error, updated_at) VALUES ($1,$2,$3,$4,$5,$3)",
                tg_id, m.key, run_at,
                "pending" if pending else "failed" if failed else "sent",
                "blocked" if failed else None,
            )
    print(f"seeded 400 demo users from id {start_id}")


if __name__ == "__main__":
    asyncio.run(main("--reset" in sys.argv))
