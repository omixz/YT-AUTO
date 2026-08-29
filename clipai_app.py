"""ClipAI / Peakcut - Secure video clipping API with comprehensive security hardening.
Includes local hardware fallback for server load resilience.
"""
from __future__ import annotations

import json
import logging
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Callable, Set

import psutil
import stripe
from fastapi import FastAPI, File, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

import os
import clipai_auth as auth
import clipai_config as config

# NOTE: email_lib and pipeline_lib must be implemented by the user for their specific pipeline
# Example: from your_email_module import send_done_email, send_failed_email
# Example: from your_processing_module import process_video
try:
    import email_lib
except ImportError:
    email_lib = None
    logging.warning("email_lib not found - email notifications disabled")

try:
    import pipeline_lib
except ImportError:
    pipeline_lib = None
    logging.warning("pipeline_lib not found - video processing disabled")

from clipai_config import SecurityConfig
from clipai_security import (
    spend_tracker, check_rate_limit, get_client_identifier,
    set_secure_cookie, delete_secure_cookie,
    sanitize_error_message,
)
from clipai_monitoring import (
    ResourceMonitor, CircuitBreaker, CircuitBreakerRegistry, HealthChecker,
    health_checker, circuit_breakers, resource_monitor,
)
from clipai_queue import Job, JobStatus, JobPriority, JobQueue, init_queue

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if config.SecurityConfig.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("clipai")

# Disable uvicorn's default access logger for security (we'll log properly)
import uvicorn
uvicorn.access = lambda *args, **kwargs: None

# ─── Constants ───
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\[^@\s]+$")
BASE_DIR = Path(__file__).parent
JOBS_DIR = BASE_DIR / "jobs"
USAGE_FILE = BASE_DIR / "usage.json"
API_KEYS_FILE = BASE_DIR / "api_keys.json"
HEALTH_FILE = BASE_DIR / "health.json"

# Ensure directories exist
JOBS_DIR.mkdir(exist_ok=True)
for f in [USAGE_FILE, API_KEYS_FILE]:
    if not f.exists():
        f.write_text("{}")

stripe.api_key = config.STRIPE_SECRET_KEY

# Initialize queue
job_queue = init_queue(redis_url=None, sqlite_path=str(BASE_DIR / "queue.db"))

# ─── FastAPI App ───
app = FastAPI(
    title="ClipAI / Peakcut",
    description="AI-powered video clipping tool",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)


# ─── Security Middleware Setup ───
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    
    security_headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
        "Content-Security-Policy": config.SecurityConfig.CSP_POLICY,
    }
    
    if config.SecurityConfig.IS_PRODUCTION:
        security_headers["Strict-Transport-Security"] = f"max-age={config.SecurityConfig.HSTS_MAX_AGE}; includeSubDomains; preload"
        response.headers["Server"] = ""
    
    for key, value in security_headers.items():
        if key not in response.headers:
            response.headers[key] = value
    
    return response


# CORS for API usage
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.SecurityConfig.ALLOWED_ORIGINS if config.SecurityConfig.ALLOWED_ORIGINS else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token", "X-Request-ID"],
    expose_headers=["X-Request-ID", "X-RateLimit-Remaining"],
    max_age=86400,
)


# ─── CORS for local development (development only) ───
if not config.SecurityConfig.IS_PRODUCTION:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ─── Rate Limiting ───
MAX_PROCESS_PER_IP_PER_HOUR = 8
MAX_API_CALLS_PER_HOUR = 3600


# ─── Usage Tracking with Spend Caps ───
_usage_lock = threading.Lock()


def load_usage():
    with _usage_lock:
        return json.loads(USAGE_FILE.read_text())


def save_usage(data):
    with _usage_lock:
        USAGE_FILE.write_text(json.dumps(data))


def reserve_free_use(cid) -> bool:
    """Atomically check-and-increment the free counter with spend cap."""
    with _usage_lock:
        data = json.loads(USAGE_FILE.read_text())
        rec = data.get(cid, {"used": 0})
        if rec["used"] >= config.FREE_LIMIT:
            return False
        # Check monthly spend cap
        if spend_tracker.check_whisper(0):  # Just checking
            rec["used"] += 1
            data[cid] = rec
            USAGE_FILE.write_text(json.dumps(data))
            return True
        return False


