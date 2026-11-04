"""
integrations/messaging/telegram_bot.py

VerifyNG Official Telegram Bot Integration & Multi-Entity Check Engine.

Capabilities:
- Commands: /check, /start, /help, /report, /verify
- Multi-Entity Detection:
    1. Phone numbers: 08012345678, +2348012345678
    2. Bank Accounts: 0123456789 (Access Bank), 0123456789 GTBank, 0123456789
       -> Cross-checks Verified Settlement Bank Binding for merchants!
    3. Store names & Merchant Handles: @sendmoorng, sendmoorng, Sendmoor
    4. Workforce Certificate IDs: VNG-2026-99E1E30C, CERT-XXXX
    5. CAC Registration Numbers: RC123456, BN987654, 9909988777654
    6. NIN (National Identity Number): NIN 12345678901, 12345678901
    7. General name & subject lookups
- Inline Queries: Type @verifyng_bot <query> inside any Telegram group or chat.
"""

import html
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import requests
from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Telegram Settings & API Helpers
# ---------------------------------------------------------------------------

def get_bot_token() -> str:
    return getattr(settings, 'TELEGRAM_BOT_TOKEN', '') or ''


def get_bot_username() -> str:
    return getattr(settings, 'TELEGRAM_BOT_USERNAME', 'verifyng_bot') or 'verifyng_bot'


def get_webhook_secret() -> str:
    return getattr(settings, 'TELEGRAM_WEBHOOK_SECRET', '') or ''


def is_telegram_configured() -> bool:
    return bool(get_bot_token())


def get_telegram_api_url(method: str) -> str:
    token = get_bot_token()
    return f"https://api.telegram.org/bot{token}/{method}"


def send_telegram_message(
    chat_id: int | str,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    reply_to_message_id: Optional[int] = None,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True,
) -> bool:
    """
    Sends a message via the Telegram Bot API.
    Fails safely without raising unhandled exceptions.
    """
    if not is_telegram_configured():
        logger.warning("Telegram Bot is not configured (TELEGRAM_BOT_TOKEN missing).")
        return False

    url = get_telegram_api_url("sendMessage")
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    try:
        resp = requests.post(url, json=payload, timeout=8)
        if not resp.ok:
            logger.error("Telegram sendMessage error (%s): %s", resp.status_code, resp.text)
            return False
        return True
    except Exception as exc:
        logger.error("Failed to post message to Telegram API: %s", exc)
        return False


