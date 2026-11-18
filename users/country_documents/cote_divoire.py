# users/country_documents/cote_divoire.py
"""
Document specifications and validation rules for Côte d'Ivoire (CI).
Authority: Office National de l'État Civil et de l'Identification (ONECI).
CNI (Carte Nationale d'Identité): Numéro National d'Identification (NNI).
"""
import re

COUNTRY_CODE = "CI"
COUNTRY_NAME = "Côte d'Ivoire"

ACCEPTED_DOCUMENTS = {
    "cni": {
        "code": "cni",
        "name": "Carte Nationale d'Identité (CNI / ONECI)",
        "authority": "Office National de l'État Civil et de l'Identification (ONECI)",
        "placeholder": "Enter NNI number",
        "help_text": "Enter your Numéro National d'Identification (NNI) printed on your Ivorian CNI.",
        "regex": r"^[A-Za-z0-9]{10,12}$",
        "clean_function": lambda n: re.sub(r"[\s\-]", "", n).upper(),
        "error_message": "An Ivorian CNI number must contain 10 to 12 alphanumeric characters.",
    },
    "passport": {
        "code": "passport",
        "name": "Passeport Ivoirien",
        "authority": "Ministère de la Sécurité / Snedai",
        "placeholder": "e.g. 12AB34567",
        "help_text": "Enter your official Republic of Côte d'Ivoire passport number.",
        "regex": r"^[A-Za-z0-9]{8,9}$",
        "clean_function": lambda n: re.sub(r"[\s\-]", "", n).upper(),
        "error_message": "An Ivorian passport number must contain 8 to 9 alphanumeric characters.",
    },
}
