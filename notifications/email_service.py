
# notifications/email_service.py
"""
Three-gate email failover service.

Gate 1: Mailtrap Sending API  — HTTPS/443, no SMTP dependency
Gate 2: Namecheap SMTP        — port 465, SSL
Gate 3: Gmail SMTP            — port 587, STARTTLS

Each gate is attempted in order. On any exception the gate fails silently
and the next gate is tried. If all three fail, a single RuntimeError is
raised containing the diagnostics from each gate.

provider_used is returned in the result dict so callers can record which
gate delivered successfully.
"""

import logging
import smtplib
import ssl
import socket
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _mask_email(email: str) -> str:
    """Privacy-safe email mask for logs: user@domain → u***@domain."""
    if not email or '@' not in email:
        return '***'
    user_part, domain_part = email.split('@', 1)
    masked = (user_part[0] + '***') if user_part else '***'
    return f"{masked}@{domain_part}"


def _build_mime_message(
    from_name: str,
    from_email: str,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> MIMEMultipart:
    """Build a MIME multipart/alternative message for SMTP gates."""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"{from_name} <{from_email}>"
    msg['To'] = to_email
    msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))
    return msg


# ---------------------------------------------------------------------------
# Gate 1 — Mailtrap Transactional Sending API (HTTPS/443)
# ---------------------------------------------------------------------------

def _send_via_mailtrap_api(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> None:
    """
    Gate 1: Send via Mailtrap Transactional Sending API (HTTPS POST, no SMTP socket).
    Raises on any error so the caller falls through to Gate 2.
    """
    api_token = getattr(settings, 'MAILTRAP_API_TOKEN', '')
    from_email = getattr(settings, 'MAILTRAP_FROM_EMAIL', '')
    from_name = getattr(settings, 'MAILTRAP_FROM_NAME', 'VerifyNG')

    if not api_token or not from_email:
        raise ValueError("Mailtrap API credentials not configured (MAILTRAP_API_TOKEN / MAILTRAP_FROM_EMAIL)")

    payload = {
        "from": {"email": from_email, "name": from_name},
        "to": [{"email": to_email}],
        "subject": subject,
        "html": html_body,
        "text": text_body,
        "category": "Transactional",
    }
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        "https://send.api.mailtrap.io/api/send",
        json=payload,
        headers=headers,
        timeout=8,
    )
    response.raise_for_status()


# ---------------------------------------------------------------------------
# Gate 2 — Namecheap Private Email SMTP (port 465, SSL)
# ---------------------------------------------------------------------------

def _send_via_namecheap_smtp(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> None:
    """
    Gate 2: Send via Namecheap Private Email SMTP on port 465 with immediate SSL.
    Raises on any error so the caller can fall through to Gate 3.
    """
    host = getattr(settings, 'NAMECHEAP_SMTP_HOST', '')
    port = getattr(settings, 'NAMECHEAP_SMTP_PORT', 465)
    username = getattr(settings, 'NAMECHEAP_SMTP_USER', '')
    password = getattr(settings, 'NAMECHEAP_SMTP_PASSWORD', '')
    from_email = getattr(settings, 'NAMECHEAP_FROM_EMAIL', username)
    from_name = getattr(settings, 'NAMECHEAP_FROM_NAME', 'VerifyNG')

    if not host or not username or not password:
        raise ValueError("Namecheap SMTP credentials not configured")

    msg = _build_mime_message(from_name, from_email, to_email, subject, html_body, text_body)
    context = ssl.create_default_context()

    with smtplib.SMTP_SSL(host, port, context=context, timeout=10) as server:
        server.login(username, password)
        server.sendmail(from_email, [to_email], msg.as_string())


# ---------------------------------------------------------------------------
# Gate 3 — Gmail SMTP (port 587, STARTTLS)
# ---------------------------------------------------------------------------

def _send_via_gmail_smtp(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> None:
    """
    Gate 3: Send via Gmail SMTP on port 587 with STARTTLS upgrade.
    Raises on failure — this is the final gate; the caller raises RuntimeError.
    """
    username = getattr(settings, 'GMAIL_SMTP_USER', '')
    password = getattr(settings, 'GMAIL_SMTP_APP_PASSWORD', '')
    from_name = getattr(settings, 'GMAIL_FROM_NAME', 'VerifyNG')

    if not username or not password:
        raise ValueError("Gmail SMTP credentials not configured")

    msg = _build_mime_message(from_name, username, to_email, subject, html_body, text_body)

    with smtplib.SMTP('smtp.gmail.com', 587, timeout=10) as server:
        server.ehlo()
        server.starttls(context=ssl.create_default_context())
        server.ehlo()
        server.login(username, password)
        server.sendmail(username, [to_email], msg.as_string())


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
) -> dict:
    """
    Attempt to deliver an email through three failover gates in order.

    Returns:
        {
            "delivered": True,
            "provider_used": "mailtrap_api" | "namecheap_smtp" | "gmail_smtp",
        }

    Raises:
        RuntimeError: if all three gates fail, with diagnostic details from each.
    """
    if not text_body:
        # Minimal plaintext fallback stripped from HTML
        import re
        text_body = re.sub(r'<[^>]+>', '', html_body).strip()

    masked = _mask_email(to_email)
    gate_errors: dict[str, str] = {}

    # ---- Gate 1: Mailtrap API ----
    try:
        _send_via_mailtrap_api(to_email, subject, html_body, text_body)
        logger.info("Email delivered via Gate 1 (Mailtrap API) → %s", masked)
        return {"delivered": True, "provider_used": "mailtrap_api"}
    except Exception as exc:
        gate_errors["gate1_mailtrap_api"] = f"{type(exc).__name__}: {exc}"
        logger.warning("Gate 1 (Mailtrap API) failed for %s: %s", masked, gate_errors["gate1_mailtrap_api"])

    # ---- Gate 2: Namecheap SMTP ----
    try:
        _send_via_namecheap_smtp(to_email, subject, html_body, text_body)
        logger.info("Email delivered via Gate 2 (Namecheap SMTP) → %s", masked)
        return {"delivered": True, "provider_used": "namecheap_smtp"}
    except Exception as exc:
        gate_errors["gate2_namecheap_smtp"] = f"{type(exc).__name__}: {exc}"
        logger.warning("Gate 2 (Namecheap SMTP) failed for %s: %s", masked, gate_errors["gate2_namecheap_smtp"])

    # ---- Gate 3: Gmail SMTP ----
    try:
        _send_via_gmail_smtp(to_email, subject, html_body, text_body)
        logger.info("Email delivered via Gate 3 (Gmail SMTP) → %s", masked)
        return {"delivered": True, "provider_used": "gmail_smtp"}
    except Exception as exc:
        gate_errors["gate3_gmail_smtp"] = f"{type(exc).__name__}: {exc}"
        logger.warning("Gate 3 (Gmail SMTP) failed for %s: %s", masked, gate_errors["gate3_gmail_smtp"])

    # All gates exhausted
    raise RuntimeError(
        f"All three email delivery gates failed for {masked}. "
        f"Diagnostics: {gate_errors}"
    )
