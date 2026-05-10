from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram Bot
    bot_token: str

    # VK API
    vk_token: str
    vk_user_agent: str

    # Веб-форма получения токена через логин/пароль (vkpymusic.TokenReceiver)
    vk_auth_ui_enabled: bool = False

    # MongoDB
    mongo_url: str
    db_name: str

    # Application
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False

    # SSL
    ssl_keyfile: str | None = None
    ssl_certfile: str | None = None

settings = Settings()
