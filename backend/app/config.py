from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from urllib.parse import urlsplit, unquote
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    environment: str = "development"
    app_secret: str = "development-only-change-this-secret-32"
    public_origin: str = "http://localhost:3000"
    database_url: str = (
        "postgresql+psycopg://narcissus:narcissus_dev_password@localhost:5432/narcissus"
    )
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "narcissus_dev"
    s3_secret_key: str = "narcissus_dev_password"
    s3_bucket: str = "narcissus-private"
    s3_region: str = "us-east-1"
    chat_api_key: str = ""
    chat_base_url: str = "https://api.deepseek.com/v1"
    chat_model: str = "deepseek-chat"
    chat_temperature: float = 0.1
    chat_max_tokens: int = 8192
    chat_send_usage: bool = True
    embedding_api_key: str = ""
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v4"
    embedding_dimensions: int = 1024
    embedding_send_dimensions: bool = True
    embedding_batch_size: int = 10
    writing_max_context_chars: int = 48000
    writing_max_tokens: int = 4096
    learning_max_tokens: int = 16384
    model_timeout_seconds: int = 60
    generation_timeout_seconds: int = 180
    retrieval_max_distance: float = 0.55
    max_files: int = 10
    max_upload_mb: int = 200
    max_pdf_pages: int = 100
    max_document_chars: int = 500000
    max_chunks: int = 800
    max_batch_files: int = 10
    max_unpacked_mb: int = 60
    max_image_pixels: int = 25000000
    web_max_bytes: int = 3000000
    web_timeout_seconds: int = 20
    web_max_redirects: int = 3
    web_dns_mode: Literal["system", "cloudflare"] = "system"
    import_user_concurrency: int = 2
    ocr_daily_pages: int = 200
    search_api_key: str = ""
    search_base_url: str = "https://api.stepfun.com/v1"
    search_reuse_stepfun_key: bool = False
    search_timeout_seconds: int = 40
    research_max_results: int = 10
    research_max_fetches: int = 8
    research_daily_searches: int = 20
    research_user_concurrency: int = 2
    research_max_attempts: int = 3
    research_max_tokens: int = 16384
    ocr_enabled: bool = True
    ocr_max_pages: int = 30
    ocr_page_timeout_seconds: int = 30
    ocr_total_timeout_seconds: int = 160
    tts_api_key: str = ""
    tts_base_url: str = "https://api.stepfun.com/v1"
    tts_model: str = "step-tts-mini"
    tts_default_voice: str = "cixingnansheng"
    tts_second_voice: str = "wenrounvsheng"
    tts_timeout_seconds: int = 90
    audio_max_chars: int = 4000
    audio_max_segments: int = 40
    audio_user_concurrency: int = 2
    audio_daily_limit: int = 20
    audio_max_duration_seconds: int = 1200
    visual_user_concurrency: int = 2
    visual_daily_jobs: int = 50
    visual_max_tokens: int = 12000
    visual_json_mode: bool = False
    visual_reasoning_effort: Literal["", "low", "medium", "high"] = ""
    visual_render_timeout: int = 90
    visual_font_path: str = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    session_days: int = 7
    minio_root_password: str = ""

    @model_validator(mode="after")
    def production(self):
        if self.environment == "production":
            if len(self.app_secret) < 32 or "development" in self.app_secret:
                raise ValueError(
                    "Production requires a random APP_SECRET of at least 32 characters"
                )
            if not self.public_origin.startswith("https://"):
                raise ValueError("Production requires an HTTPS PUBLIC_ORIGIN")
            if (
                "dev_password" in self.database_url
                or self.s3_secret_key == "narcissus_dev_password"
                or len(unquote(urlsplit(self.database_url).password or "")) < 16
                or len(self.s3_secret_key) < 16
            ):
                raise ValueError(
                    "Production must replace database and object storage development passwords"
                )
            redis_password = unquote(urlsplit(self.redis_url).password or "")
            if len(redis_password) < 16 or redis_password == "narcissus_dev_redis":
                raise ValueError(
                    "Production requires a non-default Redis password of at least 16 characters"
                )
            if self.minio_root_password and (
                len(self.minio_root_password) < 16
                or self.minio_root_password == "narcissus_dev_password"
            ):
                raise ValueError(
                    "Production must replace the MinIO development root password"
                )
            if not self.chat_api_key or not self.embedding_api_key:
                raise ValueError(
                    "Production requires separate chat and embedding configuration"
                )
        return self


@lru_cache
def settings():
    return Settings()
