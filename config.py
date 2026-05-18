"""
Configuration Management for CIRO Backend
==========================================

Handles environment variable loading, validation, and application settings.
Supports multiple deployment modes: development, staging, production.
"""

import os
from typing import Optional
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic import Field

load_dotenv()


class Settings(BaseSettings):
    """Application settings from environment variables."""

    # ─────────────────────────────────────────────────────────────────────
    # GEMINI Configuration (Required)
    # ─────────────────────────────────────────────────────────────────────
    gemini_api_key: str = Field(..., alias="GEMINI_API_KEY")
    gemini_api_key_2: Optional[str] = Field(None, alias="GEMINI_API_KEY_2")
    gemini_api_key_3: Optional[str] = Field(None, alias="GEMINI_API_KEY_3")

    # ─────────────────────────────────────────────────────────────────────
    # Real API Keys (Optional)
    # ─────────────────────────────────────────────────────────────────────
    openweather_api_key: Optional[str] = Field(None, alias="OPENWEATHER_API_KEY")
    tomtom_api_key: Optional[str] = Field(None, alias="TOMTOM_API_KEY")

    # ─────────────────────────────────────────────────────────────────────
    # Firebase Configuration (Optional)
    # ─────────────────────────────────────────────────────────────────────
    firebase_project_id: Optional[str] = Field(None, alias="FIREBASE_PROJECT_ID")
    firebase_credentials_path: str = Field("./firebase_credentials.json", alias="FIREBASE_CREDENTIALS_PATH")

    # ─────────────────────────────────────────────────────────────────────
    # Server Configuration
    # ─────────────────────────────────────────────────────────────────────
    port: int = Field(8000, alias="PORT")
    host: str = Field("0.0.0.0", alias="HOST")
    production_mode: bool = Field(False, alias="PRODUCTION_MODE")

    # ─────────────────────────────────────────────────────────────────────
    # Feature Flags
    # ─────────────────────────────────────────────────────────────────────
    rate_limit_enabled: bool = Field(True, alias="RATE_LIMIT_ENABLED")
    rate_limit_per_minute: int = Field(60, alias="RATE_LIMIT_PER_MINUTE")
    cache_enabled: bool = Field(True, alias="CACHE_ENABLED")
    cache_ttl_seconds: int = Field(300, alias="CACHE_TTL_SECONDS")
    detailed_logging: bool = Field(True, alias="DETAILED_LOGGING")

    # ─────────────────────────────────────────────────────────────────────
    # API Behavior & Timeouts (CRITICAL for production)
    # ─────────────────────────────────────────────────────────────────────
    api_timeout: int = Field(15, alias="API_TIMEOUT", ge=5, le=60, description="Timeout for external API calls in seconds")
    api_max_retries: int = Field(3, alias="API_MAX_RETRIES", ge=0, le=10)
    api_retry_backoff_base: float = Field(2.0, alias="API_RETRY_BACKOFF_BASE", ge=1.0, le=10.0)
    http_client_timeout: int = Field(20, alias="HTTP_CLIENT_TIMEOUT", ge=5, le=120, description="httpx client timeout in seconds")
    signal_collection_timeout: int = Field(30, alias="SIGNAL_COLLECTION_TIMEOUT", ge=10, le=120, description="Max time for signal collection in seconds")

    # ─────────────────────────────────────────────────────────────────────
    # Demo Mode
    # ─────────────────────────────────────────────────────────────────────
    demo_mode: bool = Field(False, alias="DEMO_MODE")
    demo_scenario: str = Field("a", alias="DEMO_SCENARIO")
    simulate_weather_failure: bool = Field(False, alias="SIMULATE_WEATHER_FAILURE")
    simulate_traffic_failure: bool = Field(False, alias="SIMULATE_TRAFFIC_FAILURE")
    simulate_gemini_failure: bool = Field(False, alias="SIMULATE_GEMINI_FAILURE")

    # ─────────────────────────────────────────────────────────────────────
    # Monitoring & Alerting
    # ─────────────────────────────────────────────────────────────────────
    health_check_enabled: bool = Field(True, alias="HEALTH_CHECK_ENABLED")
    metrics_enabled: bool = Field(True, alias="METRICS_ENABLED")
    alert_threshold_ms: int = Field(15000, alias="ALERT_THRESHOLD_MS")

    # ─────────────────────────────────────────────────────────────────────
    # Database (Optional)
    # ─────────────────────────────────────────────────────────────────────
    database_url: Optional[str] = Field(None, alias="DATABASE_URL")

    # ─────────────────────────────────────────────────────────────────────
    # Security
    # ─────────────────────────────────────────────────────────────────────
    cors_origins: str = Field(
        "http://localhost:3000,http://localhost:8000,http://127.0.0.1:3000,http://127.0.0.1:8000",
        alias="CORS_ORIGINS",
        description="Comma-separated list of allowed origins. Use * only for development."
    )
    max_request_size_mb: int = Field(10, alias="MAX_REQUEST_SIZE_MB", ge=1, le=500)
    api_key_validation_enabled: bool = Field(False, alias="API_KEY_VALIDATION_ENABLED")
    api_key_header: str = Field("X-API-Key", alias="API_KEY_HEADER")

    # ─────────────────────────────────────────────────────────────────────
    # Logging
    # ─────────────────────────────────────────────────────────────────────
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    log_file: str = Field("./logs/app.log", alias="LOG_FILE")
    log_max_size: int = Field(100, alias="LOG_MAX_SIZE")
    log_backup_count: int = Field(5, alias="LOG_BACKUP_COUNT")
    
    # ─────────────────────────────────────────────────────────────────────
    # Production Deployment Settings (CRITICAL)
    # ─────────────────────────────────────────────────────────────────────
    enable_request_validation: bool = Field(True, alias="ENABLE_REQUEST_VALIDATION", description="Validate all requests for size/format")
    enable_cache_invalidation: bool = Field(True, alias="ENABLE_CACHE_INVALIDATION", description="Invalidate cache on POST/PUT/DELETE")
    strict_error_handling: bool = Field(False, alias="STRICT_ERROR_HANDLING", description="Raise errors immediately instead of degrading gracefully")

    # ─────────────────────────────────────────────────────────────────────
    # Authentication
    # ─────────────────────────────────────────────────────────────────────
    smtp_email: Optional[str] = Field(None, alias="SMTP_EMAIL")
    smtp_password: Optional[str] = Field(None, alias="SMTP_PASSWORD")
    jwt_secret: str = Field("ciro-default-secret-change-me", alias="JWT_SECRET")

    class Config:
        env_file = ".env"
        case_sensitive = False
        populated_by_name = True
        extra = "ignore"


