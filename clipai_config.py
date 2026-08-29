"""Secure configuration loading with validation and secrets management."""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent

# ─── Sensitive pattern sanitization ───
_SENSITIVE_PATTERNS = [
    (re.compile(r'(api[_-]?key|key|secret|token|password|authorization)["\']?\s*[:=]\s*["\']?[a-zA-Z0-9_\-]{10,}'),
     r'\1=<REDACTED>'),
    (re.compile(r'(sk|pk|whsec|re|ya|AIza|GH[PS]O|glpat|ghp|gho|ghu|ghs|ghr|xox[baprs]-[a-zA-Z0-9]+)'),
     r'<REDACTED>'),
]


def sanitize_error_message(message: str) -> str:
    """Remove secrets from error messages before logging."""
    for pattern, replacement in _SENSITIVE_PATTERNS:
        message = pattern.sub(replacement, message, flags=re.IGNORECASE)
    return message


# ─── Security constants ───
class SecurityConfig:
    # Rate limits
    MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "300"))
    MAX_API_CALLS_PER_HOUR = {
        "free": 100,
        "pro": 500,
        "pro_plus": 2000,
    }
    MAX_PROCESS_PER_IP_PER_HOUR = 8
    MAX_JOB_QUEUE_SIZE = 10
    JOB_MAX_AGE_SECONDS = 24 * 60 * 60

    # File upload
    ALLOWED_EXTENSIONS: Set[str] = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
    ALLOWED_MIME_TYPES: Set[str] = {
        "video/mp4", "video/quicktime", "video/x-m4v", "video/webm", "video/x-matroska"
    }
    MAX_FILENAME_LENGTH = 255

    # API Spend caps (monthly)
    WHISPER_MAX_MINUTES_PER_MONTH = int(os.environ.get("WHISPER_MAX_MINUTES_PER_MONTH", "10000"))
    GOOGLE_TRANSLATE_MAX_CHARS_PER_MONTH = int(os.environ.get("GOOGLE_TRANSLATE_MAX_CHARS_PER_MONTH", "5000000"))
    PIPER_TTS_MAX_CHARS_PER_MONTH = int(os.environ.get("PIPER_TTS_MAX_CHARS_PER_MONTH", "1000000"))
    STRIPE_MAX_WEBHOOKS_PER_HOUR = int(os.environ.get("STRIPE_MAX_WEBHOOKS_PER_HOUR", "100"))

    # Security headers
    CSP_POLICY = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://js.stripe.com https://www.google.com https://www.gstatic.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://api.stripe.com https://accounts.google.com https://oauth2.googleapis.com; "
        "frame-src https://js.stripe.com https://hooks.stripe.com; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none';"
    )
    HSTS_MAX_AGE = 31536000  # 1 year

    # CORS
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    # Cookie settings
    COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
    COOKIE_SAMESITE = "lax"
    COOKIE_HTTPONLY = True

    # Environment
    IS_PRODUCTION = os.environ.get("ENVIRONMENT", "development").lower() == "production"
    DEBUG = os.environ.get("DEBUG", "false").lower() == "true" and not IS_PRODUCTION


@dataclass
class StripeConfig:
    secret_key: str
    price_id: str
    price_id_plus: str
    webhook_secret: str

    @classmethod
    def from_env(cls) -> "StripeConfig":
        return cls(
            secret_key=os.environ.get("STRIPE_SECRET_KEY", ""),
            price_id=os.environ.get("STRIPE_PRICE_ID", ""),
            price_id_plus=os.environ.get("STRIPE_PRICE_ID_PLUS", ""),
            webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
        )

    def validate(self) -> List[str]:
        errors = []
        if not self.secret_key or self.secret_key == "sk_test_REPLACE_ME":
            errors.append("STRIPE_SECRET_KEY not configured")
        if not self.price_id or self.price_id == "price_REPLACE_ME":
            errors.append("STRIPE_PRICE_ID not configured")
        if not self.price_id_plus or self.price_id_plus == "price_REPLACE_ME_PLUS":
            errors.append("STRIPE_PRICE_ID_PLUS not configured")
        if not self.webhook_secret or self.webhook_secret == "whsec_REPLACE_ME":
            errors.append("STRIPE_WEBHOOK_SECRET not configured")
        return errors


@dataclass
class GoogleOAuthConfig:
    client_id: str
    client_secret: str
    session_secret_key: str

    @classmethod
    def from_env(cls) -> "GoogleOAuthConfig":
        return cls(
            client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
            client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            session_secret_key=os.environ.get("SESSION_SECRET_KEY", ""),
        )

    def validate(self) -> List[str]:
        errors = []
        if not self.client_id or self.client_id == "REPLACE_ME.apps.googleusercontent.com":
            errors.append("GOOGLE_CLIENT_ID not configured")
        if not self.client_secret or self.client_secret == "REPLACE_ME":
            errors.append("GOOGLE_CLIENT_SECRET not configured")
        if not self.session_secret_key or self.session_secret_key == "dev-only-insecure-secret-REPLACE_ME":
            errors.append("SESSION_SECRET_KEY not configured (generate with: openssl rand -hex 32)")
        if len(self.session_secret_key) < 32:
            errors.append("SESSION_SECRET_KEY must be at least 32 characters")
        return errors

    @property
    def is_configured(self) -> bool:
        return (self.client_id and self.client_id != "REPLACE_ME.apps.googleusercontent.com"
                and self.client_secret and self.client_secret != "REPLACE_ME")


