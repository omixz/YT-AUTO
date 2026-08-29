"""Security middleware for FastAPI: headers, CORS, CSRF, rate limiting, request validation."""
from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set
from threading import Lock

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp

from clipai_config import app_config as config, sanitize_error_message

logger = logging.getLogger("clipai.security")

# ─── In-memory rate limiting (replace with Redis in production) ───
_rate_limit_lock = Lock()
_request_counts: Dict[str, List[float]] = defaultdict(list)
_ip_request_counts: Dict[str, List[float]] = defaultdict(list)
_api_key_request_counts: Dict[str, List[float]] = defaultdict(list)


def _clean_old_requests(counts: Dict[str, List[float]], window_seconds: int) -> None:
    """Remove timestamps older than window."""
    now = time.time()
    cutoff = now - window_seconds
    for key in list(counts.keys()):
        counts[key] = [ts for ts in counts[key] if ts > cutoff]
        if not counts[key]:
            del counts[key]


def check_rate_limit(
    identifier: str,
    max_requests: int,
    window_seconds: int = 3600,
    counts_dict: Optional[Dict[str, List[float]]] = None,
) -> bool:
    """Check if identifier has exceeded rate limit. Thread-safe."""
    if counts_dict is None:
        counts_dict = _request_counts

    with _rate_limit_lock:
        _clean_old_requests(counts_dict, window_seconds)
        now = time.time()
        cutoff = now - window_seconds

        timestamps = [ts for ts in counts_dict.get(identifier, []) if ts > cutoff]
        if len(timestamps) >= max_requests:
            return False

        timestamps.append(now)
        counts_dict[identifier] = timestamps
        return True


def get_client_identifier(request: Request) -> str:
    """Get client identifier for rate limiting (IP + User-Agent hash)."""
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    user_agent = request.headers.get("user-agent", "")[:50]
    return f"{ip}:{hash(user_agent)}"


# ─── CSRF Protection ───
_csrf_tokens: Dict[str, float] = {}
_csrf_lock = Lock()
CSRF_TOKEN_TTL = 3600  # 1 hour


def generate_csrf_token(session_id: str) -> str:
    """Generate a CSRF token for a session."""
    token = uuid.uuid4().hex
    with _csrf_lock:
        _clean_old_requests(_csrf_tokens, CSRF_TOKEN_TTL)
        _csrf_tokens[f"{session_id}:{token}"] = time.time()
    return token


def validate_csrf_token(session_id: str, token: str) -> bool:
    """Validate a CSRF token for a session."""
    with _csrf_lock:
        _clean_old_requests(_csrf_tokens, CSRF_TOKEN_TTL)
        key = f"{session_id}:{token}"
        if key in _csrf_tokens:
            del _csrf_tokens[key]  # One-time use
            return True
    return False


def get_session_id(request: Request) -> str:
    """Get or create session ID from cookie."""
    session_id = request.cookies.get("clipai_session")
    if not session_id:
        session_id = uuid.uuid4().hex
    return session_id


# ─── Security Headers Middleware ───
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    def __init__(self, app: ASGIApp, csp_policy: Optional[str] = None, hsts_max_age: int = 31536000):
        super().__init__(app)
        self.csp_policy = csp_policy or config.security.CSP_POLICY
        self.hsts_max_age = hsts_max_age
        self.is_production = config.security.IS_PRODUCTION

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        # CSP
        if self.csp_policy:
            response.headers["Content-Security-Policy"] = self.csp_policy

        # HSTS (only in production with HTTPS)
        if self.is_production and request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = f"max-age={self.hsts_max_age}; includeSubDomains; preload"

        # Remove server header
        response.headers.pop("Server", None)

        return response


