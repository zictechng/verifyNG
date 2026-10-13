
"""
api/webhooks.py

WhatsApp Business API (Meta Cloud API) webhook handler for VerifyNG.

Mounted on the existing django-ninja API at:
  GET  /api/v1/webhooks/whatsapp/  — Meta webhook verification (hub.challenge)
  POST /api/v1/webhooks/whatsapp/  — Inbound message handler

Environment variables:
  WHATSAPP_VERIFY_TOKEN     — Token you set in the Meta App Dashboard
  WHATSAPP_API_TOKEN        — Permanent/system-user bearer token for sending messages
  WHATSAPP_PHONE_NUMBER_ID  — Phone Number ID from Meta App Dashboard
  WHATSAPP_API_VERSION      — Meta Graph API version (default: v19.0)

Commands parsed from inbound WhatsApp messages:
  CHECK <phone|name|account>  — Public trust lookup
  REPORT                      — Guided fraud report flow (prompts user to use web portal)
  VERIFY                      — Trust profile verification (prompts user to use web portal)
  HELP                        — Lists available commands

Graceful degradation: if credentials are not configured, the webhook still
responds correctly to Meta (200 OK on GET verification, 200 OK on POST to
avoid Meta retries) but logs a warning and does not attempt to send replies.
"""

import hashlib
import hmac
import json
import logging
from typing import Optional

import requests
from django.conf import settings
from django.http import HttpRequest
from ninja import Router, Schema
from ninja.errors import HttpError

logger = logging.getLogger(__name__)

router = Router(tags=["WhatsApp Webhooks"])

# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def _get_verify_token() -> str:
    return getattr(settings, 'WHATSAPP_VERIFY_TOKEN', '') or ''


def _get_api_token() -> str:
    return getattr(settings, 'WHATSAPP_API_TOKEN', '') or ''


def _get_phone_number_id() -> str:
    return getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', '') or ''


def _get_api_version() -> str:
    return getattr(settings, 'WHATSAPP_API_VERSION', 'v19.0') or 'v19.0'


def _whatsapp_configured() -> bool:
    """Return True only when all mandatory credentials are present."""
    return bool(_get_api_token() and _get_phone_number_id())


# ---------------------------------------------------------------------------
# GET — Meta webhook verification (hub.challenge handshake)
# ---------------------------------------------------------------------------

@router.get("/whatsapp/", auth=None, summary="WhatsApp webhook verification")
def whatsapp_verify(request: HttpRequest):
    """
    GET /api/v1/webhooks/whatsapp/

    Meta calls this endpoint when you register a webhook URL in the App Dashboard.
    Responds with hub.challenge only when hub.verify_token matches WHATSAPP_VERIFY_TOKEN.
    Returns 403 if the token does not match.
    """
    mode = request.GET.get("hub.mode", "")
    token = request.GET.get("hub.verify_token", "")
    challenge = request.GET.get("hub.challenge", "")

    verify_token = _get_verify_token()
    if not verify_token:
        logger.warning(
            "WhatsApp webhook GET received but WHATSAPP_VERIFY_TOKEN is not configured."
        )
        raise HttpError(403, "Webhook verification token not configured.")

    if mode == "subscribe" and token == verify_token:
        logger.info("WhatsApp webhook verified successfully.")
        from django.http import HttpResponse
        return HttpResponse(challenge, content_type="text/plain", status=200)

    logger.warning(
        "WhatsApp webhook verification failed (mode=%s, token_match=%s).",
        mode,
        token == verify_token,
    )
    raise HttpError(403, "Webhook verification failed.")


# ---------------------------------------------------------------------------
# POST — Inbound message handler
# ---------------------------------------------------------------------------

@router.post("/whatsapp/", auth=None, summary="WhatsApp inbound message handler")
def whatsapp_webhook(request: HttpRequest):
    """
    POST /api/v1/webhooks/whatsapp/

    Receives inbound WhatsApp messages from Meta Cloud API.
    Validates X-Hub-Signature-256 when WHATSAPP_API_TOKEN is configured.
    Parses message text and routes CHECK / REPORT / VERIFY / HELP commands.
    Always returns 200 to prevent Meta from retrying delivery.
    """
    # Validate signature to ensure the POST is from Meta
    if _get_api_token():
        _validate_meta_signature(request)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        logger.warning("WhatsApp webhook received non-JSON body.")
        from django.http import JsonResponse
        return JsonResponse({"status": "ok"}, status=200)

    # Walk the payload to find message entries
    entries = body.get("entry", [])
    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            for message in messages:
                _handle_inbound_message(message, value)

    from django.http import JsonResponse
    return JsonResponse({"status": "ok"}, status=200)


