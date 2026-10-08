from functools import lru_cache
from typing import Literal , Self
from pathlib import Path
from pydantic_settings import BaseSettings , SettingsConfigDict
from pydantic import Field , model_validator

class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file = ".env",
        env_file_encoding = "utf-8",
        extra = "ignore",
    )

    app_name: str = "Doc Pulse"
    app_version: str = "0.1.0"
    environment: Literal["development", "production" , "staging"] = "development"

    max_file_size_mb: int = Field(default=10, gt=0, le=200)
    default_chunk_size: int = Field(default=200, gt=0, le=5000)
    default_chunk_overlap: int = Field(default=40, ge=0)
    max_concurrent_jobs: int = Field(default=4, gt=0, le=64)
    http_timeout_seconds: float = Field(default=30.0, gt=0)
    storage_dir: Path = Path("data")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "text"] = "json"

    @model_validator(mode="after")
    def _validate_def_chunk_size(self) -> Self:
        if self.default_chunk_overlap >= self.default_chunk_size:
            raise ValueError("default_chunk_overlap must be less than default_chunk_size")
        return self

@lru_cache
def get_settings() -> Settings:
    return Settings()