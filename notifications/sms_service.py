"""
notifications/sms_service.py

Africa's Talking SMS fallback integration for VerifyNG.

Environment variables (all optional — service gracefully degrades if absent):
  AFRICASTALKING_USERNAME  — AT username (use 'sandbox' for testing)
  AFRICASTALKING_API_KEY   — AT API key
  AFRICASTALKING_SENDER_ID — Short code / sender ID (optional)
"""

import logging
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)


class SMSError(Exception):
    """Raised when an SMS cannot be delivered and no retry is possible."""


def _get_credentials() -> tuple:
    username: str = getattr(settings, 'AFRICASTALKING_USERNAME', '') or ''
    api_key: str = getattr(settings, 'AFRICASTALKING_API_KEY', '') or ''
    sender_id: Optional[str] = getattr(settings, 'AFRICASTALKING_SENDER_ID', None) or None

    if not username or not api_key:
        raise SMSError(
            "Africa's Talking credentials not configured. "
            "Set AFRICASTALKING_USERNAME and AFRICASTALKING_API_KEY environment variables."
        )
    return username, api_key, sender_id


def send_sms(to: str, message: str) -> dict:
    """
    Send a single SMS via Africa's Talking.

    Args:
        to:      E.164 or Nigerian local phone number.
        message: Plain-text message body.

    Returns:
        dict with keys: recipient, status, message_id, cost

    Raises:
        SMSError: Credentials missing, API error, or delivery failure.
        ImportError: africastalking package not installed.
    """
    normalised_to = _normalise_nigerian_number(to)

    try:
        import africastalking
    except ImportError as exc:
        raise SMSError(
            "africastalking package is not installed. Run: pip install africastalking"
        ) from exc

    try:
        username, api_key, sender_id = _get_credentials()
    except SMSError:
        logger.warning(
            "SMS not sent to %s — Africa's Talking credentials not configured.",
            _mask_phone(normalised_to),
        )
        raise

    africastalking.initialize(username, api_key)
    sms = africastalking.SMS

    send_kwargs: dict = {"message": message, "recipients": [normalised_to]}
    if sender_id:
        send_kwargs["senderId"] = sender_id

    try:
        response = sms.send(**send_kwargs)
    except Exception as exc:
        logger.error(
            "Africa's Talking API call failed (recipient=%s): %s",
            _mask_phone(normalised_to), exc,
        )
        raise SMSError(f"Africa's Talking API error: {exc}") from exc

    try:
        recipients = response["SMSMessageData"]["Recipients"]
    except (KeyError, TypeError) as exc:
        raise SMSError(f"Unexpected Africa's Talking response structure: {response}") from exc

    if not recipients:
        raise SMSError(f"Africa's Talking returned no recipient records for {_mask_phone(normalised_to)}")

    recipient_result = recipients[0]
    status: str = recipient_result.get("status", "Unknown")

    if status != "Success":
        logger.warning(
            "SMS delivery failure (recipient=%s, status=%s)",
            _mask_phone(normalised_to), status,
        )
        raise SMSError(
            f"Africa's Talking reported delivery failure for {_mask_phone(normalised_to)}: {status}"
        )

    logger.info(
        "SMS dispatched via Africa's Talking (recipient=%s, message_id=%s, cost=%s)",
        _mask_phone(normalised_to),
        recipient_result.get("messageId", "?"),
        recipient_result.get("cost", "?"),
    )

    return {
        "recipient": normalised_to,
        "status": status,
        "message_id": recipient_result.get("messageId"),
        "cost": recipient_result.get("cost"),
    }


def send_sms_safe(to: str, message: str) -> bool:
    """
    Non-raising wrapper for fire-and-forget use in signals/tasks.
    Returns True on success, False on any failure. Never raises.
    """
    try:
        send_sms(to=to, message=message)
        return True
    except SMSError as exc:
        logger.warning("send_sms_safe: SMS suppressed (%s)", exc)
        return False
    except Exception as exc:
        logger.error("send_sms_safe: unexpected error sending SMS: %s", exc)
        return False


def _normalise_nigerian_number(phone: str) -> str:
    """Convert Nigerian local number to E.164 format."""
    cleaned = phone.strip().replace(" ", "").replace("-", "")
    if cleaned.startswith("+"):
        return cleaned
    if cleaned.startswith("234"):
        return f"+{cleaned}"
    if cleaned.startswith("0") and len(cleaned) == 11:
        return f"+234{cleaned[1:]}"
    return cleaned


def _mask_phone(phone: str) -> str:
    """Privacy-safe phone mask for logs (e.g. +2348***678)."""
    if not phone or len(phone) < 6:
        return "***"
    return f"{phone[:7]}***{phone[-3:]}"
