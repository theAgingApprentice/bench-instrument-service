from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BIS_")

    oscilloscope_ip: str
    signal_generator_ip: str
    multimeter_ip: str
    power_supply_ip: str
    scpi_timeout_ms: int = 5000
    log_level: str = "info"
    discover_on_startup: bool = True


settings = Settings()