def set_telegram_webhook(webhook_url: str, secret_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Registers the webhook endpoint with Telegram Bot API.
    """
    if not is_telegram_configured():
        return {"ok": False, "description": "TELEGRAM_BOT_TOKEN not configured"}

    url = get_telegram_api_url("setWebhook")
    payload: Dict[str, Any] = {
        "url": webhook_url,
        "allowed_updates": ["message", "inline_query", "callback_query"],
    }
    secret = secret_token or get_webhook_secret()
    if secret:
        payload["secret_token"] = secret

    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.json()
    except Exception as exc:
        logger.error("Failed to set Telegram webhook: %s", exc)
        return {"ok": False, "description": str(exc)}


def answer_inline_query(inline_query_id: str, results: List[Dict[str, Any]]) -> bool:
    """
    Responds to an inline query update from Telegram.
    """
    if not is_telegram_configured():
        return False

    url = get_telegram_api_url("answerInlineQuery")
    payload = {
        "inline_query_id": inline_query_id,
        "results": results,
        "cache_time": 30,
        "is_personal": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=8)
        return resp.ok
    except Exception as exc:
        logger.error("Failed to answer Telegram inline query: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Multi-Entity Unified Check Engine
# ---------------------------------------------------------------------------

def perform_unified_check(query_str: str) -> Dict[str, Any]:
    """
    Dispatches a query string across all VerifyNG trust domains:
      1. Bank Account (10 digits) + Merchant Settlement Bank cross-check
      2. Store Name or Merchant Handle (@sendmoorng, sendmoorng)
      3. Workforce Certificate ID (VNG-2026-..., CERT-...)
      4. CAC / Corporate Number (RC123456, BN987654)
      5. Phone Number (Nigerian mobile/landline)
      6. NIN (11 digits)
      7. Subject / Person / Entity Name fallback
    """
    from core.email_utils import get_dynamic_base_url
    site_url = get_dynamic_base_url()

    raw_query = query_str.strip()
    if not raw_query:
        return {"found": False, "entity_type": "empty", "query": raw_query}

    from identities.services import lookup_public_record
    from identities.utils import hash_identifier_value, normalize_identifier
    from payments.models import MerchantProfile
    from verification.models import VerificationCertificate
    from employer.models import EmployerProfile
    from identities.models import SubjectEntity

    # -----------------------------------------------------------------------
    # Case A: Store Handle prefix or explicit Merchant Handle query
    # E.g. "@sendmoorng" or store handle starting with @
    # -----------------------------------------------------------------------
    if raw_query.startswith('@'):
        clean_slug = raw_query.lstrip('@').strip().lower()
        merchant = MerchantProfile.objects.filter(store_slug__iexact=clean_slug).first()
        if merchant:
            return _build_merchant_result(merchant, site_url, query=raw_query)

    # -----------------------------------------------------------------------
    # Case B: Workforce Certificate ID
    # E.g. VNG-2026-99E1E30C, VNG-CERT-..., CERT-...
    # -----------------------------------------------------------------------
    upper_query = raw_query.upper().strip()
    if upper_query.startswith("VNG-") or upper_query.startswith("CERT-") or "-CERT-" in upper_query:
        cert = VerificationCertificate.objects.filter(certificate_id__iexact=upper_query).first()
        if not cert:
            cert = VerificationCertificate.objects.filter(certificate_id__icontains=upper_query).first()
        if cert:
            return _build_certificate_result(cert, site_url, query=raw_query)

    # -----------------------------------------------------------------------
    # Case C: Bank Account (10 digits) with optional Bank Name
    # E.g. "0123456789 (Access Bank)" or "0123456789 Access Bank" or "0123456789"
    # -----------------------------------------------------------------------
    acc_match = re.search(r'\b(\d{10})\b', raw_query)
    if acc_match:
        account_number = acc_match.group(1)
        # Extract optional bank name from parentheses or surrounding words
        bank_name = ""
        paren_match = re.search(r'\(([^)]+)\)', raw_query)
        if paren_match:
            bank_name = paren_match.group(1).strip()
        else:
            # Look for words other than the digits
            surrounding = raw_query.replace(account_number, '').strip()
            surrounding = re.sub(r'(?i)\b(check|bank|acct|account)\b', '', surrounding).strip()
            if surrounding:
                bank_name = surrounding.strip(" -:,()")

        # 1. Cross-check Verified Settlement Bank Binding for Merchants!
        merchant_bound = MerchantProfile.objects.filter(
            bank_account=account_number,
            status='active'
        ).first()
        if not merchant_bound:
            # Check any merchant status
            merchant_bound = MerchantProfile.objects.filter(
                bank_account=account_number
            ).first()

        # 2. Check Fraud Database for this account
        fraud_data = None
        try:
            acc_hash = hash_identifier_value('account', account_number)
            fraud_data = lookup_public_record(acc_hash)
        except Exception:
            fraud_data = None

        return {
            "found": True,
            "entity_type": "bank_account",
            "query": raw_query,
            "account_number": account_number,
            "bank_name": bank_name or (merchant_bound.bank_name if merchant_bound else ""),
            "merchant_bound": merchant_bound,
            "fraud_data": fraud_data,
            "site_url": site_url,
        }

    # -----------------------------------------------------------------------
    # Case D: CAC Registration Number (RC / BN / IT / LLP)
    # E.g. RC123456, BN987654, RC 123456, BN 987654, 9909988777654
    # -----------------------------------------------------------------------
    cac_match = re.search(r'(?i)\b(RC|BN|IT|LLP)\s*[-:]?\s*(\d{3,20})\b', raw_query)
    clean_numeric_cac = re.sub(r'\D', '', raw_query)
    is_cac_format = bool(cac_match) or (raw_query.upper().startswith("CAC") and clean_numeric_cac)

    if is_cac_format:
        if cac_match:
            prefix = cac_match.group(1).upper()
            num = cac_match.group(2)
            cac_code = f"{prefix}{num}"
        else:
            cac_code = f"RC{clean_numeric_cac}" if clean_numeric_cac else raw_query.upper()

        # Search EmployerProfile
        employer = EmployerProfile.objects.filter(
            models.Q(company_rc_number__iexact=cac_code) |
            models.Q(company_rc_number__iexact=clean_numeric_cac) |
            models.Q(company_rc_number__icontains=clean_numeric_cac)
        ).first()

        # Check fraud reports
        fraud_data = None
        try:
            cac_norm = normalize_identifier('cac', cac_code)
            cac_hash = hash_identifier_value('cac', cac_norm)
            fraud_data = lookup_public_record(cac_hash)
        except Exception:
            fraud_data = None

        return {
            "found": True,
            "entity_type": "cac",
            "query": raw_query,
            "cac_code": cac_code,
            "employer": employer,
            "fraud_data": fraud_data,
            "site_url": site_url,
        }

    # -----------------------------------------------------------------------
    # Case E: Phone Number (Nigerian Mobile / Landline)
    # 11 digits starting with 0, or +234/234
    # -----------------------------------------------------------------------
    digits_only = re.sub(r'\D', '', raw_query)
    is_phone = (
        (len(digits_only) == 11 and digits_only.startswith('0')) or
        (len(digits_only) == 13 and digits_only.startswith('234')) or
        (raw_query.strip().startswith('+234') and len(digits_only) == 13)
    )
    if is_phone:
        normalized_phone = ""
        try:
            normalized_phone = normalize_identifier('phone', raw_query)
        except Exception:
            if len(digits_only) == 11 and digits_only.startswith('0'):
                normalized_phone = '234' + digits_only[1:]
            elif len(digits_only) == 13 and digits_only.startswith('234'):
                normalized_phone = digits_only

        # Check if attached to verified merchant
        local_phone = '0' + normalized_phone[3:] if normalized_phone.startswith('234') else normalized_phone
        merchant_match = MerchantProfile.objects.filter(
            models.Q(whatsapp_number__icontains=local_phone) |
            models.Q(whatsapp_number__icontains=normalized_phone),
            status='active'
        ).first()

        fraud_data = None
        try:
            phone_hash = hash_identifier_value('phone', normalized_phone)
            fraud_data = lookup_public_record(phone_hash)
        except Exception:
            fraud_data = None

        return {
            "found": True,
            "entity_type": "phone",
            "query": raw_query,
            "phone_formatted": local_phone,
            "phone_e164": f"+{normalized_phone}",
            "merchant_match": merchant_match,
            "fraud_data": fraud_data,
            "site_url": site_url,
        }

    # -----------------------------------------------------------------------
    # Case F: NIN (National Identity Number)
    # E.g. "NIN 12345678901" or 11 digits not starting with 0
    # -----------------------------------------------------------------------
    is_explicit_nin = raw_query.upper().startswith("NIN") and len(digits_only) == 11
    is_nin_length = len(digits_only) == 11 and not digits_only.startswith('0')
    if is_explicit_nin or is_nin_length:
        masked_nin = f"{digits_only[:3]}*****{digits_only[-3:]}"
        fraud_data = None
        try:
            nin_hash = hash_identifier_value('nin', digits_only)
            fraud_data = lookup_public_record(nin_hash)
        except Exception:
            fraud_data = None

        return {
            "found": True,
            "entity_type": "nin",
            "query": raw_query,
            "masked_nin": masked_nin,
            "fraud_data": fraud_data,
            "site_url": site_url,
        }

    # -----------------------------------------------------------------------
    # Case G: Store Name / Merchant Slug without @ prefix
    # E.g. "sendmoorng" or "Sendmoor"
    # -----------------------------------------------------------------------
    clean_text = raw_query.strip().lower()
    merchant = MerchantProfile.objects.filter(
        models.Q(store_slug__iexact=clean_text) |
        models.Q(store_name__iexact=raw_query)
    ).first()
    if not merchant:
        merchant = MerchantProfile.objects.filter(store_name__icontains=raw_query).first()
    if merchant:
        return _build_merchant_result(merchant, site_url, query=raw_query)

    # -----------------------------------------------------------------------
    # Case H: Employer Profile by Company Name
    # -----------------------------------------------------------------------
    employer = EmployerProfile.objects.filter(company_name__icontains=raw_query).first()
    if employer:
        fraud_data = None
        if employer.company_rc_number:
            try:
                cac_norm = normalize_identifier('cac', employer.company_rc_number)
                cac_hash = hash_identifier_value('cac', cac_norm)
                fraud_data = lookup_public_record(cac_hash)
            except Exception:
                fraud_data = None

        return {
            "found": True,
            "entity_type": "cac",
            "query": raw_query,
            "cac_code": employer.company_rc_number or "Registered Employer",
            "employer": employer,
            "fraud_data": fraud_data,
            "site_url": site_url,
        }

    # -----------------------------------------------------------------------
    # Case I: Person / Subject Entity Name Fallback
    # -----------------------------------------------------------------------
    sub = SubjectEntity.objects.filter(name__icontains=raw_query).first()
    if sub:
        first_ident = sub.identifiers.first()
        fraud_data = None
        if first_ident:
            fraud_data = lookup_public_record(first_ident.value_hash)
        return {
            "found": True,
            "entity_type": "subject",
            "query": raw_query,
            "subject": sub,
            "fraud_data": fraud_data,
            "site_url": site_url,
        }

    # -----------------------------------------------------------------------
    # Case J: Nothing found
    # -----------------------------------------------------------------------
    return {
        "found": False,
        "entity_type": "unknown",
        "query": raw_query,
        "site_url": site_url,
    }


def _build_merchant_result(merchant, site_url: str, query: str) -> Dict[str, Any]:
    from identities.services import lookup_public_record
    from identities.utils import hash_identifier_value

    fraud_data = None
    if merchant.bank_account:
        try:
            acc_hash = hash_identifier_value('account', merchant.bank_account)
            fraud_data = lookup_public_record(acc_hash)
        except Exception:
            pass

    return {
        "found": True,
        "entity_type": "merchant",
        "query": query,
        "merchant": merchant,
        "fraud_data": fraud_data,
        "site_url": site_url,
    }


def _build_certificate_result(cert, site_url: str, query: str) -> Dict[str, Any]:
    return {
        "found": True,
        "entity_type": "certificate",
        "query": query,
        "certificate": cert,
        "site_url": site_url,
    }


# ---------------------------------------------------------------------------
# HTML Result Formatter for Telegram
# ---------------------------------------------------------------------------

def format_check_result_html(result: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Renders structured Telegram HTML and creates inline buttons.
    """
    site_url = result.get("site_url", "https://verifyng.com").rstrip('/')
    query = html.escape(result.get("query", ""))
    entity_type = result.get("entity_type", "unknown")

    # -----------------------------------------------------------------------
    # 1. MERCHANT RESULT
    # -----------------------------------------------------------------------
    if entity_type == "merchant":
        m = result["merchant"]
        store_name = html.escape(m.store_name)
        store_slug = html.escape(m.store_slug)
        is_active = (m.status == 'active')
        status_badge = "🛡️ <b>VERIFIED MERCHANT</b> (Active Anti-Scam Shield)" if is_active else f"⚠️ <b>Status:</b> {html.escape(m.get_status_display())}"

        lines = [
            "🏪 <b>VerifyNG Verified Merchant Search</b>",
            "━━━━━━━━━━━━━━━━━━━━━",
            f"<b>Store:</b> {store_name} (@{store_slug})",
            f"<b>Trust Status:</b> {status_badge}",
            f"<b>Category:</b> {html.escape(m.category or 'Merchant')} • {html.escape(m.operating_state or 'Nigeria')}",
        ]

        if m.display_bank_on_seal and m.bank_account and m.bank_name:
            acc_name = f" ({html.escape(m.bank_account_name)})" if m.bank_account_name else ""
            lines.extend([
                "",
                "🔒 <b>Verified Settlement Bank Binding:</b>",
                f"🏦 {html.escape(m.bank_name)}: <code>{html.escape(m.bank_account)}</code>{acc_name}",
                "<i>⚠️ Rule: Pay ONLY to this verified settlement account to stay 100% protected.</i>",
            ])

        fraud = result.get("fraud_data")
        reports_count = fraud.get("published_reports_count", 0) if fraud else 0
        if reports_count > 0:
            lines.extend([
                "",
                f"🚨 <b>Warning:</b> {reports_count} verified fraud report(s) on record for this settlement account.",
            ])
        else:
            lines.extend([
                "",
                "✅ <b>Fraud Record:</b> Clean (0 active fraud reports)",
            ])

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━",
            f"🌐 <a href=\"{site_url}/merchants/{store_slug}/\">View Official Merchant Trust Profile</a>",
        ])

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🛡️ View Verified Seal", "url": f"{site_url}/merchants/{store_slug}/"},
                    {"text": "🚨 Report Fraud", "url": f"{site_url}/reports/submit/"},
                ]
            ]
        }
        return "\n".join(lines), keyboard

    # -----------------------------------------------------------------------
    # 2. WORKFORCE TRUST CERTIFICATE RESULT
    # -----------------------------------------------------------------------
    if entity_type == "certificate":
        c = result["certificate"]
        cert_id = html.escape(c.certificate_id)
        holder_name = html.escape(c.holder.get_full_name() or c.holder.username if c.holder else (c.subject.name if c.subject else "Authorized Candidate"))
        status = c.status.lower()

        if status == 'active':
            status_badge = "🟢 <b>ACTIVE &amp; OFFICIALLY CLEARED</b>"
        elif status == 'suspended':
            status_badge = "🟡 <b>SUSPENDED</b> (Compliance Hold)"
        elif status == 'revoked':
            status_badge = "🔴 <b>REVOKED</b> (Discredited / Nullified)"
        else:
            status_badge = f"⚪ <b>{status.upper()}</b>"

        check_level = html.escape(c.get_check_level_display()) if hasattr(c, 'get_check_level_display') else "Standard"

        lines = [
            "📜 <b>VerifyNG Workforce Trust Certificate</b>",
            "━━━━━━━━━━━━━━━━━━━━━",
            f"<b>Certificate ID:</b> <code>{cert_id}</code>",
            f"<b>Holder:</b> {holder_name}",
            f"<b>Status:</b> {status_badge}",
            f"<b>Clearance Level:</b> {check_level}",
            f"<b>Issued:</b> {c.issued_at.strftime('%d %b %Y') if c.issued_at else 'N/A'}",
        ]
        if c.expires_at:
            lines.append(f"<b>Valid Through:</b> {c.expires_at.strftime('%d %b %Y')}")

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━",
            f"🌐 <a href=\"{site_url}/verify/certificate/{cert_id}/\">Verify Original Security Document</a>",
        ])

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📜 View Certificate", "url": f"{site_url}/verify/certificate/{cert_id}/"},
                ]
            ]
        }
        return "\n".join(lines), keyboard

    # -----------------------------------------------------------------------
    # 3. BANK ACCOUNT RESULT
    # -----------------------------------------------------------------------
    if entity_type == "bank_account":
        acc_no = html.escape(result["account_number"])
        bank_name = html.escape(result.get("bank_name", "") or "Nigerian Bank")
        m_bound = result.get("merchant_bound")
        fraud = result.get("fraud_data")
        reports_count = fraud.get("published_reports_count", 0) if fraud else 0
        trust_label = fraud.get("trust_label", "Safe") if fraud else "Safe"

        lines = [
            "🏦 <b>VerifyNG Bank Account Safety Check</b>",
            "━━━━━━━━━━━━━━━━━━━━━",
            f"<b>Account:</b> <code>{acc_no}</code>",
            f"<b>Bank:</b> {bank_name}",
        ]

        if m_bound:
            store_name = html.escape(m_bound.store_name)
            store_slug = html.escape(m_bound.store_slug)
            lines.extend([
                "",
                f"🛡️ <b>Verified Merchant Settlement Account:</b>",
                f"Bound to: <b>{store_name}</b> (@{store_slug})",
                "✅ <i>This account is legally bound to a verified merchant.</i>",
            ])

        lines.append("")
        if reports_count > 0:
            lines.extend([
                f"🚨 <b>Trust Rating:</b> 🔴 HIGH RISK",
                f"⚠️ <b>Active Fraud Reports:</b> {reports_count} verified scam report(s)",
                "<i>Caution: Do NOT transfer funds to this account before verifying!</i>",
            ])
        else:
            lines.extend([
                f"🛡️ <b>Trust Rating:</b> 🟢 CLEAN / NO ACTIVE REPORTS",
                "✅ 0 verified scam reports registered on VerifyNG.",
            ])

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━",
            f"🔗 <a href=\"{site_url}/check/?q={acc_no}\">Run Comprehensive Background Check</a>",
        ])

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🔍 Full Report", "url": f"{site_url}/check/?q={acc_no}"},
                    {"text": "🚨 Report Scam", "url": f"{site_url}/reports/submit/"},
                ]
            ]
        }
        return "\n".join(lines), keyboard

    # -----------------------------------------------------------------------
    # 4. CAC / CORPORATE REGISTRATION RESULT
    # -----------------------------------------------------------------------
    if entity_type == "cac":
        cac_code = html.escape(result["cac_code"])
        emp = result.get("employer")
        fraud = result.get("fraud_data")
        reports_count = fraud.get("published_reports_count", 0) if fraud else 0

        lines = [
            "🏢 <b>VerifyNG Corporate &amp; CAC Verification</b>",
            "━━━━━━━━━━━━━━━━━━━━━",
            f"<b>Registration:</b> <code>{cac_code}</code>",
        ]

        if emp:
            co_name = html.escape(emp.company_name)
            v_badge = "🛡️ <b>VERIFIED EMPLOYER / AGENCY</b>" if emp.is_verified else "⏳ Registration Pending Verification"
            lines.extend([
                f"<b>Company:</b> {co_name}",
                f"<b>Status:</b> {v_badge}",
                f"<b>Industry:</b> {html.escape(emp.industry or 'Corporate')}",
            ])
        else:
            lines.append("<i>CAC record queried against national business database.</i>")

        lines.append("")
        if reports_count > 0:
            lines.append(f"🚨 <b>Fraud Reports:</b> {reports_count} active report(s)")
        else:
            lines.append("✅ <b>Fraud Record:</b> Clean (0 active reports)")

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━",
            f"🔗 <a href=\"{site_url}/check/?q={cac_code}\">View Enterprise Vetting Record</a>",
        ])

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🏢 Enterprise Details", "url": f"{site_url}/check/?q={cac_code}"},
                ]
            ]
        }
        return "\n".join(lines), keyboard

    # -----------------------------------------------------------------------
    # 5. PHONE NUMBER RESULT
    # -----------------------------------------------------------------------
    if entity_type == "phone":
        phone_no = html.escape(result.get("phone_formatted", query))
        m_bound = result.get("merchant_match")
        fraud = result.get("fraud_data")
        reports_count = fraud.get("published_reports_count", 0) if fraud else 0

        lines = [
            "📱 <b>VerifyNG Phone Safety Check</b>",
            "━━━━━━━━━━━━━━━━━━━━━",
            f"<b>Number:</b> <code>{phone_no}</code>",
        ]

        if m_bound:
            lines.extend([
                f"<b>Associated Merchant:</b> {html.escape(m_bound.store_name)} (@{html.escape(m_bound.store_slug)})",
                "✅ <i>Official verified contact number.</i>",
            ])

        lines.append("")
        if reports_count > 0:
            lines.extend([
                f"🚨 <b>Trust Status:</b> 🔴 HIGH RISK",
                f"⚠️ <b>Fraud Reports:</b> {reports_count} verified scam report(s)",
                "<i>Warning: Multiple scam complaints registered on this number.</i>",
            ])
        else:
            lines.extend([
                f"🛡️ <b>Trust Status:</b> 🟢 CLEAN / SAFE",
                "✅ 0 verified scam reports registered on VerifyNG.",
            ])

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━",
            f"🔗 <a href=\"{site_url}/check/?q={phone_no}\">View Full Phone Audit</a>",
        ])

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🔍 View Report", "url": f"{site_url}/check/?q={phone_no}"},
                    {"text": "🚨 Report Number", "url": f"{site_url}/reports/submit/"},
                ]
            ]
        }
        return "\n".join(lines), keyboard

    # -----------------------------------------------------------------------
    # 6. NIN RESULT
    # -----------------------------------------------------------------------
    if entity_type == "nin":
        masked_nin = html.escape(result["masked_nin"])
        fraud = result.get("fraud_data")
        reports_count = fraud.get("published_reports_count", 0) if fraud else 0

        lines = [
            "🪪 <b>VerifyNG National Identity Check</b>",
            "━━━━━━━━━━━━━━━━━━━━━",
            f"<b>NIN:</b> <code>{masked_nin}</code>",
            "<i>(National privacy protection applied)</i>",
            "",
        ]
        if reports_count > 0:
            lines.append(f"🚨 <b>Warning:</b> {reports_count} verified fraud record(s) on file.")
        else:
            lines.append("✅ <b>Status:</b> Clean identity (0 active fraud records)")

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━",
            f"🔗 <a href=\"{site_url}/check/\">Verify on VerifyNG Security Portal</a>",
        ])

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🔍 National Registry", "url": f"{site_url}/check/"},
                ]
            ]
        }
        return "\n".join(lines), keyboard

    # -----------------------------------------------------------------------
    # 7. UNKNOWN / NO RECORD FOUND
    # -----------------------------------------------------------------------
    lines = [
        "🔍 <b>VerifyNG Trust Check Result</b>",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"<b>Query:</b> <code>{query}</code>",
        "",
        "✅ <b>No Active Fraud Reports Found</b>",
        "This identifier has no reported scam allegations or blacklists on VerifyNG.",
        "",
        "💡 <i>Tip: If this is an online seller, ask them for their verified store handle (e.g. <code>@sendmoorng</code>) or verified settlement bank to guarantee escrow/reputation protection.</i>",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"🌐 <a href=\"{site_url}/check/?q={query}\">Search Full Platform Database</a>",
    ]

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🔍 Full Search", "url": f"{site_url}/check/?q={query}"},
                {"text": "🚨 Report Fraud", "url": f"{site_url}/reports/submit/"},
            ]
        ]
    }
    return "\n".join(lines), keyboard


