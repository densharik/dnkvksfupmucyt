#!/usr/bin/env bash
# Локальный запуск одной командой: https-туннель localhost.run + Postgres + бот.
#   ./scripts/run.sh          запустить
#   ./scripts/run.sh --clean  то же, но сначала очистить пользователей и очередь
# Ctrl+C останавливает бота и туннель.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "нет .env: cp .env.example .env и впишите BOT_TOKEN, ADMIN_IDS"; exit 1; }
set -a; . ./.env; set +a

LOG=$(mktemp)
ssh -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=20 -o ExitOnForwardFailure=yes \
    -R 80:localhost:8000 nokey@localhost.run >"$LOG" 2>&1 &
SSH=$!
WATCH=""
trap 'exit 130' INT TERM
trap 'kill $SSH $WATCH 2>/dev/null; docker compose stop bot >/dev/null 2>&1; rm -f "$LOG"' EXIT

tunnel_url() { grep -ao 'https://[a-z0-9]*\.lhr\.life' "$LOG" | tail -1 || true; }
set_url() { sed -i.bak "s|^WEBAPP_URL=.*|WEBAPP_URL=$1/|" .env && rm -f .env.bak; }

for _ in $(seq 30); do [ -n "$(tunnel_url)" ] && break; sleep 1; done
URL=$(tunnel_url)
[ -n "$URL" ] || { echo "туннель не поднялся:"; cat "$LOG"; exit 1; }
grep -q '^WEBAPP_URL=' .env || echo "WEBAPP_URL=" >> .env
set_url "$URL"

docker compose up -d --wait db
if [ "${1:-}" = "--clean" ]; then
    docker compose exec -T db psql -qU funnel -c "TRUNCATE jobs, users" 2>/dev/null || true
fi
docker compose up -d --build bot

BOT=$(curl -s "https://api.telegram.org/bot$BOT_TOKEN/getMe" | grep -o '"username":"[^"]*"' | cut -d'"' -f4)
echo
echo "  бот:      https://t.me/$BOT?start=reg_tgc_oldmero_1_2810_ut"
echo "  дашборд:  кнопка меню «Дашборд» в чате с ботом или /dashboard"
echo

# Бесплатный localhost.run засыпает без запросов и иногда меняет адрес: пингуем и подхватываем новый.
(
    while kill -0 $SSH 2>/dev/null; do
        curl -s -o /dev/null --max-time 10 "$URL/healthz" || true
        NEW=$(tunnel_url)
        if [ -n "$NEW" ] && [ "$NEW" != "$URL" ]; then
            URL=$NEW
            set_url "$URL"
            echo ">>> туннель сменил адрес, перезапускаю бота: $URL"
            docker compose up -d --force-recreate bot >/dev/null 2>&1
        fi
        sleep 15
    done
    echo ">>> туннель упал, перезапустите ./scripts/run.sh"
) &
WATCH=$!

while kill -0 $SSH 2>/dev/null; do
    docker compose logs -f --tail 5 bot || true
    sleep 1
done
