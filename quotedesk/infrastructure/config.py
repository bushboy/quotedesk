import os
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

StoreKind = Literal["postgres", "memory"]
_STORE = "STORE is postgres or memory."

_REQUIRED = "DATABASE_URL is required."
_SPARK_KEY = "META_API_KEY is required when MODEL is spark."
_SPARK_MODEL = "SPARK_MODEL_ID is required when MODEL is spark."
_MODEL = "MODEL is script or spark."
_AGENT_PROVIDER = "AGENT_PROVIDER is meta or baseten."
_IMAGE_PROVIDER = "IMAGE_PROVIDER is meta or baseten."
_BASETEN_KEY_AGENT = "BASETEN_API_KEY is required when AGENT_PROVIDER is baseten."
_BASETEN_MODEL_AGENT = "BASETEN_MODEL_ID is required when AGENT_PROVIDER is baseten."
_BASETEN_KEY_IMAGE = "BASETEN_API_KEY is required when IMAGE_PROVIDER is baseten."
_BASETEN_MODEL_IMAGE = "BASETEN_MODEL_ID is required when IMAGE_PROVIDER is baseten."
_TENANT = "TENANT is aquasure or frameworks."
_META_BASE = "https://api.meta.ai/v1"
_BASETEN_BASE = "https://inference.baseten.co/v1"
_PROVIDERS = ("meta", "baseten")


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
    agent_provider: Literal["meta", "baseten"] = "meta"
    image_provider: Literal["meta", "baseten"] = "meta"
    meta_api_key: str = ""
    meta_base_url: str = _META_BASE
    spark_model_id: str = ""
    baseten_api_key: str = ""
    baseten_base_url: str = _BASETEN_BASE
    baseten_model_id: str = ""
    baseten_image_model_id: str = ""
    tenant: str = "aquasure"
    store: StoreKind = "postgres"


def get_settings() -> Settings:
    url = os.environ.get("DATABASE_URL")
    if url is None or url == "":
        raise SettingsError(_REQUIRED)
    model = os.environ.get("MODEL", "spark")
    if model not in ("script", "spark"):
        raise SettingsError(_MODEL)
    agent_provider = os.environ.get("AGENT_PROVIDER", "meta")
    image_provider = os.environ.get("IMAGE_PROVIDER", "meta")
    if agent_provider not in _PROVIDERS:
        raise SettingsError(_AGENT_PROVIDER)
    if image_provider not in _PROVIDERS:
        raise SettingsError(_IMAGE_PROVIDER)
    key = os.environ.get("META_API_KEY", "")
    spark_model_id = os.environ.get("SPARK_MODEL_ID", "")
    baseten_key = os.environ.get("BASETEN_API_KEY", "")
    baseten_model_id = os.environ.get("BASETEN_MODEL_ID", "")
    baseten_image_model_id = os.environ.get("BASETEN_IMAGE_MODEL_ID", "") or baseten_model_id
    live = model == "spark"
    uses_meta = live and (agent_provider == "meta" or image_provider == "meta")
    if uses_meta and key == "":
        raise SettingsError(_SPARK_KEY)
    if uses_meta and spark_model_id == "":
        raise SettingsError(_SPARK_MODEL)
    if live and agent_provider == "baseten" and baseten_key == "":
        raise SettingsError(_BASETEN_KEY_AGENT)
    if live and agent_provider == "baseten" and baseten_model_id == "":
        raise SettingsError(_BASETEN_MODEL_AGENT)
    if live and image_provider == "baseten" and baseten_key == "":
        raise SettingsError(_BASETEN_KEY_IMAGE)
    if live and image_provider == "baseten" and baseten_image_model_id == "":
        raise SettingsError(_BASETEN_MODEL_IMAGE)
    base = os.environ.get("META_BASE_URL", "") or _META_BASE
    baseten_base = os.environ.get("BASETEN_BASE_URL", "") or _BASETEN_BASE
    tenant = os.environ.get("TENANT", "aquasure")
    if tenant not in ("aquasure", "frameworks"):
        raise SettingsError(_TENANT)
    store = os.environ.get("STORE", "postgres")
    if store not in ("postgres", "memory"):
        raise SettingsError(_STORE)
    return Settings(
        database_url=url,
        model=model,
        agent_provider=agent_provider,
        image_provider=image_provider,
        meta_api_key=key,
        meta_base_url=base,
        spark_model_id=spark_model_id,
        baseten_api_key=baseten_key,
        baseten_base_url=baseten_base,
        baseten_model_id=baseten_model_id,
        baseten_image_model_id=baseten_image_model_id,
        tenant=tenant,
        store=store,
    )