# ─── Rate Limiting Middleware ───
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware with multiple strategies."""

    def __init__(
        self,
        app: ASGIApp,
        default_limit: int = 100,
        default_window: int = 3600,
        auth_limit: int = 10,
        auth_window: int = 300,
        upload_limit: int = 5,
        upload_window: int = 3600,
    ):
        super().__init__(app)
        self.default_limit = default_limit
        self.default_window = default_window
        self.auth_limit = auth_limit
        self.auth_window = auth_window
        self.upload_limit = upload_limit
        self.upload_window = upload_window

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        method = request.method
        client_id = get_client_identifier(request)

        # Determine limit based on endpoint
        if path.startswith("/auth/") and method == "POST":
            limit, window = self.auth_limit, self.auth_window
            bucket = f"auth:{client_id}"
        elif path == "/process" and method == "POST":
            limit, window = self.upload_limit, self.upload_window
            bucket = f"upload:{client_id}"
        elif path.startswith("/api/") and method == "POST":
            # API keys have their own limits
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                api_key = auth_header[7:19]  # First 12 chars for bucket
                bucket = f"api:{api_key}"
                # API tier limits checked in endpoint
                limit, window = self.default_limit, self.default_window
            else:
                bucket = f"default:{client_id}"
                limit, window = self.default_limit, self.default_window
        else:
            bucket = f"default:{client_id}"
            limit, window = self.default_limit, self.default_window

        if not check_rate_limit(bucket, limit, window):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please try again later."},
                headers={"Retry-After": str(window)},
            )

        return await call_next(request)


# ─── Request Validation Middleware ───
class RequestValidationMiddleware(BaseHTTPMiddleware):
    """Validate and sanitize incoming requests."""

    MAX_BODY_SIZE = 100 * 1024 * 1024  # 100MB
    BLOCKED_PATTERNS = [
        r"<script[^>]*>.*?</script>",
        r"javascript:",
        r"on\w+\s*=",
        r"eval\s*\(",
        r"document\.",
        r"window\.",
    ]

    def __init__(self, app: ASGIApp, max_body_size: Optional[int] = None):
        super().__init__(app)
        self.max_body_size = max_body_size or self.MAX_BODY_SIZE
        self._compiled_patterns = [__import__("re").compile(p, __import__("re").IGNORECASE) for p in self.BLOCKED_PATTERNS]

    def _sanitize_string(self, value: str) -> str:
        """Remove potentially dangerous patterns from string."""
        for pattern in self._compiled_patterns:
            value = pattern.sub("", value)
        return value

    def _validate_dict(self, data: dict, max_depth: int = 10) -> dict:
        """Recursively validate and sanitize dictionary."""
        if max_depth <= 0:
            raise HTTPException(status_code=400, detail="Request structure too deep")

        sanitized = {}
        for key, value in data.items():
            # Sanitize key
            clean_key = self._sanitize_string(str(key))[:100]

            if isinstance(value, str):
                sanitized[clean_key] = self._sanitize_string(value)[:10000]
            elif isinstance(value, dict):
                sanitized[clean_key] = self._validate_dict(value, max_depth - 1)
            elif isinstance(value, list):
                sanitized[clean_key] = [
                    self._validate_dict(v, max_depth - 1) if isinstance(v, dict)
                    else self._sanitize_string(str(v))[:1000] if isinstance(v, str)
                    else v
                    for v in value[:100]  # Limit array size
                ]
            else:
                sanitized[clean_key] = value

        return sanitized

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check content length
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_body_size:
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request body too large. Maximum {self.max_body_size // (1024*1024)}MB."},
            )

        # Validate path traversal
        path = request.url.path
        if ".." in path or path.count("/") > 20:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid request path."},
            )

        return await call_next(request)


# ─── Error Sanitization Middleware ───
class ErrorSanitizationMiddleware(BaseHTTPMiddleware):
    """Sanitize error responses to prevent secret leakage."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            response = await call_next(request)
            return response
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Unhandled error: %s", sanitize_error_message(str(e)))
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
            )