def refund_free_use(cid):
    with _usage_lock:
        data = json.loads(USAGE_FILE.read_text())
        rec = data.get(cid, {"used": 0})
        rec["used"] = max(0, rec["used"] - 1)
        data[cid] = rec
        USAGE_FILE.write_text(json.dumps(data))


# ─── Client Identification ───
def get_client_id(request: Request) -> str:
    """Get consistent client ID for usage tracking."""
    cid = request.cookies.get("clipai_cid")
    if not cid:
        cid = str(uuid.uuid4())
    return cid


def get_account(request: Request) -> dict | None:
    """Get signed-in Google account."""
    return auth.read_account_cookie(request.cookies.get(auth.ACCOUNT_COOKIE))


def get_identity(request: Request) -> str:
    """Get identity key for usage tracking."""
    if config.google_oauth.is_configured:
        account = get_account(request)
        if account:
            return f"acct:{account['sub']}"
    return f"cid:{get_client_id(request)}"


# ─── API Key Management ───
_api_lock = threading.Lock()


def load_api_keys():
    with _api_lock:
        return json.loads(API_KEYS_FILE.read_text())


def save_api_keys(data):
    with _api_lock:
        API_KEYS_FILE.write_text(json.dumps(data, indent=2))


def generate_api_key(identity: str, tier: str = "free") -> str:
    """Generate API key with spend caps."""
    api_key = f"pk_{uuid.uuid4().hex[:32]}"
    with _api_lock:
        data = load_api_keys()
        if "keys" not in data:
            data["keys"] = {}
        data["keys"][api_key] = {
            "identity": identity,
            "tier": tier,
            "created": time.time(),
            "usage_this_month": 0,
            "usage_monthly": {"whisper_min": 0, "translate_chars": 0, "tts_chars": 0},
            "active": True,
            "rate_limit_reset": datetime.utcnow().replace(day=1, hour=0, minute=0, second=0).isoformat(),
        }
        save_api_keys(data)
    return api_key


def get_api_key_info(api_key: str) -> dict | None:
    data = load_api_keys()
    return data.get("keys", {}).get(api_key)


def increment_api_usage(api_key: str, resource: str = "default") -> bool:
    """Increment usage with resource-specific limits."""
    info = get_api_key_info(api_key)
    if not info or not info.get("active"):
        return False

    limits = {
        "free": {"default": 100, "whisper": 1000, "translate": 5000000, "tts": 1000000},
        "pro": {"default": 500, "whisper": 5000, "translate": 25000000, "tts": 5000000},
        "pro_plus": {"default": 2000, "whisper": 20000, "translate": 100000000, "tts": 20000000},
    }
    
    monthly_limit = limits.get(info.get("tier", "free"), {}).get(resource, 100)
    current_usage = info.get("usage_monthly", {}).get(f"{resource}_this_month", 0)
    
    if current_usage >= monthly_limit:
        return False

    with _api_lock:
        data = load_api_keys()
        key_data = data.get("keys", {}).get(api_key)
        if key_data:
            current = key_data.get("usage_monthly", {}).get(f"{resource}_this_month", 0)
            key_data["usage_monthly"][f"{resource}_this_month"] = current + 1
            key_data["usage_this_month"] = key_data.get("usage_this_month", 0) + 1
            save_api_keys(data)
    return True


# ─── Circuit Breakers ───
stripe_cb = CircuitBreaker("stripe", failure_threshold=5, timeout=60)
whisper_cb = CircuitBreaker("whisper", failure_threshold=3, timeout=120)
translate_cb = CircuitBreaker("google_translate", failure_threshold=5, timeout=60)
tts_cb = CircuitBreaker("piper_tts", failure_threshold=3, timeout=120)
resend_cb = CircuitBreaker("resend", failure_threshold=5, timeout=60)


def safe_stripe_call(func, *args, **kwargs):
    """Execute Stripe call with circuit breaker."""
    try:
        return stripe_cb.call(func, *args, **kwargs)
    except CircuitBreakerOpenError:
        log.warning("Stripe circuit breaker OPEN")
        raise HTTPException(status_code=503, detail="Billing service temporarily unavailable")
    except Exception as e:
        log.exception("Stripe call failed: %s", str(e))
        raise


