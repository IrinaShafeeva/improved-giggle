from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Telegram
    bot_token: str

    # Database
    database_url: str = (
        "postgresql+asyncpg://mastermind:mastermind@localhost:5432/mastermind"
    )

    # LLM
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"

    # Whisper
    whisper_api_key: str = ""
    whisper_base_url: str = "https://api.openai.com/v1"
    whisper_model: str = "whisper-1"

    # Stickers (optional)
    sticker_private_step_done: str = ""
    sticker_private_day_closed: str = ""
    sticker_group_all_closed: str = ""

    # Rate limiting
    llm_requests_per_user_per_hour: int = 20


settings = Settings()
