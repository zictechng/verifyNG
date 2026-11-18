# users/country_documents/senegal.py
"""
Document specifications and validation rules for Senegal (SN).
Authority: Direction de l'Automatisation des Fichiers (DAF).
Carte Nationale d'Identité Biométrique CEDEAO.
"""
import re

COUNTRY_CODE = "SN"
COUNTRY_NAME = "Senegal"

ACCEPTED_DOCUMENTS = {
    "cni": {
        "code": "cni",
        "name": "Carte Nationale d'Identité Biométrique (CEDEAO / DAF)",
        "authority": "Direction de l'Automatisation des Fichiers (DAF)",
        "placeholder": "Enter National ID number",
        "help_text": "Enter your Senegalese National Identity Card number (NIN).",
        "regex": r"^\d{13,17}$",
        "clean_function": lambda n: re.sub(r"\D", "", n),
        "error_message": "A Senegalese CNI number must contain between 13 and 17 digits.",
    },
    "passport": {
        "code": "passport",
        "name": "Passeport Sénégalais",
        "authority": "Direction de la Police des Étrangers et des Titres de Voyage",
        "placeholder": "e.g. A1234567",
        "help_text": "Enter your Senegalese passport number.",
        "regex": r"^[A-Za-z0-9]{7,9}$",
        "clean_function": lambda n: re.sub(r"[\s\-]", "", n).upper(),
        "error_message": "A Senegalese passport number must contain 7 to 9 alphanumeric characters.",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# BUSINESS & CORPORATE REGISTRATION SPECIFICATIONS (RCCM SÉNÉGAL)
# ─────────────────────────────────────────────────────────────────────────────
BUSINESS_REGISTRATION_AUTHORITY = "Tribunal de Commerce de Dakar / APIX (RCCM Sénégal)"

BUSINESS_REGISTRATION_TYPES = {
    "rccm": {
        "code": "rccm",
        "name": "Registre du Commerce et du Crédit Mobilier (RCCM Sénégal)",
        "authority": "Greffe du Tribunal de Commerce Hors Classe de Dakar / APIX",
        "accepted_entities": [
            ("suarl", "Société Unipersonnelle à Responsabilité Limitée (SUARL)"),
            ("sarl", "Société à Responsabilité Limitée (SARL)"),
            ("sa", "Société Anonyme (SA)"),
            ("ei", "Entreprise Individuelle (EI)"),
        ],
        "placeholder": "e.g. SN.DKR.2021.B.12345 or SN-THS-2020-A-5432",
        "help_text": "Enter your official Senegalese RCCM number (e.g. SN.DKR.YYYY.X.NNNNN).",
        "regex": r"^SN[\.-][A-Za-z]{3}[\.-]\d{2,4}[\.-][A-Za-z0-9]{1,3}[\.-]\d{3,8}$",
        "clean_function": lambda n: n.strip().upper(),
        "error_message": "A valid Senegalese RCCM registration number follows SN.XXX.YYYY.X.NNNNN format (e.g. SN.DKR.2021.B.12345).",
        "required_documents": [
            "Déclaration d'immatriculation au RCCM / Extrait RCCM",
            "Avis d'Immatriculation NINEA",
        ],
    }
}

TAX_IDENTIFICATION_SPEC = {
    "name": "Numéro d'Identification Nationale des Entreprises et des Associations (NINEA)",
    "authority": "Direction Générale des Impôts et des Domaines (DGID Sénégal) / ANSD",
    "placeholder": "e.g. 001234567 or 001234567 2V3",
    "regex": r"^\d{9}([A-Za-z0-9\s]{3,4})?$",
    "clean_function": lambda n: re.sub(r"[\s\-]", "", n).upper(),
    "error_message": "A valid Senegalese NINEA must be 9 digits, optionally followed by a 3-character branch code (e.g. 0012345672V3).",
}

