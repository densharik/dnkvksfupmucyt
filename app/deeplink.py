import re
from dataclasses import dataclass

# Формат меток как в боевых ботах: reg_<канал>_<аудитория>_<пост>_<ДДММ>_<ut|ob|ve>
# например reg_tgc_oldmero_2_2710_ob - телеграм-канал, база прошлого эфира, 2-й пост 27.10, обед.
REG_RE = re.compile(r"^reg_([A-Za-z0-9]+)_([A-Za-z0-9]+)_(\d+)_(\d{4})_([a-z]+)$")
REF_RE = re.compile(r"^ref_(\d+)$")

SLOTS = {"ut": "утро", "ob": "обед", "ve": "вечер"}


@dataclass
class Source:
    raw: str = ""
    channel: str = "organic"
    audience: str = ""
    post: int | None = None
    post_date: str = ""
    slot: str = ""
    ref_by: int | None = None


def parse_start(param: str | None) -> Source:
    param = (param or "").strip()
    if not param:
        return Source()
    if m := REG_RE.match(param):
        channel, audience, post, ddmm, slot = m.groups()
        return Source(
            raw=param,
            channel=channel.lower(),
            audience=audience.lower(),
            post=int(post),
            post_date=f"{ddmm[:2]}.{ddmm[2:]}",
            slot=slot,
        )
    if m := REF_RE.match(param):
        return Source(raw=param, channel="ref", ref_by=int(m.group(1)))
    return Source(raw=param, channel="other")
