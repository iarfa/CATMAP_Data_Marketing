# Fichier: utils/formatters.py

def clean_siret_string(val):
    """Nettoie une entrée utilisateur pour obtenir un SIRET propre."""
    if not val: return ""
    return str(val).strip().replace(" ", "").replace(".", "")

def format_euro(valeur):
    """Formate un nombre en string monétaire lisible."""
    try:
        return f"{float(valeur):,.0f} €".replace(",", " ")
    except (ValueError, TypeError):
        return "N/A"

def format_pourcentage(valeur):
    """Formate un float en pourcentage."""
    try:
        return f"{float(valeur):.1f} %"
    except (ValueError, TypeError):
        return "N/A"