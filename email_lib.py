"""Email notifications via Resend API."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import List

try:
    import httpx
except ImportError:
    httpx = None

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from clipai_config import app_config as config
except ImportError:
    class _Config:
        RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "re_REPLACE_ME")
        EMAIL_FROM = os.environ.get("EMAIL_FROM", "Peakcut <onboarding@resend.dev>")
        SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000")
        EMAIL_CONFIGURED = RESEND_API_KEY != "re_REPLACE_ME"
    config = _Config()

logger = logging.getLogger("clipai.email")

RESEND_URL = "https://api.resend.com/emails"


def _send(to_email: str, subject: str, html: str) -> bool:
    if not config.EMAIL_CONFIGURED:
        logger.debug("Email not configured, skipping send to %s", to_email)
        return False
    if not httpx:
        logger.warning("httpx not installed, cannot send email")
        return False
    try:
        resp = httpx.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
            json={"from": config.EMAIL_FROM, "to": [to_email], "subject": subject, "html": html},
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.warning("Resend send failed (%s): %s", resp.status_code, resp.text[:300])
            return False
        return True
    except Exception as e:
        logger.exception("Failed to send email to %s: %s", to_email, e)
        return False


def send_done_email(to_email: str, clip_urls: List[str], duration: float, is_pro: bool) -> bool:
    links = "".join(f'<li><a href="{config.SITE_URL}{u}">Clip {i+1}</a></li>' for i, u in enumerate(clip_urls))
    upsell = "" if is_pro else (
        '<p style="margin-top:24px;padding:16px;background:#f6f5fb;border-radius:10px;">'
        'Want no watermark and unlimited videos? '
        f'<a href="{config.SITE_URL}/create-checkout-session">Upgrade to Pro — $15/mo</a></p>'
    )
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;">
      <h2>Your clips are ready 🎬</h2>
      <p>Peakcut turned your {round(duration)}s video into {len(clip_urls)} clip(s):</p>
      <ul>{links}</ul>
      <p style="color:#6b6478;font-size:0.85rem;">Links expire in 24 hours — download them soon.</p>
      {upsell}
    </div>
    """
    return _send(to_email, "Your Peakcut clips are ready", html)


def send_failed_email(to_email: str, error: str) -> bool:
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;">
      <h2>Processing failed</h2>
      <p>{error}</p>
      <p><a href="{config.SITE_URL}">Try again</a></p>
    </div>
    """
    return _send(to_email, "Peakcut — video processing failed", html)