import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class InvalidInitData(Exception):
    pass


def validate_init_data(init_data: str, bot_token: str, max_age: int = 86400) -> dict:
    """Проверка подписи Telegram WebApp initData. Возвращает user из initData."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        raise InvalidInitData("no hash")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise InvalidInitData("bad hash")
    if time.time() - int(pairs.get("auth_date", 0)) > max_age:
        raise InvalidInitData("expired")
    return json.loads(pairs.get("user", "{}"))
