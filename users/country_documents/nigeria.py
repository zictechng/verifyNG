# users/country_documents/nigeria.py
"""
Document specifications and validation rules for Nigeria (NG).
Authority: NIMC, FRSC, INEC, NIS.
Note: BVN is strictly prohibited as an identity document proof.
"""
import re

COUNTRY_CODE = "NG"
COUNTRY_NAME = "Nigeria"

ACCEPTED_DOCUMENTS = {
    "nin": {
        "code": "nin",
        "name": "National Identity Number (NIN)",
        "authority": "National Identity Management Commission (NIMC)",
        "placeholder": "Enter 11-digit NIN",
        "help_text": "Enter your 11-digit National Identity Number as printed on your NIN slip or card.",
        "regex": r"^\d{11}$",
        "clean_function": lambda n: re.sub(r"\D", "", n),
        "error_message": "A Nigerian National Identity Number (NIN) must contain exactly 11 digits.",
    },
    "voters_card": {
        "code": "voters_card",
        "name": "Permanent Voter's Card (PVC)",
        "authority": "Independent National Electoral Commission (INEC)",
        "placeholder": "Enter 19-character VIN",
        "help_text": "Enter your 19-character Voter Identification Number (VIN) printed on your card.",
        "regex": r"^[A-Za-z0-9]{19}$",
        "clean_function": lambda n: re.sub(r"[\s\-]", "", n).upper(),
        "error_message": "A Nigerian Voter Identification Number (VIN) must contain 19 alphanumeric characters.",
    },
    "passport": {
        "code": "passport",
        "name": "International Passport",
        "authority": "Nigeria Immigration Service (NIS)",
        "placeholder": "e.g. A12345678",
        "help_text": "Enter your Nigerian Standard Passport booklet number (1 letter followed by 8 digits).",
        "regex": r"^[A-Za-z]\d{8}$",
        "clean_function": lambda n: re.sub(r"[\s\-]", "", n).upper(),
        "error_message": "A Nigerian passport number must consist of 1 letter followed by 8 digits (e.g. A12345678).",
    },
    "drivers_license": {
        "code": "drivers_license",
        "name": "Driver's License (FRSC)",
        "authority": "Federal Road Safety Corps (FRSC)",
        "placeholder": "e.g. ABC123456789",
        "help_text": "Enter your 11 or 12 character Driver's License number.",
        "regex": r"^[A-Za-z]{3}[A-Za-z0-9]{8,9}$",
        "clean_function": lambda n: re.sub(r"[\s\-]", "", n).upper(),
        "error_message": "A valid Nigerian Driver's License number must contain 11 to 12 alphanumeric characters.",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# BUSINESS & CORPORATE REGISTRATION SPECIFICATIONS (CAC)
# ─────────────────────────────────────────────────────────────────────────────
BUSINESS_REGISTRATION_AUTHORITY = "Corporate Affairs Commission (CAC)"

BUSINESS_REGISTRATION_TYPES = {
    "cac": {
        "code": "cac",
        "name": "Corporate Affairs Commission (CAC)",
        "authority": "Corporate Affairs Commission (CAC)",
        "accepted_entities": [
            ("rc", "Private/Public Limited Company (RC)"),
            ("bn", "Business Name / Enterprise (BN)"),
            ("it", "Incorporated Trustees / NGO (IT)"),
        ],
        "placeholder": "e.g. RC-1234567 or BN-123456",
        "help_text": "Enter your official CAC registration number including optional RC, BN, or IT prefix.",
        "regex": r"^(RC|BN|IT|LLP)?[- ]?\d{5,8}$",
        "clean_function": lambda n: re.sub(r"\s+", "", n).upper(),
        "error_message": "A valid Nigerian CAC registration number must be 5 to 8 digits, optionally prefixed with RC, BN, or IT.",
        "required_documents": [
            "CAC Certificate of Incorporation",
            "CAC Status Report / Form CAC 1.1",
        ],
    }
}

TAX_IDENTIFICATION_SPEC = {
    "name": "Taxpayer Identification Number (FIRS/JTB TIN)",
    "authority": "Federal Inland Revenue Service (FIRS) / Joint Tax Board (JTB)",
    "placeholder": "e.g. 12345678-0001 or 10-digit TIN",
    "regex": r"^\d{8,12}(-\d{3,4})?$",
    "clean_function": lambda n: re.sub(r"[\s]", "", n),
    "error_message": "A valid Nigerian TIN consists of 8 to 12 digits, with an optional branch suffix (e.g. 12345678-0001).",
}

