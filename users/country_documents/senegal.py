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