@dataclass
class EmailConfig:
    resend_api_key: str
    from_email: str

    @classmethod
    def from_env(cls) -> "EmailConfig":
        return cls(
            resend_api_key=os.environ.get("RESEND_API_KEY", ""),
            from_email=os.environ.get("EMAIL_FROM", "Peakcut <onboarding@resend.dev>"),
        )

    def validate(self) -> List[str]:
        errors = []
        if not self.resend_api_key or self.resend_api_key == "re_REPLACE_ME":
            errors.append("RESEND_API_KEY not configured")
        return errors

    @property
    def is_configured(self) -> bool:
        return self.resend_api_key and self.resend_api_key != "re_REPLACE_ME"


@dataclass
class AdsenseConfig:
    publisher_id: str

    @classmethod
    def from_env(cls) -> "AdsenseConfig":
        return cls(publisher_id=os.environ.get("ADSENSE_PUBLISHER_ID", ""))

    def validate(self) -> List[str]:
        errors = []
        if not self.publisher_id or self.publisher_id == "ca-pub-5158161193547085":
            errors.append("ADSENSE_PUBLISHER_ID not configured")
        return errors


@dataclass
class AppConfig:
    site_url: str
    free_limit: int
    contact_email: str
    whisper_model: str

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            site_url=os.environ.get("SITE_URL", "http://localhost:8000").rstrip("/"),
            free_limit=int(os.environ.get("FREE_LIMIT", "5")),
            contact_email=os.environ.get("CONTACT_EMAIL", "support@peakcut.example"),
            whisper_model=os.environ.get("WHISPER_MODEL", "tiny"),
        )

    def validate(self) -> List[str]:
        errors = []
        if not self.site_url.startswith("http"):
            errors.append("SITE_URL must start with http:// or https://")
        if self.free_limit < 0:
            errors.append("FREE_LIMIT must be non-negative")
        if "@" not in self.contact_email:
            errors.append("CONTACT_EMAIL must be a valid email")
        if self.whisper_model not in ("tiny", "base", "small", "medium", "large-v3"):
            errors.append("WHISPER_MODEL must be one of: tiny, base, small, medium, large-v3")
        return errors


@dataclass
class Config:
    """Complete application configuration with validation."""
    stripe: StripeConfig
    google_oauth: GoogleOAuthConfig
    email: EmailConfig
    adsense: AdsenseConfig
    app: AppConfig
    security: SecurityConfig

    @classmethod
    def load(cls) -> "Config":
        cfg = cls(
            stripe=StripeConfig.from_env(),
            google_oauth=GoogleOAuthConfig.from_env(),
            email=EmailConfig.from_env(),
            adsense=AdsenseConfig.from_env(),
            app=AppConfig.from_env(),
            security=SecurityConfig(),
        )
        errors = cfg.validate()
        if errors:
            for err in errors:
                logger.error("Config validation failed: %s", err)
            if cfg.security.IS_PRODUCTION:
                raise RuntimeError("Configuration validation failed: " + "; ".join(errors))
        else:
            logger.info("Configuration validated successfully")
        return cfg

    def validate(self) -> List[str]:
        errors = []
        errors.extend(self.stripe.validate())
        errors.extend(self.google_oauth.validate())
        errors.extend(self.email.validate())
        errors.extend(self.adsense.validate())
        errors.extend(self.app.validate())

        # Cross-validation
        if self.google_oauth.is_configured and not self.email.is_configured:
            logger.warning("Google OAuth configured but email not configured - notifications will not work")

        if self.security.IS_PRODUCTION:
            if not self.app.site_url.startswith("https://"):
                errors.append("SITE_URL must use HTTPS in production")
            if not self.security.COOKIE_SECURE:
                errors.append("COOKIE_SECURE must be true in production")

        return errors


# Global config instance (loaded once at startup)
app_config: Config = Config.load()

# Backwards compatibility exports
STRIPE_SECRET_KEY = app_config.stripe.secret_key
STRIPE_PRICE_ID = app_config.stripe.price_id
STRIPE_PRICE_ID_PLUS = app_config.stripe.price_id_plus
STRIPE_WEBHOOK_SECRET = app_config.stripe.webhook_secret
ADSENSE_PUBLISHER_ID = app_config.adsense.publisher_id
GOOGLE_CLIENT_ID = app_config.google_oauth.client_id
GOOGLE_CLIENT_SECRET = app_config.google_oauth.client_secret
SESSION_SECRET_KEY = app_config.google_oauth.session_secret_key
GOOGLE_SIGNIN_CONFIGURED = app_config.google_oauth.is_configured
RESEND_API_KEY = app_config.email.resend_api_key
EMAIL_FROM = app_config.email.from_email
EMAIL_CONFIGURED = app_config.email.is_configured
CONTACT_EMAIL = app_config.app.contact_email
SITE_URL = app_config.app.site_url
FREE_LIMIT = app_config.app.free_limit
MAX_UPLOAD_MB = app_config.security.MAX_UPLOAD_MB
ALLOWED_EXTENSIONS = app_config.security.ALLOWED_EXTENSIONS
WHISPER_MODEL = app_config.app.whisper_model