# ---------------------------------------------------------------------------
# Telegram Bot Webhook & Update Dispatcher
# ---------------------------------------------------------------------------

def handle_telegram_update(update: Dict[str, Any]) -> None:
    """
    Main entry point for handling parsed Telegram webhook updates.
    """
    from core.email_utils import get_dynamic_base_url
    site_url = get_dynamic_base_url().rstrip('/')

    # 1. Inline Query Support (e.g. @verifyng_bot 08012345678)
    if "inline_query" in update:
        _handle_inline_query(update["inline_query"], site_url)
        return

    # 2. Inbound Message Handling
    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    if not chat_id:
        return

    message_id = message.get("message_id")
    raw_text = (message.get("text") or "").strip()
    if not raw_text:
        return

    # Process Commands
    lower_text = raw_text.lower()

    if lower_text.startswith("/start"):
        _send_start_welcome(chat_id, message.get("from", {}), site_url)
        return

    if lower_text.startswith("/help"):
        _send_help_guide(chat_id, site_url)
        return

    if lower_text.startswith("/report"):
        text = (
            "🚨 <b>File a Verified Fraud Report</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "Protect the Nigerian public by reporting scams, impersonation, or bounced transfers.\n\n"
            "• Anonymous reports are barred to prevent smear campaigns.\n"
            "• Evidence and identity verification (NIN/BVN) are required.\n\n"
            f"🔗 <a href=\"{site_url}/reports/submit/\">Click here to file a verified report</a>"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "🚨 Open Report Form", "url": f"{site_url}/reports/submit/"}]
            ]
        }
        send_telegram_message(chat_id, text, reply_markup=keyboard, reply_to_message_id=message_id)
        return

    if lower_text.startswith("/verify"):
        text = (
            "🛡️ <b>Get Verified on VerifyNG</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "Build unstoppable consumer trust and protect your business reputation:\n\n"
            "• <b>Merchants &amp; Instagram Sellers:</b> Get the TrustPass™ Verified Badge &amp; Settlement Bank Binding.\n"
            "• <b>Workers &amp; Jobseekers:</b> Obtain a tamper-proof Workforce Trust Certificate.\n"
            "• <b>Employers &amp; Landlords:</b> Verify your CAC registration and screen staff.\n\n"
            f"🔗 <a href=\"{site_url}/verify/\">Start Verification on VerifyNG</a>"
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🏪 Merchant Verification", "url": f"{site_url}/merchants/apply/"},
                    {"text": "📜 Candidate Clearance", "url": f"{site_url}/verify/"},
                ]
            ]
        }
        send_telegram_message(chat_id, text, reply_markup=keyboard, reply_to_message_id=message_id)
        return

    # /check command or direct text query
    query_body = ""
    if lower_text.startswith("/check"):
        # Strip "/check" or "/check@botname"
        parts = raw_text.split(maxsplit=1)
        if len(parts) > 1:
            query_body = parts[1].strip()
        else:
            _send_check_usage(chat_id)
            return
    else:
        # If in a private 1-on-1 chat, allow direct text lookup without needing /check!
        chat_type = chat.get("type", "private")
        if chat_type == "private":
            query_body = raw_text
        else:
            return  # In group chats, ignore messages that don't start with /check

    # Execute Unified Check
    result = perform_unified_check(query_body)
    reply_html, keyboard = format_check_result_html(result)
    send_telegram_message(chat_id, reply_html, reply_markup=keyboard, reply_to_message_id=message_id)


