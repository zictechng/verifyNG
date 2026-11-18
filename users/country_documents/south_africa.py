# users/country_documents/south_africa.py
"""
Document specifications and validation rules for South Africa (ZA).
Authority: Department of Home Affairs (DHA).
National Identity Document / Smart ID Card: 13 digits (YYMMDDSSSSCAZ).
Reference: Identification Act 68 of 1997 / DHA Regulations.
"""
import re

COUNTRY_CODE = "ZA"
COUNTRY_NAME = "South Africa"


def _luhn_checksum(id_str: str) -> bool:
    """Validates Luhn 10 checksum on South African 13-digit ID."""
    if len(id_str) != 13 or not id_str.isdigit():
        return False
    digits = [int(c) for c in id_str]
    total = 0
    for i in range(12, -1, -1):
        n = digits[i]
        if (12 - i) % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


ACCEPTED_DOCUMENTS = {
    "national_id": {
        "code": "national_id",
        "name": "South African Smart ID Card / Green Book",
        "authority": "Department of Home Affairs (DHA)",
        "placeholder": "Enter 13-digit ID number",
        "help_text": "Enter your 13-digit South African National Identity Number (YYMMDDSSSSCAZ).",
        "regex": r"^\d{13}$",
        "clean_function": lambda n: re.sub(r"\D", "", n),
        "validator": _luhn_checksum,
        "error_message": "A South African ID number must contain exactly 13 digits with a valid checksum.",
    },
    "passport": {
        "code": "passport",
        "name": "South African International Passport",
        "authority": "Department of Home Affairs (DHA)",
        "placeholder": "e.g. A01234567 or D01234567",
        "help_text": "Enter your South African passport number (1 letter followed by 8 digits).",
        "regex": r"^[A-Za-z]\d{8}$",
        "clean_function": lambda n: re.sub(r"[\s\-]", "", n).upper(),
        "error_message": "A South African passport number must consist of 1 letter followed by 8 digits.",
    },
}
