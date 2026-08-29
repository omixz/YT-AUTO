"""Enhanced OAuth authentication with token validation, refresh, and error handling."""
from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from urllib.parse import urlencode

import httpx
import jwt
from itsdangerous import BadSignature, URLSafeTimedSerializer
from jwt import PyJWKClient

from clipai_config import app_config as config, sanitize_error_message

logger = logging.getLogger("clipai.auth")

# ─── Constants ──────────────────────────────────────────────────────────────
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
ACCOUNT_COOKIE = "clipai_account"
STATE_COOKIE = "clipai_oauth_state"
CSRF_COOKIE = "clipai_csrf"
ACCOUNT_MAX_AGE = 60 * 60 * 24 * 365  # 1 year
STATE_MAX_AGE = 600  # 10 minutes

# Token validation
TOKEN_LEEWAY = 60  # seconds of clock skew tolerance
MAX_TOKEN_AGE = 3600  # reject tokens older than 1 hour (should be ~5 min from Google)

_discovery_cache: Dict = {"data": None, "at": 0.0}
_jwks_client: Optional[PyJWKClient] = None
_serializer: Optional[URLSafeTimedSerializer] = None


def _get_serializer() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        _serializer = URLSafeTimedSerializer(config.google_oauth.session_secret_key, salt="clipai-account-v1")
    return _serializer


def _discovery() -> Dict:
    """Fetch and cache Google's OpenID Connect discovery document."""
    global _discovery_cache
    now = time.time()
    if not _discovery_cache["data"] or now - _discovery_cache["at"] > 3600:
        try:
            resp = httpx.get(GOOGLE_DISCOVERY_URL, timeout=10)
            resp.raise_for_status()
            _discovery_cache = {"data": resp.json(), "at": now}
        except httpx.HTTPError as e:
            logger.error("Failed to fetch Google discovery document: %s", sanitize_error_message(str(e)))
            raise RuntimeError("Authentication service temporarily unavailable")
    return _discovery_cache["data"]


