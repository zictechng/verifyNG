# users/country_config.py
"""
Central Pan-African Country Configuration Registry for VerifyNG.

Single source of truth for:
- Supported African identity-issuing countries
- Country-specific accepted document types, labels, and authorities
- Plausible format regexes and checksum validators
- Clear separation between user country of residence and document-issuing country
- Strict exclusion of BVN as an identity document
- Strict rejection of unsupported country codes (never silently defaulting to Nigeria)
- Preserved backward compatibility for legacy accounts where issuing country is None
"""
import re
from typing import Optional, Tuple, Dict, Any, List

from .country_documents import (
    nigeria,
    ghana,
    kenya,
    benin,
    south_africa,
    cote_divoire,
    senegal,
)

DEFAULT_COUNTRY = "NG"


class StandardCountryDocConfig:
    """
    Standardized identity & business configuration for Pan-African and international countries.
    Aligned with Smile ID core Document Verification (DocV) specifications:
    - International Passport (ICAO Doc 9303 / MRZ compatible)
    - National Identity Card (Government citizen biometric card)
    - Driver's License (Government motor vehicle / licensing authority)
    """
    def __init__(self, code: str, name: str, authority: str = "National Civil Identity Authority"):
        self.COUNTRY_CODE = code
        self.COUNTRY_NAME = name
        self.ACCEPTED_DOCUMENTS = {
            "passport": {
                "code": "passport",
                "name": "International Passport",
                "authority": f"{name} Immigration & Passport Authority",
                "placeholder": "e.g. A12345678",
                "help_text": "Enter your official international passport number as printed on your booklet.",
                "regex": r"^[A-Za-z0-9]{5,20}$",
                "clean_function": lambda n: re.sub(r"[\s\-]", "", str(n or "")).upper(),
                "error_message": f"A valid passport number must contain 5 to 20 alphanumeric characters.",
            },
            "national_id": {
                "code": "national_id",
                "name": "National Identity Card",
                "authority": authority,
                "placeholder": "Enter National ID Number",
                "help_text": f"Enter your official {name} National ID / Citizen card number.",
                "regex": r"^[A-Za-z0-9\-\/\s]{4,30}$",
                "clean_function": lambda n: re.sub(r"[\s\-]", "", str(n or "")).upper(),
                "error_message": f"Please enter a valid National Identity Card number (4 to 30 characters).",
            },
            "drivers_license": {
                "code": "drivers_license",
                "name": "Driver's License",
                "authority": f"{name} Driver & Vehicle Licensing Authority",
                "placeholder": "Enter Driver's License Number",
                "help_text": f"Enter your official {name} Driver's License number.",
                "regex": r"^[A-Za-z0-9\-\/\s]{4,25}$",
                "clean_function": lambda n: re.sub(r"[\s\-]", "", str(n or "")).upper(),
                "error_message": f"Please enter a valid Driver's License number (4 to 25 characters).",
            },
        }
        self.BUSINESS_REGISTRATION_AUTHORITY = f"{name} Commercial / Company Registry"
        self.BUSINESS_REGISTRATION_TYPES = {
            "commercial_reg": {
                "code": "commercial_reg",
                "name": "Business / Company Registration Number",
                "authority": f"{name} Commercial / Company Registry",
                "placeholder": "Enter official company registration number",
                "help_text": "Enter your official business incorporation or commercial register number.",
                "regex": r"^[A-Za-z0-9\-\/\s]{3,30}$",
                "clean_function": lambda n: re.sub(r"[\s\-]", "", str(n or "")).upper(),
                "error_message": "Please enter a valid business registration number.",
                "accepted_entities": [
                    ("ltd", "Limited Liability Company / Corp"),
                    ("sole", "Sole Proprietorship / Enterprise"),
                    ("partnership", "Partnership / Joint Venture"),
                ],
            }
        }


