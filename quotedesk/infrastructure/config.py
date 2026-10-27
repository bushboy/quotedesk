import os

from pydantic_settings import BaseSettings, SettingsConfigDict

_REQUIRED = "DATABASE_URL is required."


class SettingsError(Exception):
    def __init__(self, sentence: str) -> None:
        super().__init__(sentence)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str


def get_settings() -> Settings:
    url = os.environ.get("DATABASE_URL")
    if url is None or url == "":
        raise SettingsError(_REQUIRED)
    return Settings(database_url=url)
