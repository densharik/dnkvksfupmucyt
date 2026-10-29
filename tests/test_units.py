import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest

from app.config import load_launch
from app.deeplink import parse_start
from app.initdata import InvalidInitData, validate_init_data
from app.render import mask_phone, normalize_phone

ROOT = Path(__file__).resolve().parent.parent


def test_deeplink_reg_format():
    s = parse_start("reg_tgc_oldmero_2_2710_ob")
    assert (s.channel, s.audience, s.post, s.post_date, s.slot) == ("tgc", "oldmero", 2, "27.10", "ob")


def test_deeplink_site_and_ref_and_garbage():
    assert parse_start("reg_Site_Site_1_2010_ob").channel == "site"
    ref = parse_start("ref_12345")
    assert ref.channel == "ref" and ref.ref_by == 12345
    assert parse_start(None).channel == "organic"
    other = parse_start("promo2026")
    assert other.channel == "other" and other.raw == "promo2026"


def test_phone_normalize_and_mask():
    assert normalize_phone("8 (999) 123-45-67") == "+79991234567"
    assert normalize_phone("+7 999 123 45 67") == "+79991234567"
    assert mask_phone("+79991234567") == "+799******67"


def sign(data: dict, token: str) -> str:
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return urlencode({**data, "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()})


def test_init_data_valid_and_tampered():
    token = "123:abc"
    data = {"auth_date": str(int(time.time())), "user": json.dumps({"id": 42, "first_name": "D"})}
    assert validate_init_data(sign(data, token), token)["id"] == 42
    with pytest.raises(InvalidInitData):
        validate_init_data(sign(data, token).replace("42", "43"), token)
    with pytest.raises(InvalidInitData):
        validate_init_data(sign(data, token), "999:other")


def test_init_data_expired():
    token = "123:abc"
    data = {"auth_date": str(int(time.time()) - 90000), "user": json.dumps({"id": 1})}
    with pytest.raises(InvalidInitData, match="expired"):
        validate_init_data(sign(data, token), token)


def test_launch_config_loads():
    cfg = load_launch(ROOT / "config" / "launch.yaml")
    assert [m.delay_seconds for m in cfg.messages] == [10, 60]


def test_launch_config_rejects_duplicate_keys(tmp_path):
    bad = (ROOT / "config" / "launch.yaml").read_text().replace("key: ticket", "key: program")
    p = tmp_path / "bad.yaml"
    p.write_text(bad)
    with pytest.raises(ValueError):
        load_launch(p)