# ---------------------------------------------------------------------------
# Signature validation
# ---------------------------------------------------------------------------

def _validate_meta_signature(request: HttpRequest) -> None:
    """
    Verify X-Hub-Signature-256 header using WHATSAPP_API_TOKEN as the secret.
    Raises HttpError(403) on mismatch.

    NOTE: Meta signs with the App Secret, not the API token.
    Set WHATSAPP_APP_SECRET in .env for proper signature validation.
    Using API token as fallback secret when App Secret is not configured.
    """
    app_secret = (
        getattr(settings, 'WHATSAPP_APP_SECRET', '') or
        _get_api_token()
    )
    if not app_secret:
        return  # No secret configured — skip validation

    signature_header = request.headers.get("X-Hub-Signature-256", "")
    if not signature_header.startswith("sha256="):
        logger.warning("WhatsApp POST missing or malformed X-Hub-Signature-256 header.")
        raise HttpError(403, "Missing webhook signature.")

    expected_signature = "sha256=" + hmac.new(
        app_secret.encode("utf-8"),
        request.body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature_header, expected_signature):
        logger.warning("WhatsApp webhook signature mismatch — possible spoofed request.")
        raise HttpError(403, "Webhook signature verification failed.")


# ---------------------------------------------------------------------------
# Message routing
# ---------------------------------------------------------------------------

def _handle_inbound_message(message: dict, value: dict) -> None:
    """
    Parse and route a single inbound WhatsApp message.
    Extracts sender phone, message text, and dispatches command response.
    """
    msg_type = message.get("type", "")
    sender_phone = message.get("from", "")

    if msg_type != "text":
        # Ignore non-text messages (images, voice notes, etc.) for now
        logger.debug(
            "WhatsApp: ignoring non-text message type=%s from=%s",
            msg_type,
            _mask_phone(sender_phone),
        )
        return

    text_body: str = message.get("text", {}).get("body", "").strip()
    if not text_body:
        return

    logger.info(
        "WhatsApp inbound message from=%s text_preview=%s",
        _mask_phone(sender_phone),
        text_body[:40],
    )

    response_text = _route_command(text_body, sender_phone)
    if response_text:
        _send_whatsapp_reply(to=sender_phone, text=response_text)


def _route_command(text: str, sender_phone: str) -> Optional[str]:
    """
    Parse the message text and return the appropriate reply string.
    Returns None if the message should be silently ignored.

    Supported commands (case-insensitive):
      CHECK <query>  — Public trust lookup
      REPORT         — Directed to web portal
      VERIFY         — Directed to web portal
      HELP           — Lists commands
    """
    upper = text.upper().strip()
    site_url = getattr(settings, 'SITE_BASE_URL', 'https://verifyng.com')

    if upper.startswith("CHECK"):
        query = text[5:].strip()
        if not query:
            return (
                "ℹ️ *VerifyNG CHECK*\n\n"
                "Please provide a phone number, name, or bank account to check.\n\n"
                "Example: *CHECK 08012345678*"
            )
        return _handle_check_command(query, site_url)

    if upper.startswith("REPORT"):
        return (
            "⚠️ *VerifyNG — File a Fraud Report*\n\n"
            "To file a verified fraud report, please visit our secure web portal:\n"
            f"🔗 {site_url}/reports/submit/\n\n"
            "Anonymous reports are not accepted. "
            "You will need to verify your identity (NIN or BVN) before submitting."
        )

    if upper.startswith("VERIFY"):
        return (
            "✅ *VerifyNG — Trust Profile Verification*\n\n"
            "To build or request a VerifyNG Trust Profile, visit:\n"
            f"🔗 {site_url}/verification/\n\n"
            "Employers and landlords can verify a person or business on the same portal."
        )

    if upper in ("HELP", "HI", "HELLO", "START", "MENU"):
        return (
            "👋 *Welcome to VerifyNG*\n"
            "Nigeria's Public Trust & Safety Platform\n\n"
            "Send one of these commands:\n\n"
            "🔍 *CHECK* <phone/name/account>\n"
            "   — Search for fraud reports on a person or business\n\n"
            "🚨 *REPORT*\n"
            "   — File a fraud or scam report\n\n"
            "✅ *VERIFY*\n"
            "   — Build or check a trust profile\n\n"
            f"🌐 Visit us at {site_url}"
        )

    # Unrecognised input — gentle nudge
    return (
        "🤔 I didn't understand that.\n\n"
        "Send *HELP* to see available commands, or visit:\n"
        f"🔗 {site_url}"
    )