def _send_start_welcome(chat_id: int | str, from_user: Dict[str, Any], site_url: str) -> None:
    first_name = html.escape(from_user.get("first_name", "there"))
    text = (
        f"👋 <b>Welcome, {first_name}!</b>\n\n"
        "I am the <b>VerifyNG Security Bot</b> 🛡️ — Nigeria's official public safety and anti-scam intelligence assistant.\n\n"
        "<b>What I Can Check Instantly:</b>\n"
        "• 📱 <b>Phone Numbers:</b> <code>/check 08012345678</code>\n"
        "• 🏦 <b>Bank Accounts:</b> <code>/check 0123456789 (Access Bank)</code>\n"
        "• 🏪 <b>Store Names &amp; Handles:</b> <code>/check @sendmoorng</code>\n"
        "• 🏢 <b>CAC Registrations:</b> <code>/check RC123456</code>\n"
        "• 📜 <b>Workforce Certificates:</b> <code>/check VNG-2026-99E1E30C</code>\n"
        "• 🪪 <b>NIN Identity:</b> <code>/check NIN 12345678901</code>\n\n"
        "<i>In private chat, you can also simply send any number, store name, or account directly!</i>"
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🔍 Help & Instructions", "callback_data": "help"},
                {"text": "🌐 Visit Website", "url": site_url},
            ],
            [
                {"text": "🚨 Report a Scam", "url": f"{site_url}/reports/submit/"},
                {"text": "🛡️ Verify My Store", "url": f"{site_url}/merchants/apply/"},
            ]
        ]
    }
    send_telegram_message(chat_id, text, reply_markup=keyboard)