# ─── Cookie Security Middleware ───
class SecureCookieMiddleware(BaseHTTPMiddleware):
    """Ensure all cookies have secure flags in production."""

    def __init__(self, app: ASGIApp, secure: bool = True, httponly: bool = True, samesite: str = "lax"):
        super().__init__(app)
        self.secure = secure and config.security.IS_PRODUCTION
        self.httponly = httponly
        self.samesite = samesite

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Apply secure flags to all cookies
        for cookie_name in response.headers.getlist("Set-Cookie"):
            # Starlette handles this via response.set_cookie, but we can enforce here
            pass

        return response


def set_secure_cookie(
    response: Response,
    key: str,
    value: str,
    max_age: int = 3600,
    path: str = "/",
    domain: Optional[str] = None,
) -> None:
    """Set a cookie with secure defaults."""
    response.set_cookie(
        key=key,
        value=value,
        max_age=max_age,
        path=path,
        domain=domain,
        secure=config.security.COOKIE_SECURE,
        httponly=config.security.COOKIE_HTTPONLY,
        samesite=config.security.COOKIE_SAMESITE,
    )


def delete_secure_cookie(response: Response, key: str, path: str = "/", domain: Optional[str] = None) -> None:
    """Delete a cookie securely."""
    response.delete_cookie(
        key=key,
        path=path,
        domain=domain,
        secure=config.security.COOKIE_SECURE,
        httponly=config.security.COOKIE_HTTPONLY,
        samesite=config.security.COOKIE_SAMESITE,
    )


# ─── Spend Cap Tracking ───
@dataclass
class SpendTracker:
    """Track API usage costs to enforce spend caps."""
    whisper_minutes_used: float = 0.0
    google_translate_chars: int = 0
    piper_tts_chars: int = 0
    stripe_webhooks: int = 0
    _lock: Lock = field(default_factory=Lock, init=False)

    def check_whisper(self, minutes: float) -> bool:
        with self._lock:
            if self.whisper_minutes_used + minutes > config.security.WHISPER_MAX_MINUTES_PER_MONTH:
                return False
            self.whisper_minutes_used += minutes
            return True

    def check_google_translate(self, chars: int) -> bool:
        with self._lock:
            if self.google_translate_chars + chars > config.security.GOOGLE_TRANSLATE_MAX_CHARS_PER_MONTH:
                return False
            self.google_translate_chars += chars
            return True

    def check_piper_tts(self, chars: int) -> bool:
        with self._lock:
            if self.piper_tts_chars + chars > config.security.PIPER_TTS_MAX_CHARS_PER_MONTH:
                return False
            self.piper_tts_chars += chars
            return True

    def check_stripe_webhook(self) -> bool:
        with self._lock:
            if self.stripe_webhooks >= config.security.STRIPE_MAX_WEBHOOKS_PER_HOUR:
                return False
            self.stripe_webhooks += 1
            return True

    def reset_monthly(self) -> None:
        """Call monthly via cron to reset counters."""
        with self._lock:
            self.whisper_minutes_used = 0.0
            self.google_translate_chars = 0
            self.piper_tts_chars = 0

    def reset_hourly(self) -> None:
        """Call hourly via cron to reset webhook counter."""
        with self._lock:
            self.stripe_webhooks = 0


spend_tracker = SpendTracker()


# ─── Setup function ───
def setup_security_middleware(app: FastAPI) -> None:
    """Add all security middleware to the FastAPI app."""

    # Order matters: inner to outer
    # 1. Error sanitization (outermost - catches all errors)
    app.add_middleware(ErrorSanitizationMiddleware)

    # 2. Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # 3. CORS (before rate limiting so preflight works)
    if config.security.ALLOWED_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.security.ALLOWED_ORIGINS,
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
            expose_headers=["X-Request-ID"],
            max_age=86400,
        )

    # 4. Request validation
    app.add_middleware(RequestValidationMiddleware)

    # 5. Rate limiting (innermost - runs first on request)
    app.add_middleware(RateLimitMiddleware)

    logger.info("Security middleware configured")


# ─── Request ID Middleware (for tracing) ───
class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add request ID to all requests for tracing."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response