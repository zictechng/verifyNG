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

# ─────────────────────────────────────────────────────────────────────────────
# BUSINESS & CORPORATE REGISTRATION SPECIFICATIONS (RCCM CÔTE D'IVOIRE)
# ─────────────────────────────────────────────────────────────────────────────
BUSINESS_REGISTRATION_AUTHORITY = "Tribunal de Commerce d'Abidjan / CEPICI (RCCM CI)"

BUSINESS_REGISTRATION_TYPES = {
    "rccm": {
        "code": "rccm",
        "name": "Registre du Commerce et du Crédit Mobilier (RCCM Côte d'Ivoire)",
        "authority": "Greffe du Tribunal de Commerce d'Abidjan / CEPICI",
        "accepted_entities": [
            ("sarl", "Société à Responsabilité Limitée (SARL)"),
            ("sa", "Société Anonyme (SA)"),
            ("sas", "Société par Actions Simplifiée (SAS)"),
            ("ei", "Entreprise Individuelle (EI)"),
        ],
        "placeholder": "e.g. CI-ABJ-2020-B-12345 or CI-ABJ-03-2021-B12-05432",
        "help_text": "Enter your official Ivorian RCCM number (e.g. CI-ABJ-YYYY-X-NNNNN).",
        "regex": r"^CI-[A-Za-z]{3}(-\d{2,4})?-\d{2,4}-[A-Za-z0-9]{1,4}-\d{3,8}$",
        "clean_function": lambda n: n.strip().upper(),
        "error_message": "A valid Ivorian RCCM registration number follows CI-XXX-YYYY-X-NNNNN format (e.g. CI-ABJ-2020-B-12345).",
        "required_documents": [
            "Extrait du Registre du Commerce et du Crédit Mobilier (RCCM)",
            "Déclaration de Régularité et de Conformité (DRC) / Déclaration CEPICI",
        ],
    }
}

TAX_IDENTIFICATION_SPEC = {
    "name": "Numéro de Compte Contribuable (NCC)",
    "authority": "Direction Générale des Impôts (DGI Côte d'Ivoire)",
    "placeholder": "e.g. 1234567A",
    "regex": r"^\d{7}[A-Za-z]$",
    "clean_function": lambda n: re.sub(r"[\s\-]", "", n).upper(),
    "error_message": "A valid Ivorian Numéro de Compte Contribuable (NCC) consists of 7 digits followed by 1 letter (e.g. 1234567A).",
}

