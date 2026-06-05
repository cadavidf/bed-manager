from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/bedmanager"
    webhook_secret: str = "change-me"
    ical_poll_interval_minutes: int = 60
    app_port: int = 13377


settings = Settings()