# Global settings instance
settings = Settings()


# ═════════════════════════════════════════════════════════════════════════════
# Environment Validation & Startup Checks
# ═════════════════════════════════════════════════════════════════════════════

def validate_environment() -> dict:
    """
    Validate environment configuration and return status.

    Returns:
        Dict with keys: environment, mode, api_keys, warnings, errors
    """
    status = {
        "environment": determine_environment(),
        "mode": "PRODUCTION" if settings.production_mode else "DEVELOPMENT",
        "api_keys": {
            "gemini": "[OK] Configured" if settings.gemini_api_key else "[X] MISSING (REQUIRED)",
            "openweather": "[OK] Configured" if settings.openweather_api_key else "[!] Not configured (using mock)",
            "tomtom": "[OK] Configured" if settings.tomtom_api_key else "[!] Not configured (using mock)",
            "firebase": "[OK] Configured" if settings.firebase_project_id else "[!] Not configured (using in-memory)",
        },
        "features": {
            "rate_limiting": "[OK] Enabled" if settings.rate_limit_enabled else "[X] Disabled",
            "caching": "[OK] Enabled" if settings.cache_enabled else "[X] Disabled",
            "detailed_logging": "[OK] Enabled" if settings.detailed_logging else "[X] Disabled",
        },
        "warnings": [],
        "errors": [],
    }

    # Warnings
    if not settings.openweather_api_key:
        status["warnings"].append("OpenWeather API key not set - will use mock weather data")
    if not settings.tomtom_api_key:
        status["warnings"].append("TomTom API key not set - will use mock traffic data")
    if not settings.firebase_project_id:
        status["warnings"].append("Firebase not configured - using in-memory store (data lost on restart)")

    # Errors
    if not settings.gemini_api_key:
        status["errors"].append("GEMINI_API_KEY is required!")
    if settings.production_mode and not settings.firebase_project_id:
        status["errors"].append("Production mode requires Firebase configuration")
    if settings.production_mode and not settings.openweather_api_key:
        status["errors"].append("Production mode requires OpenWeather API key")
    if settings.production_mode and not settings.tomtom_api_key:
        status["errors"].append("Production mode requires TomTom API key")

    return status


def determine_environment() -> str:
    """Determine deployment environment."""
    if os.getenv("PRODUCTION_MODE") == "true":
        return "PRODUCTION"
    elif os.getenv("STAGING_MODE") == "true":
        return "STAGING"
    return "DEVELOPMENT"


def print_startup_banner():
    """Print startup banner with configuration info."""
    status = validate_environment()

    banner = f"""
========================================================================
                CIRO Backend Startup Configuration
========================================================================
  Environment: {status['environment']}
  Mode:        {status['mode']}
------------------------------------------------------------------------
  API KEYS:
    - Gemini:      {status['api_keys']['gemini']}
    - OpenWeather: {status['api_keys']['openweather']}
    - TomTom:      {status['api_keys']['tomtom']}
    - Firebase:    {status['api_keys']['firebase']}
------------------------------------------------------------------------
  FEATURES:
    - Rate Limiting:   {status['features']['rate_limiting']}
    - Caching:         {status['features']['caching']}
    - Detailed Logging:{status['features']['detailed_logging']}
"""

    if status["warnings"]:
        banner += "------------------------------------------------------------------------\n"
        banner += "  WARNINGS:\n"
        for warning in status["warnings"]:
            banner += f"    [!] {warning}\n"

    if status["errors"]:
        banner += "------------------------------------------------------------------------\n"
        banner += "  ERRORS:\n"
        for error in status["errors"]:
            banner += f"    [X] {error}\n"

    banner += "========================================================================\n"

    print(banner)

    # Raise error if critical issues in production
    if status["errors"] and settings.production_mode:
        raise RuntimeError(f"Configuration errors detected: {status['errors']}")
    elif status["errors"]:
        print("[WARNING] Issues detected but running in dev mode - some features may not work.")


if __name__ == "__main__":
    print_startup_banner()
