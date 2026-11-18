# users/country_documents/ghana.py
"""
Document specifications and validation rules for Ghana (GH).
Authority: National Identification Authority (NIA), GIS, DVLA.
Reference: register.nia.gov.gh
Format: GHA-XXXXXXXXX-X (GHA followed by 9 or 10 digits and 1 check digit).
"""
import re

COUNTRY_CODE = "GH"
COUNTRY_NAME = "Ghana"

ACCEPTED_DOCUMENTS = {
    "ghana_card": {
        "code": "ghana_card",
        "name": "Ghana Card (National ID)",
        "authority": "National Identification Authority (NIA)",
        "placeholder": "e.g. GHA-123456789-0",
        "help_text": "Enter your Ghana Card PIN in the format GHA-XXXXXXXXX-X.",
        "regex": r"^GHA-\d{9,10}-\d$",
        "clean_function": lambda n: n.strip().upper(),
        "error_message": "A Ghana Card PIN must be in the format GHA-XXXXXXXXX-X (e.g. GHA-712345678-1).",
    },
    "passport": {
        "code": "passport",
        "name": "Ghanaian International Passport",
        "authority": "Ghana Immigration Service (GIS)",
        "placeholder": "e.g. G1234567",
        "help_text": "Enter your Ghanaian passport booklet number (1 letter followed by 7 or 8 digits).",
        "regex": r"^[A-Za-z]\d{7,8}$",
        "clean_function": lambda n: re.sub(r"[\s\-]", "", n).upper(),
        "error_message": "A Ghanaian passport number must consist of 1 letter followed by 7 to 8 digits.",
    },
    "drivers_license": {
        "code": "drivers_license",
        "name": "Driver's License (DVLA)",
        "authority": "Driver and Vehicle Licensing Authority (DVLA)",
        "placeholder": "e.g. DL12345678",
        "help_text": "Enter your official DVLA driver's license number.",
        "regex": r"^[A-Za-z0-9]{8,12}$",
        "clean_function": lambda n: re.sub(r"[\s\-]", "", n).upper(),
        "error_message": "A Ghanaian Driver's License number must contain 8 to 12 alphanumeric characters.",
    },
}