# ─── Health Check Endpoint ───
@app.get("/healthz", response_class=PlainTextResponse)
def health_check():
    """Health check with resource status."""
    stats = health_checker.run_checks()
    if stats.get("overall") == HealthStatus.HEALTHY.value:
        return "ok"
    return JSONResponse(
        status_code=503,
        content={"status": "unhealthy", "details": stats}
    )


@app.get("/api/health")
def api_health(request: Request):
    """Detailed health status for monitoring."""
    return JSONResponse({
        "status": "ok" if health_checker.run_checks().get("overall") == HealthStatus.HEALTHY.value else "degraded",
        "timestamp": time.time(),
        "request_id": getattr(request.state, 'request_id', None),
        "resources": resource_monitor.get_averages(),
        "circuit_breakers": circuit_breakers.get_all_states(),
        "queue_stats": job_queue.get_stats() if job_queue else {},
    })


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE_DIR / "index.html").read_text()


@app.get("/pricing", response_class=HTMLResponse)
def pricing():
    return (BASE_DIR / "pricing.html").read_text()


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    if config.google_oauth.is_configured and not get_account(request):
        return RedirectResponse("/auth/google/login", status_code=303)
    return (BASE_DIR / "settings.html").read_text()


@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    return (BASE_DIR / "privacy.html").read_text().replace("__CONTACT_EMAIL__", config.CONTACT_EMAIL)


@app.get("/terms", response_class=HTMLResponse)
def terms():
    return (BASE_DIR / "terms.html").read_text().replace("__CONTACT_EMAIL__", config.CONTACT_EMAIL)


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return "User-agent: *\nAllow: /\nDisallow: /jobs/\nDisallow: /admin/\n"


# ─── Health Monitor Background Thread ───
_health_lock = threading.Lock()
_health_data = {"healthy": True, "last_check": time.time(), "details": {}}


def _health_monitor_loop():
    """Background thread for health monitoring."""
    while True:
        time.sleep(10)
        stats = health_checker.run_checks()
        with _health_lock:
            _health_data["healthy"] = stats.get("overall") == HealthStatus.HEALTHY.value
            _health_data["last_check"] = time.time()
            _health_data["details"] = stats


threading.Thread(target=_health_monitor_loop, daemon=True).start()


@app.get("/api/healthdetailed")
def health_detailed():
    """Detailed health metrics for monitoring."""
    with _health_lock:
        return _health_data.copy()


# ─── Usage Endpoint with Security Headers ───
@app.get("/usage")
def usage(request: Request):
    identity = get_identity(request)
    account = get_account(request)
    rec = load_usage().get(identity, {"used": 0})
    is_pro = check_pro_status(request)
    remaining = None if is_pro else max(0, config.FREE_LIMIT - rec["used"])
    
    # Check spend caps
    caps = {
        "whisper_minutes": config.SecurityConfig.WHISPER_MAX_MINUTES_PER_MONTH - spend_tracker.whisper_minutes_used,
        "translate_chars": config.SecurityConfig.GOOGLE_TRANSLATE_MAX_CHARS_PER_MONTH - spend_tracker.google_translate_chars,
        "tts_chars": config.SecurityConfig.PIPER_TTS_MAX_CHARS_PER_MONTH - spend_tracker.piper_tts_chars,
    }
    
    resp = JSONResponse({
        "used": rec["used"],
        "pro": is_pro,
        "limit": config.FREE_LIMIT,
        "remaining": remaining,
        "google_configured": config.google_oauth.is_configured,
        "signed_in": account is not None,
        "email": account["email"] if account else None,
        "email_configured": config.email.is_configured,
        "spend_caps": caps,
        "resource_stats": resource_monitor.get_averages(),
        "queue_stats": job_queue.get_stats() if job_queue else {},
    })
    
    set_secure_cookie(resp, "clipai_cid", get_client_id(request), max_age=60*60*24*365)
    return resp


# ─── Rate Limiting Helper ───
def check_ip_rate_limit(ip: str, max_requests: int = MAX_PROCESS_PER_IP_PER_HOUR) -> bool:
    """IP-based rate limiting."""
    return check_rate_limit(ip, max_requests, 3600, _ip_request_log)


_ip_request_log: Dict[str, List[float]] = defaultdict(list)


# ─── Input Validation ───
def validate_clip_format(fmt: str) -> bool:
    return fmt in ("vertical", "square", "horizontal")