def _jwks() -> PyJWKClient:
    """Get or create JWKS client for token verification."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(_discovery()["jwks_uri"])
    return _jwks_client


# ─── Data Classes ───────────────────────────────────────────────────────────
@dataclass
class AuthResult:
    """Result of an authentication operation."""
    success: bool
    account: Optional[Dict] = None
    error: Optional[str] = None
    redirect_url: Optional[str] = None


@dataclass
class TokenClaims:
    """Validated ID token claims."""
    sub: str
    email: str
    email_verified: bool
    name: Optional[str] = None
    picture: Optional[str] = None
    iat: int = 0
    exp: int = 0


# ─── State Management (CSRF Protection) ─────────────────────────────────────
_state_store: Dict[str, Tuple[float, str]] = {}  # state -> (timestamp, redirect_url)
_state_lock = __import__("threading").Lock()


def new_state(redirect_url: str = "/") -> str:
    """Generate a new OAuth state parameter with associated redirect."""
    state = secrets.token_urlsafe(32)
    with _state_lock:
        _cleanup_expired_states()
        _state_store[state] = (time.time(), redirect_url)
    return state


def consume_state(state: str) -> Optional[str]:
    """Consume and validate a state parameter, returning the redirect URL."""
    with _state_lock:
        _cleanup_expired_states()
        if state in _state_store:
            _, redirect_url = _state_store.pop(state)
            return redirect_url
    return None


def _cleanup_expired_states() -> None:
    """Remove expired state entries."""
    now = time.time()
    expired = [s for s, (ts, _) in _state_store.items() if now - ts > STATE_MAX_AGE]
    for s in expired:
        _state_store.pop(s, None)


# ─── OAuth Flow ─────────────────────────────────────────────────────────────
def build_login_url(redirect_uri: str, state: str) -> str:
    """Build the Google OAuth authorization URL."""
    discovery = _discovery()
    params = {
        "client_id": config.google_oauth.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
        "access_type": "offline",
    }
    return f"{discovery['authorization_endpoint']}?{urlencode(params)}"


class OAuthError(Exception):
    """OAuth-specific error with user-friendly message."""
    def __init__(self, message: str, user_message: str, status_code: int = 400):
        super().__init__(message)
        self.user_message = user_message
        self.status_code = status_code


def exchange_code_for_claims(code: str, redirect_uri: str) -> TokenClaims:
    """Exchange authorization code for ID token and verify it."""
    discovery = _discovery()

    try:
        # Exchange code for tokens
        token_resp = httpx.post(
            discovery["token_endpoint"],
            data={
                "code": code,
                "client_id": config.google_oauth.client_id,
                "client_secret": config.google_oauth.client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()

        id_token = token_data.get("id_token")
        if not id_token:
            raise OAuthError("No ID token in response", "Authentication failed - please try again")

        # Verify ID token signature and claims
        signing_key = _jwks().get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=config.google_oauth.client_id,
            issuer=["https://accounts.google.com", "accounts.google.com"],
            leeway=TOKEN_LEEWAY,
            options={"require": ["exp", "iat", "aud", "iss", "sub", "email", "email_verified"]},
        )

        # Additional validation
        now = int(time.time())
        if claims.get("iat", 0) < now - MAX_TOKEN_AGE:
            raise OAuthError("Token too old", "Authentication token expired - please sign in again")

        if not claims.get("email_verified", False):
            raise OAuthError("Email not verified", "Please verify your email with Google first", 403)

        return TokenClaims(
            sub=claims["sub"],
            email=claims["email"],
            email_verified=claims["email_verified"],
            name=claims.get("name"),
            picture=claims.get("picture"),
            iat=claims["iat"],
            exp=claims["exp"],
        )

    except jwt.ExpiredSignatureError:
        raise OAuthError("Token expired", "Authentication token expired - please sign in again")
    except jwt.InvalidAudienceError:
        raise OAuthError("Invalid audience", "Authentication configuration error")
    except jwt.InvalidIssuerError:
        raise OAuthError("Invalid issuer", "Authentication token from untrusted source")
    except jwt.InvalidTokenError as e:
        raise OAuthError(f"Invalid token: {e}", "Invalid authentication token - please try again")
    except httpx.HTTPStatusError as e:
        logger.error("Token exchange failed: %s", sanitize_error_message(e.response.text))
        raise OAuthError("Token exchange failed", "Authentication service error - please try again")
    except httpx.RequestError as e:
        logger.error("Token exchange request failed: %s", sanitize_error_message(str(e)))
        raise OAuthError("Network error", "Unable to reach authentication service")


# ─── Account Cookie Management ──────────────────────────────────────────────
def sign_account_cookie(claims: TokenClaims) -> str:
    """Create a signed account cookie."""
    return _get_serializer().dumps({
        "sub": claims.sub,
        "email": claims.email,
        "name": claims.name,
        "picture": claims.picture,
        "iat": claims.iat,
    })


def read_account_cookie(token: str) -> Optional[Dict]:
    """Read and validate account cookie."""
    if not token:
        return None
    try:
        data = _get_serializer().loads(token, max_age=ACCOUNT_MAX_AGE)
        return {
            "sub": data["sub"],
            "email": data["email"],
            "name": data.get("name"),
            "picture": data.get("picture"),
        }
    except BadSignature:
        logger.warning("Invalid account cookie signature")
        return None
    except Exception as e:
        logger.exception("Failed to parse account cookie: %s", sanitize_error_message(str(e)))
        return None


def revoke_account_cookie(response) -> None:
    """Securely delete the account cookie."""
    from clipai_security import delete_secure_cookie
    delete_secure_cookie(response, ACCOUNT_COOKIE)


# ─── CSRF Token Management ──────────────────────────────────────────────────
_csrf_tokens: Dict[str, float] = {}
_csrf_lock = __import__("threading").Lock()
CSRF_TTL = 3600  # 1 hour


def generate_csrf_token(session_id: str) -> str:
    """Generate a CSRF token for a session."""
    token = secrets.token_urlsafe(32)
    with _csrf_lock:
        _cleanup_csrf_tokens()
        _csrf_tokens[f"{session_id}:{token}"] = time.time()
    return token


def validate_csrf_token(session_id: str, token: str) -> bool:
    """Validate and consume a CSRF token."""
    with _csrf_lock:
        _cleanup_csrf_tokens()
        key = f"{session_id}:{token}"
        if key in _csrf_tokens:
            del _csrf_tokens[key]
            return True
    return False


def _cleanup_csrf_tokens() -> None:
    """Remove expired CSRF tokens."""
    now = time.time()
    expired = [k for k, ts in _csrf_tokens.items() if now - ts > CSRF_TTL]
    for k in expired:
        _csrf_tokens.pop(k, None)


def get_session_id(request) -> str:
    """Get or create session ID from cookie."""
    session_id = request.cookies.get("clipai_session")
    if not session_id:
        session_id = secrets.token_urlsafe(16)
    return session_id


# ─── Token Refresh (for long-lived sessions) ────────────────────────────────
async def refresh_google_token(refresh_token: str) -> Optional[Dict]:
    """Refresh an expired access token using refresh token."""
    discovery = _discovery()
    try:
        resp = await httpx.AsyncClient().post(
            discovery["token_endpoint"],
            data={
                "client_id": config.google_oauth.client_id,
                "client_secret": config.google_oauth.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.error("Token refresh failed: %s", sanitize_error_message(str(e)))
        return None


# ─── Validation Helpers ─────────────────────────────────────────────────────
def is_google_configured() -> bool:
    """Check if Google OAuth is properly configured."""
    return config.google_oauth.is_configured


def validate_redirect_uri(redirect_uri: str) -> bool:
    """Validate redirect URI against allowed patterns."""
    if not redirect_uri.startswith(config.app.site_url):
        return False
    # Prevent open redirects
    if "//" in redirect_uri[len(config.app.site_url):]:
        return False
    return True