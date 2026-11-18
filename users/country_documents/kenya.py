# users/country_documents/kenya.py
"""
Document specifications and validation rules for Kenya (KE).
Authority: National Registration Bureau (NRB), Department of Immigration Services.
National Identity Card (Huduma/ID) is issued to citizens 18+ (typically 7 to 9 digits).
"""
import re

COUNTRY_CODE = "KE"
COUNTRY_NAME = "Kenya"

ACCEPTED_DOCUMENTS = {
    "national_id": {
        "code": "national_id",
        "name": "Kenyan National Identity Card",
        "authority": "National Registration Bureau (NRB)",
        "placeholder": "Enter 7 to 9 digit ID number",
        "help_text": "Enter your official Kenyan National ID number (7 to 9 digits).",
        "regex": r"^\d{7,9}$",
        "clean_function": lambda n: re.sub(r"\D", "", n),
        "error_message": "A Kenyan National ID number must contain between 7 and 9 digits.",
    },
    "passport": {
        "code": "passport",
        "name": "Kenyan International Passport",
        "authority": "Department of Immigration Services",
        "placeholder": "e.g. AK1234567 or A1234567",
        "help_text": "Enter your Kenyan East African e-Passport number (1 or 2 letters followed by 7 digits).",
        "regex": r"^[A-Za-z]{1,2}\d{7}$",
        "clean_function": lambda n: re.sub(r"[\s\-]", "", n).upper(),
        "error_message": "A Kenyan passport number must consist of 1 or 2 letters followed by 7 digits (e.g. AK1234567).",
    },
    "alien_id": {
        "code": "alien_id",
        "name": "Foreign Alien Identity Card",
        "authority": "Department of Immigration Services",
        "placeholder": "Enter Alien Card number",
        "help_text": "Enter your Kenya Alien Card registration number.",
        "regex": r"^[A-Za-z0-9]{6,10}$",
        "clean_function": lambda n: re.sub(r"[\s\-]", "", n).upper(),
        "error_message": "A Kenyan Alien Card number must contain 6 to 10 alphanumeric characters.",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# BUSINESS & CORPORATE REGISTRATION SPECIFICATIONS (BRS)
# ─────────────────────────────────────────────────────────────────────────────
BUSINESS_REGISTRATION_AUTHORITY = "Business Registration Service (BRS)"

BUSINESS_REGISTRATION_TYPES = {
    "brs": {
        "code": "brs",
        "name": "Business Registration Service (BRS)",
        "authority": "Business Registration Service (BRS) / eCitizen",
        "accepted_entities": [
            ("cpr", "Private Limited Company (CPR / PVT)"),
            ("bn", "Business Name / Sole Proprietor (BN)"),
            ("llp", "Limited Liability Partnership (LLP)"),
        ],
        "placeholder": "e.g. CPR/2021/12345 or PVT-XYZ123 or BN/2020/54321",
        "help_text": "Enter your official BRS registration number as registered on eCitizen.",
        "regex": r"^((CPR|BN|LLP)/\d{4}/\d{3,8}|PVT-[A-Za-z0-9]{5,12}|[A-Za-z0-9]{6,15})$",
        "clean_function": lambda n: re.sub(r"[\s]", "", n).upper(),
        "error_message": "A valid Kenyan BRS registration number follows CPR/YYYY/NNNNN, BN/YYYY/NNNNN, or PVT-XXXXXX format.",
        "required_documents": [
            "CR12 Official Search / Status Report",
            "Certificate of Incorporation",
        ],
    }
}

TAX_IDENTIFICATION_SPEC = {
    "name": "Kenya Revenue Authority Personal/Company Identification Number (KRA PIN)",
    "authority": "Kenya Revenue Authority (KRA)",
    "placeholder": "e.g. P051234567Z",
    "regex": r"^[A-Za-z]\d{9}[A-Za-z]$",
    "clean_function": lambda n: re.sub(r"[\s\-]", "", n).upper(),
    "error_message": "A valid Kenyan KRA PIN consists of 11 characters starting with a letter, 9 digits, and ending with a letter (e.g. P051234567Z).",
}