def _send_help_guide(chat_id: int | str, site_url: str) -> None:
    text = (
        "📖 <b>VerifyNG Bot — Command Guide</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>1. Bank Account Check:</b>\n"
        "<code>/check 0123456789 (Access Bank)</code>\n"
        "<i>Cross-references verified merchant settlement accounts and active fraud complaints.</i>\n\n"
        "<b>2. Phone Number Check:</b>\n"
        "<code>/check 08012345678</code>\n"
        "<i>Audits seller phone numbers against community scam reports.</i>\n\n"
        "<b>3. Merchant Store / Handle:</b>\n"
        "<code>/check @sendmoorng</code> or <code>/check sendmoorng</code>\n"
        "<i>Validates Verified Merchant Seal, legal binding, and approved bank details.</i>\n\n"
        "<b>4. Corporate / CAC Registry:</b>\n"
        "<code>/check RC123456</code> or <code>/check BN987654</code>\n"
        "<i>Verifies business legitimacy and registered status.</i>\n\n"
        "<b>5. Candidate Trust Certificate:</b>\n"
        "<code>/check VNG-2026-99E1E30C</code>\n"
        "<i>Verifies tamper-proof background check and criminal clearance credentials.</i>\n\n"
        "<b>6. National Identity:</b>\n"
        "<code>/check NIN 12345678901</code>\n\n"
        f"🌐 <b>Website:</b> <a href=\"{site_url}\">{site_url}</a>"
    )
    send_telegram_message(chat_id, text)


