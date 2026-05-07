from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    openai_base_url: str = "http://dolo-llm.local:11434/v1"
    openai_api_key: str = "ollama"
    model_name: str = "qwen2.5:7b-instruct-q5_K_M"

    database_url: str = "postgresql+asyncpg://hermes:hermes@db:5432/hermes"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
