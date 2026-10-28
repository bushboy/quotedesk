import os
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_REQUIRED = "DATABASE_URL is required."
_SPARK_KEY = "META_API_KEY is required when MODEL is spark."
_SPARK_MODEL = "SPARK_MODEL_ID is required when MODEL is spark."
_MODEL = "MODEL is script or spark."
_META_BASE = "https://api.meta.ai/v1"


class SettingsError(Exception):
    def __init__(self, sentence: str) -> None:
        super().__init__(sentence)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str
    channel: Literal["outbox"] = "outbox"
    whatsapp_verify_token: str | None = None
    whatsapp_app_secret: str | None = None
    model: Literal["script", "spark"] = "script"
    meta_api_key: str = ""
    meta_base_url: str = _META_BASE
    spark_model_id: str = ""


def get_settings() -> Settings:
    url = os.environ.get("DATABASE_URL")
    if url is None or url == "":
        raise SettingsError(_REQUIRED)
    model = os.environ.get("MODEL", "script")
    if model not in ("script", "spark"):
        raise SettingsError(_MODEL)
    key = os.environ.get("META_API_KEY", "")
    spark_model_id = os.environ.get("SPARK_MODEL_ID", "")
    if model == "spark" and key == "":
        raise SettingsError(_SPARK_KEY)
    if model == "spark" and spark_model_id == "":
        raise SettingsError(_SPARK_MODEL)
    base = os.environ.get("META_BASE_URL", "") or _META_BASE
    return Settings(
        database_url=url,
        model=model,
        meta_api_key=key,
        meta_base_url=base,
        spark_model_id=spark_model_id,
    )