def _handle_check_command(query: str, site_url: str) -> str:
    """
    Perform a public trust lookup for the given query string.
    Uses the existing identities lookup service.
    Returns a formatted WhatsApp reply string.
    """
    try:
        from identities.services import lookup_public_record
        from identities.utils import hash_identifier_value

        # Determine identifier type from query format
        identifier_type = _infer_identifier_type(query)
        if identifier_type:
            try:
                query_hash = hash_identifier_value(identifier_type, query)
                result = lookup_public_record(query_hash, identifier_type)
            except ValueError:
                result = None
        else:
            # Name-based lookup — pass raw query
            result = lookup_public_record(query, "name")

        if not result:
            return (
                f"✅ *No records found for:* {query}\n\n"
                "This person or business has no verified fraud reports on VerifyNG.\n\n"
                f"🌐 Full search: {site_url}/check/"
            )

        report_count = result.get("published_reports_count", 0)
        subject_name = result.get("subject_name", query)
        trust_label = result.get("trust_label", "Unknown")
        trust_colour_emoji = {
            "safe": "🟢",
            "caution": "🟡",
            "high risk": "🔴",
            "unknown": "⚪",
        }.get(trust_label.lower(), "⚪")

        lines = [
            f"🔍 *VerifyNG Check Result*",
            f"",
            f"*Name:* {subject_name}",
            f"*Trust Status:* {trust_colour_emoji} {trust_label}",
            f"*Verified Reports:* {report_count}",
        ]

        if report_count > 0:
            lines.append("")
            lines.append("⚠️ This person/business has active fraud reports.")
            lines.append("Use caution before transacting.")

        lines.append("")
        lines.append(f"🔗 Full details: {site_url}/check/?q={query}")

        return "\n".join(lines)

    except Exception as exc:
        logger.error("WhatsApp CHECK command failed for query=%s: %s", query[:20], exc)
        return (
            "⚠️ *VerifyNG Check*\n\n"
            "We couldn't complete that lookup right now. Please try:\n"
            f"🔗 {site_url}/check/"
        )


def _infer_identifier_type(query: str) -> Optional[str]:
    """
    Infer the identifier type from the query string format.
    Returns 'phone', 'account', or None (name/free-text).
    """
    cleaned = query.strip().replace(" ", "").replace("-", "")
    # Nigerian phone: starts with 0 + 10 digits, or +234 + 10 digits
    if (cleaned.startswith("0") and len(cleaned) == 11 and cleaned.isdigit()):
        return "phone"
    if (cleaned.startswith("+234") and len(cleaned) == 14 and cleaned[1:].isdigit()):
        return "phone"
    if (cleaned.startswith("234") and len(cleaned) == 13 and cleaned.isdigit()):
        return "phone"
    # Nigerian bank account: exactly 10 digits
    if len(cleaned) == 10 and cleaned.isdigit():
        return "account"
    return None


# ---------------------------------------------------------------------------
# Outbound message sending
# ---------------------------------------------------------------------------

def _send_whatsapp_reply(to: str, text: str) -> None:
    """
    Send a text reply to a WhatsApp number via the Meta Cloud API.
    Logs and returns silently on failure — never raises.
    """
    if not _whatsapp_configured():
        logger.warning(
            "WhatsApp reply suppressed (credentials not configured). "
            "Set WHATSAPP_API_TOKEN and WHATSAPP_PHONE_NUMBER_ID."
        )
        return

    phone_number_id = _get_phone_number_id()
    api_version = _get_api_version()
    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }

    headers = {
        "Authorization": f"Bearer {_get_api_token()}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        logger.info(
            "WhatsApp reply sent (to=%s, status=%s)",
            _mask_phone(to),
            response.status_code,
        )
    except requests.exceptions.Timeout:
        logger.error("WhatsApp API timeout sending reply to %s", _mask_phone(to))
    except requests.exceptions.HTTPError as exc:
        logger.error(
            "WhatsApp API HTTP error sending reply to %s: %s — %s",
            _mask_phone(to),
            exc.response.status_code,
            exc.response.text[:200],
        )
    except requests.exceptions.RequestException as exc:
        logger.error(
            "WhatsApp API request error sending reply to %s: %s",
            _mask_phone(to),
            exc,
        )


def _mask_phone(phone: str) -> str:
    """Privacy-safe phone mask for logs."""
    if not phone or len(phone) < 6:
        return "***"
    return f"{phone[:5]}***{phone[-3:]}"

