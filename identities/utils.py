import hmac
import hashlib
import re
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

SUPPORTED_IDENTIFIER_TYPES = {'phone', 'nin', 'bvn', 'account', 'cac', 'email', 'plate_vin', 'property_ref', 'cert_no'}

PHONE_DELIMITERS_REGEX = re.compile(r'[\s().-]')
PHONE_ALLOWED_CHARS_REGEX = re.compile(r'^[0-9\s().+\-]+$')
CAC_DELIMITERS_REGEX = re.compile(r'[\s().\-_]')
CAC_SCHEMES_REGEX = re.compile(r'^(RC|BN|IT|LLP)[0-9]{4,12}$', re.IGNORECASE)


def get_identifier_pepper() -> str:
    """
    Retrieves global pepper from settings/environment.
    Raises ImproperlyConfigured if not configured or empty.
    """
    pepper = getattr(settings, 'IDENTIFIER_HASH_PEPPER', None)
    if not pepper or not str(pepper).strip():
        raise ImproperlyConfigured(
            "IDENTIFIER_HASH_PEPPER is not configured. An explicit, high-entropy secret is required."
        )
    return str(pepper).strip()


def normalize_identifier(identifier_type: str, raw_value: str) -> str:
    """
    Validates and normalizes identifier values according to Nigerian national formats.
    Preserves leading zeros and strips formatting.
    Never exposes raw identifier values in exceptions or logs.
    """
    if identifier_type not in SUPPORTED_IDENTIFIER_TYPES:
        raise ValueError(f"Unsupported identifier type '{identifier_type}'. Supported: {SUPPORTED_IDENTIFIER_TYPES}")

    if not raw_value or not str(raw_value).strip():
        raise ValueError("Identifier value cannot be empty.")

    cleaned = str(raw_value).strip()

    if identifier_type == 'phone':
        # Reject if unsupported characters exist (only digits, spaces, (), ., +, - allowed)
        if not PHONE_ALLOWED_CHARS_REGEX.match(cleaned):
            raise ValueError("Phone number contains invalid characters.")

        # Strip delimiters
        digits = PHONE_DELIMITERS_REGEX.sub('', cleaned)
        if digits.startswith('+'):
            digits = digits[1:]

        # Check only digits remain
        if not digits.isdigit():
            raise ValueError("Phone number must contain only numeric digits after delimiter removal.")

        # 080... (11 digits) -> 23480... (13 digits)
        if digits.startswith('0') and len(digits) == 11:
            return '234' + digits[1:]
        # 23480... (13 digits)
        elif digits.startswith('234') and len(digits) == 13:
            return digits
        else:
            raise ValueError("Phone number does not match standard Nigerian length or prefix format.")

    elif identifier_type == 'nin':
        digits = re.sub(r'\s', '', cleaned)
        if len(digits) == 11 and digits.isdigit():
            return digits
        raise ValueError("NIN must be exactly 11 digits.")

    elif identifier_type == 'bvn':
        digits = re.sub(r'\s', '', cleaned)
        if len(digits) == 11 and digits.isdigit():
            return digits
        raise ValueError("BVN must be exactly 11 digits.")

    elif identifier_type == 'account':
        digits = re.sub(r'\s', '', cleaned)
        if len(digits) == 10 and digits.isdigit():
            return digits
        raise ValueError("Bank account number must be exactly 10 digits.")

    elif identifier_type == 'cac':
        stripped = CAC_DELIMITERS_REGEX.sub('', cleaned).upper()
        # If numeric-only (e.g. '1234567'), normalize to standard Nigerian company prefix 'RC'
        if stripped.isdigit() and 4 <= len(stripped) <= 12:
            return f"RC{stripped}"
        # If prefixed (e.g. 'RC123456', 'BN987654')
        if CAC_SCHEMES_REGEX.match(stripped):
            return stripped
        raise ValueError("CAC registration number does not match recognized Nigerian registration formats (e.g., RC, BN, IT, LLP).")

    elif identifier_type == 'email':
        lowered = cleaned.lower()
        try:
            validate_email(lowered)
        except ValidationError:
            raise ValueError("Email address format is invalid.")
        return lowered

    elif identifier_type == 'plate_vin':
        stripped = re.sub(r'[\s\-_]', '', cleaned).upper()
        if 4 <= len(stripped) <= 20:
            return stripped
        raise ValueError("Vehicle Plate or VIN number must be between 4 and 20 alphanumeric characters.")

    elif identifier_type == 'property_ref':
        stripped = re.sub(r'[\s]', '', cleaned).upper()
        if 3 <= len(stripped) <= 40:
            return stripped
        raise ValueError("Property, Land Title, or C of O reference must be between 3 and 40 characters.")

    elif identifier_type == 'cert_no':
        stripped = re.sub(r'[\s]', '', cleaned).upper()
        if 3 <= len(stripped) <= 50:
            return stripped
        raise ValueError("Certificate or matriculation number must be between 3 and 50 characters.")

    raise ValueError(f"Unhandled identifier type '{identifier_type}'.")


def hash_identifier_value(identifier_type: str, raw_value: str) -> str:
    """
    Computes a deterministic, peppered HMAC-SHA256 digest.
    Includes domain/type separation and versioning in message prefix:
    Message: 'v1:<identifier_type>:<normalized_value>'
    """
    pepper = get_identifier_pepper()
    normalized = normalize_identifier(identifier_type, raw_value)

    message = f"v1:{identifier_type}:{normalized}".encode('utf-8')
    digest = hmac.new(
        key=pepper.encode('utf-8'),
        msg=message,
        digestmod=hashlib.sha256
    ).hexdigest()

    return digest