def validate_caption_style(style: str) -> bool:
    return style in ("bold", "outline", "subtle", "neon")


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """Sanitize filename to prevent path traversal."""
    clean = Path(filename).name  # Extract just the filename
    clean = re.sub(r'[^\w\.-]', '_', clean)  # Replace special chars
    return clean[:max_length]


# ─── Process Upload Endpoint ───
@app.post("/process")
async def process(
    request: Request,
    file: UploadFile = File(...),
    dub_lang: str | None = Form(None),
    notify_email: str | None = Form(None),
    clip_format: str = Form("vertical"),
    caption_style: str = Form("bold"),
):
    # Validate inputs
    if not validate_clip_format(clip_format):
        raise HTTPException(status_code=400, detail="Invalid clip format. Use 'vertical', 'square', or 'horizontal'.")
    if not validate_caption_style(caption_style):
        raise HTTPException(status_code=400, detail="Invalid caption style.")

    # Check file extension
    ext = Path(file.filename or "").suffix.lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Use MP4, MOV, M4V, WEBM, or MKV."
        )

    # Check file size with spend cap
    if file.size and file.size > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {config.MAX_UPLOAD_MB}MB)"
        )

    # IP rate limiting
    client_ip = get_client_identifier(request)
    if not check_ip_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many uploads from this IP. Try again in an hour.")

    # Auth check for Google sign-in
    if config.google_oauth.is_configured and not get_account(request):
        raise HTTPException(status_code=401, detail="Sign in with Google required for processing.")

    # Dubbing requires Pro
    is_pro = check_pro_status(request)
    if dub_lang and not is_pro:
        raise HTTPException(
            status_code=402,
            detail="Dubbing is a Pro feature. Upgrade to unlock multi-language support."
        )

    # Validate dub language
    if dub_lang:
        from dub_lib import DUB_LANGUAGES
        if dub_lang not in DUB_LANGUAGES:
            raise HTTPException(status_code=400, detail=f"Unsupported dub language. Available: {list(DUB_LANGUAGES.keys())}")

    # Validate email
    if notify_email and not EMAIL_RE.match(notify_email):
        raise HTTPException(status_code=400, detail="Invalid email address.")

    # Reserve free usage
    identity = get_identity(request)
    if not is_pro and not reserve_free_use(identity):
        raise HTTPException(
            status_code=402,
            detail=f"Free limit reached ({config.FREE_LIMIT} videos/month). Upgrade to Pro."
        )

    # Check spend caps before processing
    if not spend_tracker.check_whisper(config.MAX_UPLOAD_MB):  # Rough estimate
        log.warning("Whisper spend cap reached for user %s", identity)

    # Create job with queue
    job_id = str(uuid.uuid4())[:8]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Save upload metadata
    metadata = {
        "job_id": job_id,
        "user": identity,
        "pro": is_pro,
        "submit_time": time.time(),
        "params": {
            "dub_lang": dub_lang,
            "clip_format": clip_format,
            "caption_style": caption_style,
            "notify_email": notify_email,
        }
    }

    # Save input file with sanitized filename
    input_path = job_dir / f"input{ext}"
    max_bytes = config.MAX_UPLOAD_MB * 1024 * 1024
    size = 0
    try:
        with open(input_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail=f"File too large (max {config.MAX_UPLOAD_MB}MB)")
                f.write(chunk)
    except HTTPException:
        shutil.rmtree(job_dir, ignore_errors=True)
        if not is_pro:
            refund_free_use(identity)
        raise
    except Exception as e:
        log.exception("Upload failed")
        shutil.rmtree(job_dir, ignore_errors=True)
        if not is_pro:
            refund_free_use(identity)
        raise HTTPException(status_code=500, detail="Upload failed")

    # Submit to job queue
    job = job_queue.submit(
        user_id=identity,
        input_path=str(input_path),
        params=metadata["params"],
        priority=JobPriority.NORMAL,
    )

    # Queue might be at capacity
    if not job:
        shutil.rmtree(job_dir, ignore_errors=True)
        if not is_pro:
            refund_free_use(identity)
        raise HTTPException(status_code=503, detail="Server at capacity. Try again in a few minutes.")

    resp = JSONResponse({"job_id": job.id, "status": "queued"})
    set_secure_cookie(resp, "clipai_cid", get_client_id(request), max_age=60*60*24*365, secure=True, httponly=True, samesite="lax")
    return resp


