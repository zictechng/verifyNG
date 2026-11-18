# users/country_documents/benin.py
"""
Document specifications and validation rules for Benin (BJ).
Authority: Agence Nationale d'Identification des Personnes (ANIP).
CIP (Certificat d'Identification Personnelle): 10-digit NPI (Numéro Personnel d'Identification).
CNI Biométrique: Carte Nationale d'Identité Biométrique.
Reference: anip.bj
"""
import re

COUNTRY_CODE = "BJ"
COUNTRY_NAME = "Benin"

ACCEPTED_DOCUMENTS = {
    "cip": {
        "code": "cip",
        "name": "Certificat d'Identification Personnelle (CIP)",
        "authority": "Agence Nationale d'Identification des Personnes (ANIP)",
        "placeholder": "Enter 10-digit NPI",
        "help_text": "Enter the 10-digit Numéro Personnel d'Identification (NPI) on your CIP certificate.",
        "regex": r"^\d{10}$",
        "clean_function": lambda n: re.sub(r"\D", "", n),
        "error_message": "A Benin CIP requires a valid 10-digit Numéro Personnel d'Identification (NPI).",
    },
    "cni": {
        "code": "cni",
        "name": "Carte Nationale d'Identité Biométrique (CNI)",
        "authority": "ANIP / Direction de l'Émigration et de l'Immigration (DEI)",
        "placeholder": "Enter CNI number",
        "help_text": "Enter your Benin Biometric National Identity Card number.",
        "regex": r"^[A-Za-z0-9]{9,14}$",
        "clean_function": lambda n: re.sub(r"[\s\-]", "", n).upper(),
        "error_message": "A Benin CNI number must contain between 9 and 14 alphanumeric characters.",
    },
    "passport": {
        "code": "passport",
        "name": "Passeport Béninois",
        "authority": "Direction de l'Émigration et de l'Immigration (DEI)",
        "placeholder": "e.g. 12AB34567 or AB123456",
        "help_text": "Enter your official Republic of Benin passport booklet number.",
        "regex": r"^[A-Za-z0-9]{8,9}$",
        "clean_function": lambda n: re.sub(r"[\s\-]", "", n).upper(),
        "error_message": "A Benin passport number must contain 8 to 9 alphanumeric characters.",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# BUSINESS & CORPORATE REGISTRATION SPECIFICATIONS (RCCM BÉNIN)
# ─────────────────────────────────────────────────────────────────────────────
BUSINESS_REGISTRATION_AUTHORITY = "Tribunal de Commerce de Cotonou / GUFE (RCCM Bénin)"

BUSINESS_REGISTRATION_TYPES = {
    "rccm": {
        "code": "rccm",
        "name": "Registre du Commerce et du Crédit Mobilier (RCCM Bénin)",
        "authority": "Greffe du Tribunal de Commerce de Cotonou / GUFE",
        "accepted_entities": [
            ("sarl", "Société à Responsabilité Limitée (SARL)"),
            ("sas", "Société par Actions Simplifiée (SAS)"),
            ("ei", "Entreprise Individuelle (EI)"),
        ],
        "placeholder": "e.g. RB/COT/20 B 12345 or RB/PNO/19 A 5432",
        "help_text": "Enter your official Beninese RCCM number (e.g. RB/COT/YY X NNNNN).",
        "regex": r"^RB/[A-Za-z]{3}/\d{2,4}\s?[A-Za-z]?\s?\d{3,8}$",
        "clean_function": lambda n: n.strip().upper(),
        "error_message": "A valid Beninese RCCM registration number follows RB/XXX/YY [A/B] NNNNN format (e.g. RB/COT/20 B 12345).",
        "required_documents": [
            "Extrait du Registre du Commerce et du Crédit Mobilier (RCCM)",
            "Attestation d'Immatriculation GUFE / Certificat de Conformité",
        ],
    }
}

TAX_IDENTIFICATION_SPEC = {
    "name": "Identifiant Fiscal Unique (IFU)",
    "authority": "Direction Générale des Impôts (DGI Bénin)",
    "placeholder": "Enter 13-digit IFU",
    "regex": r"^\d{13}$",
    "clean_function": lambda n: re.sub(r"\D", "", n),
    "error_message": "A valid Beninese Identifiant Fiscal Unique (IFU) must consist of exactly 13 digits.",
}