def _send_check_usage(chat_id: int | str) -> None:
    text = (
        "ℹ️ <b>How to Use /check:</b>\n\n"
        "Please provide an identifier after the command:\n"
        "• <code>/check 08012345678</code> (Phone)\n"
        "• <code>/check 0123456789 (Access Bank)</code> (Account)\n"
        "• <code>/check @sendmoorng</code> (Store Handle)\n"
        "• <code>/check RC123456</code> (CAC Registration)\n"
        "• <code>/check VNG-2026-99E1E30C</code> (Certificate ID)\n"
        "• <code>/check NIN 12345678901</code> (National ID)"
    )
    send_telegram_message(chat_id, text)


def _handle_inline_query(inline_query: Dict[str, Any], site_url: str) -> None:
    query_id = inline_query.get("id")
    query_text = (inline_query.get("query") or "").strip()
    if not query_id or not query_text:
        return

    result = perform_unified_check(query_text)
    reply_html, keyboard = format_check_result_html(result)

    title_map = {
        "merchant": "Verified Merchant Profile",
        "certificate": "Workforce Trust Certificate",
        "bank_account": "Bank Account Safety Check",
        "cac": "Corporate / CAC Verification",
        "phone": "Phone Number Safety Check",
        "nin": "National Identity Check",
        "unknown": "VerifyNG Trust Check",
    }
    title = title_map.get(result.get("entity_type", "unknown"), "VerifyNG Trust Check")

    article = {
        "type": "article",
        "id": f"vng_{hash(query_text)}",
        "title": f"🛡️ {title}: {query_text[:20]}",
        "description": "Tap to send VerifyNG verified anti-scam intelligence into this chat",
        "input_message_content": {
            "message_text": reply_html,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
    }
    if keyboard:
        article["reply_markup"] = keyboard

    answer_inline_query(query_id, [article])