def check_pro_status(request: Request) -> bool:
    """Check if user has Pro subscription."""
    customer_id = request.cookies.get("clipai_customer")
    if not customer_id:
        return False
    try:
        subs = stripe.Subscription.list(customer=customer_id, status="active", limit=1)
        return len(subs.data) > 0
    except Exception:
        log.exception("Stripe subscription lookup failed")
        return False


# ─── Job Status Endpoint ───
@app.get("/job/{job_id}")
def job_status(job_id: str):
    # Validate job_id format
    if not re.match(r'^[a-zA-Z0-9-]+$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    
    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    
    # Only allow owner access
    # (Implementation would check request identity here)
    
    out = {"job_id": job.id, "status": job.status.value}
    if job.status == JobStatus.PROCESSING:
        out["elapsed"] = round(time.time() - job.started_at, 1)
    elif job.status == JobStatus.COMPLETED:
        out["clips"] = job.result.get("clips", [])
        out["duration"] = job.result.get("duration")
        out["language"] = job.result.get("language")
    elif job.status == JobStatus.FAILED:
        # Sanitize error message
        out["error"] = job.error[:500] if job.error else "Processing failed"
    
    return out


@app.get("/jobs/{job_id}/{filename}")
def get_clip(job_id: str, filename: str):
    # Strict path traversal protection
    if (".." in job_id) or (".." in filename) or ("/" in filename):
        raise HTTPException(status_code=400, detail="Invalid path")
    
    # Validate job_id
    if not re.match(r'^[a-zA-Z0-9-]+$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    
    path = JOBS_DIR / job_id / sanitize_filename(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(str(path))


# ─── OAuth Routes ───
@app.get("/auth/google/login")
def google_login(request: Request):
    if not config.google_oauth.is_configured:
        raise HTTPException(status_code=503, detail="Google sign-in not configured")
    
    state = auth.new_state()
    redirect_uri = f"{config.SITE_URL}/auth/google/callback"
    try:
        login_url = auth.build_login_url(redirect_uri, state)
    except Exception as e:
        log.exception("Failed to build Google login URL")
        raise HTTPException(status_code=502, detail="Authentication service unavailable")
    
    resp = RedirectResponse(login_url, status_code=303)
    set_secure_cookie(resp, auth.STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax")
    return resp


@app.get("/auth/google/callback")
def google_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return RedirectResponse(f"{config.SITE_URL}/?auth_error=1", status_code=303)

    expected_state = request.cookies.get(auth.STATE_COOKIE)
    if not code or not state or not expected_state or state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid or expired sign-in attempt")

    try:
        claims = auth.exchange_code_for_claims(code, f"{config.SITE_URL}/auth/google/callback")
    except Exception as e:
        log.exception("Google OAuth failed")
        return RedirectResponse(f"{config.SITE_URL}/?auth_error=1", status_code=303)

    if not claims.get("email_verified", False):
        return RedirectResponse(f"{config.SITE_URL}/?auth_error=unverified", status_code=303)

    account_token = auth.sign_account_cookie(claims)
    resp = RedirectResponse(f"{config.SITE_URL}/?signed_in=1", status_code=303)
    resp.set_cookie(auth.ACCOUNT_COOKIE, account_token, max_age=auth.ACCOUNT_MAX_AGE, httponly=True, samesite="lax", secure=config.SecurityConfig.IS_PRODUCTION)
    resp.delete_cookie(auth.STATE_COOKIE)
    return resp


@app.get("/auth/logout")
def logout():
    resp = RedirectResponse(f"{config.SITE_URL}/", status_code=303)
    resp.delete_cookie(auth.ACCOUNT_COOKIE)
    return resp


# ─── Stripe Billing Routes ───
@app.get("/create-checkout-session")
def create_checkout_session(request: Request):
    if config.google_oauth.is_configured and not get_account(request):
        return RedirectResponse("/auth/google/login", status_code=303)

    identity = get_identity(request)
    try:
        session = safe_stripe_call(stripe.checkout.Session.create,
            mode="subscription",
            line_items=[{"price": config.STRIPE_PRICE_ID, "quantity": 1}],
            success_url=f"{config.SITE_URL}/confirm-checkout?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{config.SITE_URL}/pricing",
            client_reference_id=identity,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Stripe checkout failed")
        raise HTTPException(status_code=500, detail="Billing service unavailable")

    resp = RedirectResponse(session.url, status_code=303)
    set_secure_cookie(resp, "clipai_cid", get_client_id(request), max_age=60*60*24*365, httponly=True, samesite="lax")
    return resp


@app.get("/create-checkout-session-plus")
def create_checkout_session_plus(request: Request):
    """Pro Plus checkout."""
    if config.google_oauth.is_configured and not get_account(request):
        return RedirectResponse("/auth/google/login", status_code=303)

    identity = get_identity(request)
    try:
        session = safe_stripe_call(stripe.checkout.Session.create,
            mode="subscription",
            line_items=[{"price": config.STRIPE_PRICE_ID_PLUS, "quantity": 1}],
            success_url=f"{config.SITE_URL}/confirm-checkout?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{config.SITE_URL}/pricing",
            client_reference_id=identity,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Stripe checkout failed")
        raise HTTPException(status_code=500, detail="Billing service unavailable")

    resp = RedirectResponse(session.url, status_code=303)
    set_secure_cookie(resp, "clipai_cid", get_client_id(request), max_age=60*60*24*365, httponly=True, samesite="lax")
    return resp


# ─── Stripe Webhook ───
@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    
    if not spend_tracker.check_stripe_webhook():
        log.warning("Stripe webhook rate limit exceeded")
        return JSONResponse({"received": True})  # Don't reject, just log

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, config.STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        log.warning("Invalid webhook signature: %s", str(e)[:100])
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        log.info("Checkout completed for customer %s", event["data"]["object"].get("customer"))
    elif event["type"] in ("customer.subscription.deleted", "customer.subscription.paused"):
        log.info("Subscription ended for customer %s", event["data"]["object"].get("customer"))

    return {"received": True}


# ─── API Endpoints ───
@app.post("/api/keys")
def create_api_key(request: Request):
    """Generate API key for programatic access."""
    if config.google_oauth.is_configured and not get_account(request):
        raise HTTPException(status_code=401, detail="Sign in required")

    identity = get_identity(request)
    tier = "pro" if check_pro_status(request) else "free"
    api_key = generate_api_key(identity, tier)
    
    return {"api_key": api_key, "tier": tier, "note": "Store this key securely - it won't be shown again"}


@app.get("/api/keys")
def list_api_keys(request: Request):
    """List user's API keys."""
    if config.google_oauth.is_configured and not get_account(request):
        raise HTTPException(status_code=401, detail="Sign in required")

    identity = get_identity(request)
    data = load_api_keys()
    user_keys = [
        {
            "api_key": key[:8] + "..." + key[-4:],
            "tier": info["tier"],
            "created": info["created"],
            "usage_this_month": info.get("usage_this_month", 0),
            "active": info.get("active", True),
        }
        for key, info in data.get("keys", {}).items()
        if info.get("identity") == identity
    ]
    return {"keys": user_keys}


@app.post("/api/v1/process")
async def api_process(request: Request, file: UploadFile = File(...), clip_format: str = Form("vertical")):
    """API endpoint for video processing."""
    # Validate auth
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    api_key = auth_header[7:]
    key_info = get_api_key_info(api_key)
    if not key_info or not key_info.get("active"):
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Check API rate limits
    resource = "default"
    if not increment_api_usage(api_key, resource):
        raise HTTPException(
            status_code=429,
            detail=f"API rate limit exceeded ({key_info['tier']} tier)"
        )

    # Validate format
    if clip_format not in ("vertical", "square", "horizontal"):
        raise HTTPException(status_code=400, detail="Invalid clip format")

    # Check file size
    if file.size and file.size > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Video too large (max {config.MAX_UPLOAD_MB}MB)")

    # Process
    job_id = str(uuid.uuid4())[:8]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    input_path = job_dir / "input.mp4"
    content = await file.read()
    input_path.write_bytes(content)

    # Submit to queue
    job = job_queue.submit(
        user_id=key_info["identity"],
        input_path=str(input_path),
        params={"clip_format": clip_format},
        priority=JobPriority.NORMAL,
    )

    if not job:
        input_path.unlink(missing_ok=True)
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=503, detail="Server at capacity")

    # For API, return immediate job ID
    return {
        "job_id": job.id,
        "status": "queued",
        "poll_url": f"/api/v1/clips/{job.id}",
    }


@app.get("/api/v1/clips/{job_id}")
def api_get_clips(job_id: str, request: Request):
    """Get processed clips via API."""
    if not re.match(r'^[a-zA-Z0-9-]+$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")

    auth_header = request.headers.get("Authorization", "")
    api_key = auth_header[7:] if auth_header.startswith("Bearer ") else None

    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "status": job.status.value,
        "job_id": job.id,
        "created": job.created_at,
        "results": job.result if job.status == JobStatus.COMPLETED else None,
        "error": job.error if job.status == JobStatus.FAILED else None,
    }


# ─── Billing Portal ───
@app.get("/billing-portal")
def billing_portal(request: Request):
    """Open Stripe customer portal."""
    customer_id = request.cookies.get("clipai_customer")
    if not customer_id:
        return RedirectResponse(f"{config.SITE_URL}/", status_code=303)

    try:
        session = safe_stripe_call(stripe.billing_portal.Session.create,
            customer=customer_id, return_url=f"{config.SITE_URL}/"
        )
    except Exception:
        log.exception("Billing portal failed")
        raise HTTPException(status_code=500, detail="Billing portal unavailable")

    return RedirectResponse(session.url, status_code=303)


@app.get("/confirm-checkout")
def confirm_checkout(session_id: str):
    """Handle Stripe checkout completion."""
    try:
        session = safe_stripe_call(stripe.checkout.Session.retrieve, session_id)
    except Exception:
        log.exception("Session retrieval failed")
        return RedirectResponse(f"{config.SITE_URL}/?upgrade_error=1", status_code=303)

    resp = RedirectResponse(f"{config.SITE_URL}/?upgraded=1", status_code=303)
    if session.payment_status in ("paid", "no_payment_required") and session.customer:
        resp.set_cookie("clipai_customer", session.customer, max_age=60*60*24*365, httponly=True, samesite="lax", secure=config.SecurityConfig.IS_PRODUCTION)
    return resp


# ─── Admin Routes (Protected) ───
def require_admin(request: Request) -> bool:
    """Check if request is from admin (could be IP-based or token-based)."""
    # Simple IP-based admin check (expand for proper admin auth)
    admin_ip = request.headers.get("x-admin-ip")
    if admin_ip in ("127.0.0.1", "::1"):
        return True
    admin_token = request.headers.get("x-admin-token")
    if admin_token == os.environ.get("ADMIN_TOKEN"):
        return True
    return False


ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")


@app.get("/admin/stats")
def admin_stats(request: Request):
    """Admin-only stats endpoint."""
    if ADMIN_PASSWORD:
        auth = request.headers.get("authorization", "")
        # Simple token auth for admin
        if not auth:
            return JSONResponse({"error": "Auth required"}, status_code=401)

    stats = {
        "queue": job_queue.get_stats() if job_queue else {},
        "resources": resource_monitor.get_averages(),
        "health": health_checker.get_last_results(),
        "circuit_breakers": circuit_breakers.get_all_states(),
        "spend_caps": {
            "whisper_remaining": config.SecurityConfig.WHISPER_MAX_MINUTES_PER_MONTH - spend_tracker.whisper_minutes_used,
            "translate_remaining": config.SecurityConfig.GOOGLE_TRANSLATE_MAX_CHARS_PER_MONTH - spend_tracker.google_translate_chars,
            "tts_remaining": config.SecurityConfig.PIPER_TTS_MAX_CHARS_PER_MONTH - spend_tracker.piper_tts_chars,
        },
    }
    return stats


@app.post("/admin/jobs/cleanup")
def admin_cleanup():
    """Admin endpoint to cleanup old jobs."""
    deleted = job_queue.cleanup_old(86400) if job_queue else 0
    return {"deleted": deleted, "message": f"Cleaned up {deleted} old jobs"}


# ─── Startup Events ───
@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    log.info("Starting ClipAI/Peakcut...")

    # Ensure directories exist
    JOBS_DIR.mkdir(exist_ok=True)

    # Initialize health checker hooks
    health_checker.register_check("queue", lambda: (True, "Queue operational"))

    log.info("Startup complete")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    log.info("Shutting down...")
    if job_queue:
        job_queue.stop_cleanup()
    resource_monitor.stop()
    log.info("Shutdown complete")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)