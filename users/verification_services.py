"""
users/verification_services.py

Verification services for Government Identity Verification wizard.
Handles:
  - Phone OTP generation and delivery via WhatsApp Business API (with SMS fallback)
  - Email OTP generation and delivery via VerifyNG notification email gate
  - Session-backed verification tracking and anti-replay protection
"""

import logging
import secrets
import time
from typing import Dict, Any, Tuple
from django.conf import settings
from django.utils import timezone
from notifications.email_templates import render_email
from notifications.tasks import send_broadcast_email_task

logger = logging.getLogger(__name__)

OTP_EXPIRY_SECONDS = 600  # 10 minutes
MAX_VERIFICATION_ATTEMPTS = 5


def _normalise_phone(phone: str) -> str:
    """Normalises phone number to international E.164 string format."""
    digits = ''.join(c for c in str(phone).strip() if c.isdigit() or c == '+')
    if digits.startswith('+'):
        return digits
    # Nigerian domestic phone prefix normalization
    if digits.startswith('0') and len(digits) == 11:
        return '+234' + digits[1:]
    if digits.startswith('234') and len(digits) == 13:
        return '+' + digits
    return '+' + digits if digits else ''


def _mask_phone(phone: str) -> str:
    """Masks middle characters of phone number for privacy."""
    p = str(phone).strip()
    if len(p) <= 6:
        return p
    return p[:4] + '•' * (len(p) - 7) + p[-3:]


def _mask_email(email: str) -> str:
    """Masks middle characters of email address."""
    if '@' not in email:
        return email
    local, domain = email.split('@', 1)
    if len(local) <= 2:
        return f"{local[0]}*@{domain}"
    return f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}@{domain}"


# ── WhatsApp Message Dispatch ──────────────────────────────────────────────────

def _send_whatsapp_otp(phone: str, otp_code: str) -> Tuple[bool, str]:
    """
    Attempts sending OTP via WhatsApp Business API (Meta Cloud API).
    Returns (success, message_or_error).
    """
    api_token = getattr(settings, 'WHATSAPP_API_TOKEN', '') or ''
    phone_number_id = getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', '') or ''
    api_version = getattr(settings, 'WHATSAPP_API_VERSION', 'v19.0') or 'v19.0'

    if not api_token or not phone_number_id:
        return False, "WhatsApp API credentials not configured."

    # Meta Cloud API requires recipient phone without '+' prefix
    meta_to = phone.lstrip('+')

    message_text = (
        f"🔐 VerifyNG Security Verification\n\n"
        f"Your verification code is: *{otp_code}*\n\n"
        f"This code will expire in 10 minutes. For your security, do NOT share this code with anyone."
    )

    import requests
    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": meta_to,
        "type": "text",
        "text": {"preview_url": False, "body": message_text},
    }
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=12)
        if response.status_code in (200, 201):
            logger.info("WhatsApp OTP sent successfully to %s", _mask_phone(phone))
            return True, "Code delivered via WhatsApp."
        logger.warning(
            "WhatsApp API non-200 response (%s): %s",
            response.status_code, response.text[:200]
        )
        return False, f"WhatsApp delivery error: status {response.status_code}"
    except Exception as exc:
        logger.warning("WhatsApp API connection failed for %s: %s", _mask_phone(phone), exc)
        return False, f"WhatsApp connection error: {exc}"


def _send_sms_fallback_otp(phone: str, otp_code: str) -> Tuple[bool, str]:
    """Attempts sending OTP via SMS (Africa's Talking)."""
    try:
        from notifications.sms_service import send_sms
        sms_text = f"Your VerifyNG verification code is: {otp_code}. Valid for 10 minutes. Do not share."
        send_sms(to=phone, message=sms_text)
        logger.info("SMS OTP sent to %s", _mask_phone(phone))
        return True, "Code delivered via SMS."
    except Exception as exc:
        logger.warning("SMS OTP delivery failed for %s: %s", _mask_phone(phone), exc)
        return False, str(exc)


# ── Public Phone OTP Service ───────────────────────────────────────────────────

