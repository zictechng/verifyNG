"""
payments/bank_services.py

Provides real-time Paystack Account Number Resolution (NIP / NUBAN lookup)
with multi-tier caching (Redis -> Permanent Database -> Paystack API)
and anti-abuse bot protection.
"""

import logging
import requests
from django.conf import settings
from django.core.cache import cache
from payments.models import NigerianBank, VerifiedBankAccount

logger = logging.getLogger(__name__)


def get_bank_code_by_name(bank_name: str) -> str | None:
    """Matches a bank name string to its NUBAN institution sort code using the database."""
    if not bank_name:
        return None
    cleaned = bank_name.strip()
    
    # 1. Exact or case-insensitive match from database
    bank = NigerianBank.objects.filter(is_active=True, name__iexact=cleaned).first()
    if bank:
        return bank.code
    
    # 2. Substring matching from database (e.g. "opay" matching "OPay Digital Services...")
    bank = NigerianBank.objects.filter(is_active=True, name__icontains=cleaned).first()
    if bank:
        return bank.code

    # 3. Known common aliases
    alias_map = {
        'opay': '999992',
        'palmpay': '999991',
        'kuda': '50211',
        'moniepoint': '50515',
        'gtb': '058',
        'gtbank': '058',
        'guaranty': '058',
        'zenith': '057',
        'access': '044',
        'first bank': '011',
        'firstbank': '011',
        'uba': '033',
        'united bank': '033',
    }
    cleaned_lower = cleaned.lower()
    for alias, code in alias_map.items():
        if alias in cleaned_lower:
            return code
            
    return None


def resolve_bank_account(account_number: str, bank_name: str) -> dict:
    """
    Resolves an account number against:
    Tier 1: Redis Memory Cache (Instant, ₦0)
    Tier 2: Permanent VerifiedBankAccount Database (Permanent across all users, ₦0)
    Tier 3: Paystack / NIP API (Only if never seen before on the platform, ₦10)
    """
    account_clean = str(account_number or '').strip()
    if not (account_clean.isdigit() and len(account_clean) == 10):
        return {
            'success': False,
            'account_name': None,
            'message': 'Account number must be exactly 10 numeric digits.'
        }

    bank_code = get_bank_code_by_name(bank_name)
    if not bank_code:
        return {
            'success': False,
            'account_name': None,
            'message': f"Unable to identify bank code for '{bank_name}'. Please select your bank from the list."
        }

    # Normalize canonical bank name
    bank_obj = NigerianBank.objects.filter(code=bank_code).first()
    canonical_bank_name = bank_obj.name if bank_obj else bank_name

    cache_key = f"vng_bank_resolve:{bank_code}:{account_clean}"

    # -------------------------------------------------------------
    # TIER 1: Check Redis In-Memory Cache (Instant)
    # -------------------------------------------------------------
    cached_name = cache.get(cache_key)
    if cached_name:
        logger.info("Resolved bank account from Redis: %s (%s) -> %s", account_clean, bank_code, cached_name)
        return {
            'success': True,
            'account_name': cached_name,
            'account_number': account_clean,
            'bank_code': bank_code,
            'bank_name': canonical_bank_name,
            'source': 'redis_cache'
        }

    # -------------------------------------------------------------
    # TIER 2: Check Permanent Database Vault (Never expires, ₦0)
    # -------------------------------------------------------------
    db_record = VerifiedBankAccount.objects.filter(account_number=account_clean, bank_code=bank_code).first()
    if db_record and db_record.account_name:
        logger.info("Resolved bank account from Permanent Database Vault: %s (%s) -> %s", account_clean, bank_code, db_record.account_name)
        # Re-populate Redis for faster subsequent lookups
        cache.set(cache_key, db_record.account_name, timeout=60 * 60 * 24 * 30)
        return {
            'success': True,
            'account_name': db_record.account_name,
            'account_number': account_clean,
            'bank_code': bank_code,
            'bank_name': canonical_bank_name,
            'source': 'permanent_db'
        }

    # -------------------------------------------------------------
    # TIER 3: Call Paystack NIP Switch (Only for brand-new accounts)
    # -------------------------------------------------------------
    secret_key = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
    if not secret_key:
        logger.warning("PAYSTACK_SECRET_KEY not configured. Skipping live account resolution.")
        return {
            'success': False,
            'account_name': None,
            'message': 'Account resolution service is currently unconfigured.'
        }

    url = f"https://api.paystack.co/bank/resolve?account_number={account_clean}&bank_code={bank_code}"
    headers = {
        'Authorization': f"Bearer {secret_key}",
        'Content-Type': 'application/json',
    }

    try:
        resp = requests.get(url, headers=headers, timeout=8)
        data = resp.json()

        if resp.status_code == 200 and data.get('status') is True:
            account_name = data.get('data', {}).get('account_name', '').strip()
            if account_name:
                # 1. Save permanently in database vault
                VerifiedBankAccount.objects.update_or_create(
                    account_number=account_clean,
                    bank_code=bank_code,
                    defaults={
                        'bank_name': canonical_bank_name,
                        'account_name': account_name,
                    }
                )
                # 2. Cache in Redis
                cache.set(cache_key, account_name, timeout=60 * 60 * 24 * 30)
                logger.info("Paystack resolved new account %s to '%s' (saved permanently to DB)", account_clean, account_name)
                return {
                    'success': True,
                    'account_name': account_name,
                    'account_number': account_clean,
                    'bank_code': bank_code,
                    'bank_name': canonical_bank_name,
                    'source': 'paystack_api'
                }

        error_msg = data.get('message', 'Could not resolve account name.')
        logger.warning("Paystack resolution rejected %s (%s): %s", account_clean, bank_code, error_msg)
        return {
            'success': False,
            'account_name': None,
            'message': error_msg
        }

    except Exception as exc:
        logger.error("Paystack bank resolution network error: %s", exc)
        return {
            'success': False,
            'account_name': None,
            'message': 'Network timeout communicating with banking switch.'
        }
