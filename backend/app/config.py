import json
import re
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def parse_cors_origins(raw: str) -> list[str]:
    value = (raw or "").strip()
    if not value:
        return ["http://localhost:3000"]
    if value.startswith("["):
        parsed = json.loads(value)
        return [str(v).strip() for v in parsed if str(v).strip()]
    return [part.strip() for part in value.split(",") if part.strip()]


def origins_to_regex(patterns: list[str]) -> re.Pattern[str] | None:
    """Compile `*` glob patterns (e.g. https://*.vercel.app) into an origin regex."""
    wildcards = [p for p in patterns if "*" in p]
    if not wildcards:
        return None
    joined = "|".join(re.escape(p).replace(r"\*", ".*") for p in wildcards)
    return re.compile(f"^(?:{joined})$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "ResumeBuild"
    debug: bool = True
    log_level: str = "DEBUG"
    sql_echo: bool = True

    database_url: str = "sqlite:///./resumebuild.db"
    redis_url: str = "redis://localhost:6379/0"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    # Set true on Render free/starter to avoid OOM from downloading the ~90MB model.
    embedding_fallback: bool = False
    openai_timeout_seconds: float = 25.0

    auto_apply_resumes_path: Path = BASE_DIR / "storage" / "auto_apply"

    storage_path: Path = BASE_DIR / "storage"
    # Resolve relative to this package (backend/), not the repo root — in the
    # Docker image BASE_DIR points at "/", where templates wouldn't exist.
    templates_path: Path = Path(__file__).resolve().parent.parent / "templates"
    vector_index_path: Path = BASE_DIR / "storage" / "faiss_index"

    match_threshold: float = 65.0
    top_jobs_limit: int = 200

    # Plain string env var — never use list[str] here (Render/pydantic JSON parsing breaks).
    allowed_origins: str = Field(
        default="http://localhost:3000",
        validation_alias=AliasChoices("CORS_ORIGINS", "ALLOWED_ORIGINS"),
    )
    # Glob patterns for origins whose host changes (Vercel preview/alias domains).
    allowed_origin_patterns: str = Field(
        default="https://*.vercel.app,http://localhost:*",
        validation_alias=AliasChoices("CORS_ORIGIN_PATTERNS", "ALLOWED_ORIGIN_PATTERNS"),
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return parse_cors_origins(self.allowed_origins)

    @property
    def cors_pattern_list(self) -> list[str]:
        return parse_cors_origins(self.allowed_origin_patterns)

    @property
    def cors_origin_regex(self) -> re.Pattern[str] | None:
        return origins_to_regex(self.cors_pattern_list)

    def cors_origin_allowed(self, origin: str | None) -> bool:
        if not origin:
            return False
        if origin in self.cors_origin_list:
            return True
        pattern = self.cors_origin_regex
        return bool(pattern and pattern.match(origin))

    @property
    def use_embedding_fallback(self) -> bool:
        """Skip the ~90MB sentence-transformers model in production (Render free tier)."""
        if self.embedding_fallback:
            return True
        return not self.debug

    # Job boards — Indeed, ZipRecruiter, LinkedIn, Glassdoor + Greenhouse career pages
    # + Foundit + Naukri (India-first: LinkedIn, Indeed, Foundit, Naukri)
    indeed_domain: str = "www.indeed.com"
    indeed_session_cookie: str = ""
    greenhouse_boards: str = "stripe,figma,airbnb,netflix,datadog"
    linkedin_access_token: str = ""
    linkedin_session_cookie: str = ""
    glassdoor_session_cookie: str = ""
    foundit_session_cookie: str = ""
    naukri_session_cookie: str = ""
    naukri_nkparam: str = ""
    naukri_app_id: str = ""
    naukri_system_id: str = ""


settings = Settings()

# A literal default DATABASE_URL means "never configured" (set in the Render
# dashboard as a placeholder). If the persistent disk at /var/data is mounted,
# keep SQLite on the durable volume instead of the container's ephemeral FS.
if settings.database_url == "sqlite:///./resumebuild.db":
    try:
        _mounts = Path("/proc/mounts").read_text()
        if any(line.split()[1] == "/var/data" for line in _mounts.splitlines() if line.split()):
            settings.database_url = "sqlite:////var/data/resumebuild.db"
    except Exception:
        pass

settings.storage_path.mkdir(parents=True, exist_ok=True)
settings.auto_apply_resumes_path.mkdir(parents=True, exist_ok=True)
(settings.storage_path / "resumes").mkdir(parents=True, exist_ok=True)
(settings.storage_path / "generated").mkdir(parents=True, exist_ok=True)
settings.vector_index_path.mkdir(parents=True, exist_ok=True)
