from pathlib import Path

import yaml
from pydantic import BaseModel, Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str
    database_url: str = "postgresql://funnel:funnel@localhost:5432/funnel"
    # Telegram id через запятую: кому доступен дашборд.
    admin_ids: str = ""
    launch_config: Path = Path("config/launch.yaml")
    # Публичный https-адрес миниаппа (Telegram открывает Mini App только по https).
    webapp_url: str = ""
    api_port: int = 8000
    # Открыть дашборд в обычном браузере без Telegram. Только для локальной разработки.
    dashboard_dev: bool = False

    @property
    def admins(self) -> set[int]:
        return {int(x) for x in self.admin_ids.replace(" ", "").split(",") if x}


class Button(BaseModel):
    text: str
    url: HttpUrl


class Texts(BaseModel):
    welcome: str
    ask_phone: str
    phone_button: str
    wrong_contact: str
    thanks: str
    already_registered: str
    referral_bonus: str


class Message(BaseModel):
    key: str
    delay_seconds: int = Field(ge=0)
    text: str
    buttons: list[Button] = []
    share_button: str | None = None


class Nudge(BaseModel):
    delay_seconds: int = Field(gt=0)
    text: str


class Launch(BaseModel):
    name: str
    description: str = Field("", max_length=512)


class LaunchConfig(BaseModel):
    launch: Launch
    texts: Texts
    messages: list[Message] = Field(min_length=1)
    nudge: Nudge | None = None


def load_launch(path: Path) -> LaunchConfig:
    cfg = LaunchConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    keys = [m.key for m in cfg.messages]
    if len(keys) != len(set(keys)) or "nudge" in keys:
        raise ValueError(f"{path}: ключи messages должны быть уникальны и не 'nudge'")
    return cfg