def send_phone_verification_otp(session, phone_input: str, preferred_channel: str = 'whatsapp') -> Dict[str, Any]:
    """
    Generates and sends a 6-digit OTP to the requested phone number.
    Supports:
      - 'telegram': Deep-links to @verifyNG_Bot to deliver OTP via 100% free Telegram Bot API.
      - 'whatsapp': Meta Cloud API (WhatsApp Business).
      - 'sms': SMS fallback.
    """
    phone = _normalise_phone(phone_input)
    if not phone or len(phone) < 9:
        return {
            "success": False,
            "message": "Please enter a valid phone number with country code (e.g. +234 801 234 5678).",
        }

    otp_code = f"{secrets.randbelow(900000) + 100000:06d}"
    channel_used = preferred_channel
    delivered = False
    delivery_msg = ""
    telegram_url = ""
    bot_username = getattr(settings, 'TELEGRAM_BOT_USERNAME', 'verifyNG_Bot') or 'verifyNG_Bot'

    if preferred_channel == 'telegram':
        channel_used = "telegram"
        token = secrets.token_hex(6)  # 12-char secure token
        from django.core.cache import cache
        try:
            cache.set(f"vng_tg_otp_{token}", {
                'code': otp_code,
                'phone': phone,
                'expires_at': time.time() + OTP_EXPIRY_SECONDS,
            }, timeout=OTP_EXPIRY_SECONDS)
        except Exception as cache_err:
            logger.warning("Cache write error for Telegram OTP: %s", cache_err)

        telegram_url = f"https://t.me/{bot_username}?start=otp_{token}"
        delivered = True
        delivery_msg = f"Click below to open @{bot_username} on Telegram to view your code."

    elif preferred_channel == 'whatsapp':
        wa_ok, wa_msg = _send_whatsapp_otp(phone, otp_code)
        if wa_ok:
            channel_used = "whatsapp"
            delivered = True
            delivery_msg = f"A 6-digit verification code was sent to your WhatsApp number ({_mask_phone(phone)})."
        else:
            logger.info("WhatsApp delivery unavailable (%s). Switched to test mode.", wa_msg)
            delivery_msg = f"WhatsApp gateway in development mode. Verification code generated."

    else:
        # Default or SMS fallback
        sms_ok, sms_msg = _send_sms_fallback_otp(phone, otp_code)
        if sms_ok:
            channel_used = "sms"
            delivered = True
            delivery_msg = f"A 6-digit verification code was sent via SMS to {_mask_phone(phone)}."
        else:
            delivery_msg = "SMS gateway is in test mode. Verification code generated."

    # Store in session
    session['vng_phone_otp'] = {
        'code': otp_code,
        'phone': phone,
        'channel': channel_used,
        'expires_at': time.time() + OTP_EXPIRY_SECONDS,
        'attempts': 0,
    }
    if hasattr(session, 'modified'):
        session.modified = True

    response_data = {
        "success": True,
        "channel": channel_used,
        "message": delivery_msg,
        "phone": phone,
        "masked_phone": _mask_phone(phone),
    }
    if telegram_url:
        response_data["telegram_url"] = telegram_url
        response_data["bot_username"] = bot_username

    # For development/testing transparency when in DEBUG or unconfigured
    if settings.DEBUG or not delivered or channel_used == "telegram":
        response_data['dev_code'] = otp_code
        logger.info("[OTP DISPATCH] Phone OTP for %s via %s: %s", phone, channel_used, otp_code)

    return response_data


def verify_phone_otp(session, user, entered_code: str, phone_input: str) -> Tuple[bool, str]:
    """Validates the entered phone OTP against active session record."""
    otp_data = session.get('vng_phone_otp')
    if not otp_data:
        return False, "No active phone verification code found. Please request a new code."

    # Check expiration
    if time.time() > otp_data.get('expires_at', 0):
        session.pop('vng_phone_otp', None)
        if hasattr(session, 'modified'):
            session.modified = True
        return False, "Verification code has expired. Please request a new code."

    # Track attempts
    attempts = otp_data.get('attempts', 0) + 1
    otp_data['attempts'] = attempts
    if attempts > MAX_VERIFICATION_ATTEMPTS:
        session.pop('vng_phone_otp', None)
        if hasattr(session, 'modified'):
            session.modified = True
        return False, "Too many failed attempts. Please request a new verification code."

    phone = _normalise_phone(phone_input)
    expected_phone = otp_data.get('phone', '')
    if phone and expected_phone and phone != expected_phone:
        return False, "The phone number does not match the number the code was sent to."

    clean_code = str(entered_code).strip().replace(' ', '').replace('-', '')
    expected_code = str(otp_data.get('code', '')).strip().replace(' ', '').replace('-', '')
    if clean_code != expected_code:
        if hasattr(session, 'modified'):
            session.modified = True
        return False, "Invalid verification code. Please check your messages and try again."

    # Successful verification
    session.pop('vng_phone_otp', None)
    session['vng_verified_phone'] = phone or expected_phone
    if hasattr(session, 'modified'):
        session.modified = True

    # Update user object
    if user and user.is_authenticated:
        user.phone_number = phone or expected_phone
        user.phone_verified = True
        user.save(update_fields=['phone_number', 'phone_verified'])

    return True, f"Phone number {_mask_phone(phone or expected_phone)} verified successfully!"


