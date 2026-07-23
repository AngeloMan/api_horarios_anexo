import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "API de Horários FET"
    VERSION: str = "1.0.0"
    
    # Configurações do Banco de Dados
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "postgresql://postgres:postgres@db:5432/horarios"
    )
    
    # Configurações do Redis / Celery
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    
    # Configurações do Motor FET
    FET_CL_PATH: str = os.getenv("FET_CL_PATH", "fet-cl")
    DEFAULT_TIMEOUT_SECONDS: int = int(os.getenv("DEFAULT_TIMEOUT_SECONDS", "60"))

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