# Comprehensive Pan-African & Key Global Country List
EXPANDED_COUNTRIES = [
    # Top West Africa
    ("NG", "Nigeria"),
    ("GH", "Ghana"),
    ("BJ", "Benin"),
    ("CI", "Côte d'Ivoire"),
    ("SN", "Senegal"),
    ("BF", "Burkina Faso"),
    ("CV", "Cabo Verde"),
    ("GM", "Gambia"),
    ("GN", "Guinea"),
    ("GW", "Guinea-Bissau"),
    ("LR", "Liberia"),
    ("ML", "Mali"),
    ("MR", "Mauritania"),
    ("NE", "Niger"),
    ("SL", "Sierra Leone"),
    ("TG", "Togo"),
    # East Africa
    ("KE", "Kenya"),
    ("RW", "Rwanda"),
    ("UG", "Uganda"),
    ("TZ", "Tanzania"),
    ("ET", "Ethiopia"),
    ("BI", "Burundi"),
    ("DJ", "Djibouti"),
    ("ER", "Eritrea"),
    ("SO", "Somalia"),
    ("SS", "South Sudan"),
    ("SD", "Sudan"),
    ("SC", "Seychelles"),
    ("MU", "Mauritius"),
    ("KM", "Comoros"),
    ("MG", "Madagascar"),
    # Central Africa
    ("CM", "Cameroon"),
    ("CF", "Central African Republic"),
    ("TD", "Chad"),
    ("CG", "Congo (Brazzaville)"),
    ("CD", "Congo (DRC)"),
    ("GQ", "Equatorial Guinea"),
    ("GA", "Gabon"),
    ("ST", "São Tomé and Príncipe"),
    # Southern Africa
    ("ZA", "South Africa"),
    ("AO", "Angola"),
    ("BW", "Botswana"),
    ("SZ", "Eswatini"),
    ("LS", "Lesotho"),
    ("MW", "Malawi"),
    ("MZ", "Mozambique"),
    ("NA", "Namibia"),
    ("ZM", "Zambia"),
    ("ZW", "Zimbabwe"),
    # North Africa
    ("DZ", "Algeria"),
    ("EG", "Egypt"),
    ("LY", "Libya"),
    ("MA", "Morocco"),
    ("TN", "Tunisia"),
    # Global Diaspora & International
    ("GB", "United Kingdom"),
    ("US", "United States"),
    ("CA", "Canada"),
    ("AE", "United Arab Emirates"),
    ("FR", "France"),
    ("DE", "Germany"),
    ("CN", "China"),
    ("IN", "India"),
    ("XX", "Other Country (International)"),
]

# Central registry of supported document-issuing countries
_REGISTRY: Dict[str, Any] = {
    "NG": nigeria,
    "GH": ghana,
    "KE": kenya,
    "BJ": benin,
    "ZA": south_africa,
    "CI": cote_divoire,
    "SN": senegal,
}

# Populate standard configurations for all other supported countries
for code, name in EXPANDED_COUNTRIES:
    if code not in _REGISTRY:
        _REGISTRY[code] = StandardCountryDocConfig(code, name)


def is_country_supported(country_code: Optional[str]) -> bool:
    """Returns True if the given country code is supported in the registry."""
    if not country_code:
        return False
    return country_code.strip().upper() in _REGISTRY


def get_supported_countries() -> List[Tuple[str, str]]:
    """
    Returns list of supported (code, name) tuples for UI dropdowns.
    Nigeria is prioritized first, followed alphabetically by other nations, with 'Other Country' last.
    """
    priority = ["NG"]
    items = []
    other_item = None
    for code, mod in _REGISTRY.items():
        if code in priority:
            continue
        if code == "XX":
            other_item = (code, mod.COUNTRY_NAME)
        else:
            items.append((code, mod.COUNTRY_NAME))
    items.sort(key=lambda x: x[1])
    result = [("NG", _REGISTRY["NG"].COUNTRY_NAME)] + items
    if other_item:
        result.append(other_item)
    return result