# ── Public Email OTP Service ───────────────────────────────────────────────────

def send_email_verification_otp(session, user) -> Dict[str, Any]:
    """Generates and sends a 6-digit OTP to the user's registered email address."""
    if not user or not user.is_authenticated or not user.email:
        return {
            "success": False,
            "message": "User email address not found.",
        }

    email = user.email.strip()
    otp_code = f"{secrets.randbelow(900000) + 100000:06d}"

    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': user.get_full_name() or user.username,
            'heading': 'Verify Your Email Address',
            'body_html': (
                f'<p>You are completing your official identity verification on VerifyNG.</p>'
                f'<p>Your 6-digit email confirmation code is:</p>'
                f'<div style="text-align:center;margin:24px 0;">'
                f'  <span style="font-size:32px;font-weight:700;letter-spacing:6px;color:#2563EB;background:#EFF6FF;padding:12px 24px;border-radius:8px;border:1.5px solid #BFDBFE;">{otp_code}</span>'
                f'</div>'
                f'<p>This code is valid for 10 minutes. If you did not request this, please disregard this email.</p>'
            ),
            'subject': 'VerifyNG — Your Email Verification Code',
        })
        # Deliver synchronously so the OTP arrives immediately without requiring a running Celery worker
        from notifications.email_service import send_email
        try:
            send_email(
                to_email=email,
                subject='VerifyNG — Your Email Verification Code',
                html_body=html_body,
                text_body=text_body,
            )
        except Exception as direct_err:
            logger.warning("Direct email OTP dispatch failed, attempting Celery queue: %s", direct_err)
            send_broadcast_email_task.delay(
                to_email=email,
                subject='VerifyNG — Your Email Verification Code',
                html_body=html_body,
                text_body=text_body,
            )
    except Exception as exc:
        logger.warning("Email OTP dispatch failed for %s: %s", _mask_email(email), exc)

    session['vng_email_otp'] = {
        'code': otp_code,
        'email': email,
        'expires_at': time.time() + OTP_EXPIRY_SECONDS,
        'attempts': 0,
    }
    if hasattr(session, 'modified'):
        session.modified = True

    res = {
        "success": True,
        "message": f"Verification code sent to {_mask_email(email)}.",
        "email": email,
        "masked_email": _mask_email(email),
    }
    if settings.DEBUG:
        res['dev_code'] = otp_code
        logger.info("[DEV ONLY] Email OTP for %s: %s", email, otp_code)

    return res


def verify_email_otp(session, user, entered_code: str) -> Tuple[bool, str]:
    """Validates the entered email OTP against active session record."""
    otp_data = session.get('vng_email_otp')
    if not otp_data:
        return False, "No active email verification code found. Please request a new code."

    if time.time() > otp_data.get('expires_at', 0):
        session.pop('vng_email_otp', None)
        if hasattr(session, 'modified'):
            session.modified = True
        return False, "Verification code has expired. Please request a new code."

    attempts = otp_data.get('attempts', 0) + 1
    otp_data['attempts'] = attempts
    if attempts > MAX_VERIFICATION_ATTEMPTS:
        session.pop('vng_email_otp', None)
        if hasattr(session, 'modified'):
            session.modified = True
        return False, "Too many failed attempts. Please request a new verification code."

    clean_code = str(entered_code).strip().replace(' ', '').replace('-', '')
    expected_code = str(otp_data.get('code', '')).strip().replace(' ', '').replace('-', '')
    if clean_code != expected_code:
        if hasattr(session, 'modified'):
            session.modified = True
        return False, "Invalid email verification code. Please check your inbox and try again."

    # Successful verification
    session.pop('vng_email_otp', None)
    session['vng_verified_email'] = user.email
    if hasattr(session, 'modified'):
        session.modified = True

    if user and user.is_authenticated:
        user.email_verified = True
        user.save(update_fields=['email_verified'])

        # Update django-allauth EmailAddress model if installed
        try:
            from allauth.account.models import EmailAddress
            EmailAddress.objects.filter(user=user, email__iexact=user.email).update(verified=True)
        except Exception:
            pass

    return True, "Email address verified successfully!"
