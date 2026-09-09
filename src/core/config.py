from functools import lru_cache

from dotenv import find_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseConfig(BaseSettings):
    """Базовый класс для всех настроек приложения.

    Note:
        Автоматически подхватывает `.env` и игнорирует лишние переменные.
    """

    model_config = SettingsConfigDict(
        env_file=(find_dotenv()),
        env_file_encoding="utf-8",
        extra="ignore",
    )


class OzonSettings(BaseConfig):
    """Настройки OZON"""

    model_config = SettingsConfigDict(env_prefix="OZON_")
    client_id: str = ""
    api_key: str = ""
    warehouse_id: int = 0


class Settings(BaseConfig):
    """Корневые настройки сервиса"""

    ozon: OzonSettings = Field(default_factory=OzonSettings)


@lru_cache(maxsize=1)
def get_settings() -> "Settings":
    """Возвращает singleton настроек.

    Returns:
        Settings: Объект `Settings`.
    """
    return Settings()