def get_country_config(country_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Returns configuration dict for the given country code.

    Rules:
    - country_code is None or empty: Returns Nigeria config (backward compatibility for legacy accounts).
    - country_code is valid ISO code in registry: Returns that country's specific configuration.
    - country_code is an unknown/unsupported code: Returns None (NEVER silently becomes Nigeria).
    """
    if country_code is None or country_code == "":
        mod = _REGISTRY[DEFAULT_COUNTRY]
        return {
            "code": mod.COUNTRY_CODE,
            "name": mod.COUNTRY_NAME,
            "accepted_documents": mod.ACCEPTED_DOCUMENTS,
        }

    normalized = str(country_code).strip().upper()
    if normalized in _REGISTRY:
        mod = _REGISTRY[normalized]
        return {
            "code": mod.COUNTRY_CODE,
            "name": mod.COUNTRY_NAME,
            "accepted_documents": mod.ACCEPTED_DOCUMENTS,
        }

    return None


def get_country_documents(country_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Returns accepted_documents map for a country, or None if unsupported."""
    cfg = get_country_config(country_code)
    return cfg["accepted_documents"] if cfg else None


def validate_document_number(
    issuing_country: Optional[str],
    doc_type: str,
    number: str
) -> Tuple[bool, str]:
    """
    Validates an identification document number against the rules of its issuing country.

    Returns:
        (is_valid: bool, error_message_or_cleaned_number: str)
        If is_valid is True, error_message_or_cleaned_number contains the sanitized document number.
        If is_valid is False, error_message_or_cleaned_number contains the explanatory error message.
    """
    doc_type_clean = str(doc_type or "").strip().lower()
    raw_number = str(number or "").strip()

    # BVN Strict Exclusion: financial identifier, never an accepted identity document
    if doc_type_clean == "bvn":
        return (
            False,
            "A Bank Verification Number (BVN) is a financial identifier and cannot be accepted as a photo identity document. "
            "Please provide a recognized government photo ID (NIN, Ghana Card, National ID, International Passport, or Driver's License)."
        )

    if not raw_number:
        return False, "Please enter your official identification number."

    # Country Resolution
    if issuing_country is None or issuing_country == "":
        config = get_country_config(DEFAULT_COUNTRY)
    else:
        config = get_country_config(issuing_country)
        if config is None:
            return False, f"Issuing country '{issuing_country}' is not currently supported for identity verification."

    # Document type resolution
    accepted_docs = config["accepted_documents"]
    if doc_type_clean not in accepted_docs:
        doc_names = ", ".join([d["name"] for d in accepted_docs.values()])
        return False, f"Document type '{doc_type}' is not accepted for {config['name']}. Accepted documents are: {doc_names}."

    doc_rule = accepted_docs[doc_type_clean]

    # Clean / Sanitize input
    cleaned_number = raw_number
    if "clean_function" in doc_rule and callable(doc_rule["clean_function"]):
        cleaned_number = doc_rule["clean_function"](raw_number)

    # Regex format check
    regex_pattern = doc_rule.get("regex")
    if regex_pattern and not re.match(regex_pattern, cleaned_number):
        return False, doc_rule.get("error_message", "Invalid identification number format.")

    # Custom algorithmic validator (e.g. South African Luhn checksum)
    custom_validator = doc_rule.get("validator")
    if custom_validator and callable(custom_validator):
        if not custom_validator(cleaned_number):
            return False, doc_rule.get("error_message", "Invalid identification number format.")

    return True, cleaned_number


# ─────────────────────────────────────────────────────────────────────────────
# PAN-AFRICAN CORPORATE & BUSINESS CONFIGURATION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def get_country_business_config(country_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Returns business registration configuration dict for the given country code.

    Rules:
    - country_code is None or empty: Returns Nigeria CAC config (backward compatibility for legacy accounts).
    - country_code is valid ISO code in registry: Returns that country's specific business configuration.
    - country_code is an unknown/unsupported code: Returns None (NEVER silently becomes Nigeria).
    """
    if country_code is None or country_code == "":
        mod = _REGISTRY[DEFAULT_COUNTRY]
        return {
            "code": mod.COUNTRY_CODE,
            "name": mod.COUNTRY_NAME,
            "registration_authority": getattr(mod, "BUSINESS_REGISTRATION_AUTHORITY", "Corporate Affairs Commission (CAC)"),
            "registration_types": getattr(mod, "BUSINESS_REGISTRATION_TYPES", {}),
            "tax_spec": getattr(mod, "TAX_IDENTIFICATION_SPEC", None),
        }

    normalized = str(country_code).strip().upper()
    if normalized in _REGISTRY:
        mod = _REGISTRY[normalized]
        return {
            "code": mod.COUNTRY_CODE,
            "name": mod.COUNTRY_NAME,
            "registration_authority": getattr(mod, "BUSINESS_REGISTRATION_AUTHORITY", "National Company Registry"),
            "registration_types": getattr(mod, "BUSINESS_REGISTRATION_TYPES", {}),
            "tax_spec": getattr(mod, "TAX_IDENTIFICATION_SPEC", None),
        }

    return None


def validate_business_registration(
    country_code: Optional[str],
    reg_type: str,
    reg_number: str,
    tin_number: Optional[str] = None
) -> Tuple[bool, str, Dict[str, str]]:
    """
    Validates business registration number and optional tax ID against country-specific rules.

    Safeguards:
    1. Plausibility Syntax Check Only: Does not constitute or guarantee registry confirmation.
    2. Legacy Nigeria fallback applies strictly when country_code is None or empty. Explicit unsupported codes reject cleanly.
    3. Handles country-specific registration types and tax identifiers.

    Returns:
        (is_valid: bool, error_message: str, cleaned_data: Dict[str, str])
    """
    cleaned_data = {
        "reg_type": str(reg_type or "").strip().lower(),
        "reg_number": str(reg_number or "").strip(),
        "tin_number": str(tin_number or "").strip(),
    }

    if not cleaned_data["reg_number"]:
        return False, "Please enter your official business registration number.", cleaned_data

    # Resolve Country Business Configuration
    config = get_country_business_config(country_code)
    if config is None:
        return False, f"Country of registration '{country_code}' is not currently supported for corporate verification.", cleaned_data

    reg_types = config["registration_types"]
    selected_type = cleaned_data["reg_type"]

    # If reg_type is omitted or invalid, pick default or first available type
    if not selected_type or selected_type not in reg_types:
        # If country has a single primary reg type (e.g. 'cac', 'orc', 'brs', 'rccm', 'cipc')
        if len(reg_types) == 1:
            selected_type = list(reg_types.keys())[0]
            cleaned_data["reg_type"] = selected_type
        elif "cac" in reg_types and (country_code is None or country_code.upper() == "NG"):
            selected_type = "cac"
            cleaned_data["reg_type"] = "cac"
        else:
            valid_types = ", ".join(reg_types.keys())
            return False, f"Please select a valid registration type for {config['name']} ({valid_types}).", cleaned_data

    type_spec = reg_types[selected_type]

    # Clean registration number
    clean_func = type_spec.get("clean_function")
    cleaned_reg_number = clean_func(cleaned_data["reg_number"]) if callable(clean_func) else cleaned_data["reg_number"]
    cleaned_data["reg_number"] = cleaned_reg_number

    # Check registration number regex
    regex_pattern = type_spec.get("regex")
    if regex_pattern and not re.match(regex_pattern, cleaned_reg_number):
        return False, type_spec.get("error_message", "Invalid registration number format."), cleaned_data

    # Validate TIN if provided
    raw_tin = cleaned_data["tin_number"]
    tax_spec = config.get("tax_spec")
    if raw_tin and tax_spec:
        tin_clean_func = tax_spec.get("clean_function")
        cleaned_tin = tin_clean_func(raw_tin) if callable(tin_clean_func) else raw_tin
        cleaned_data["tin_number"] = cleaned_tin

        tin_regex = tax_spec.get("regex")
        if tin_regex and not re.match(tin_regex, cleaned_tin):
            return False, tax_spec.get("error_message", "Invalid Tax Identification Number format."), cleaned_data

    return True, "", cleaned_data

