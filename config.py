# Fichier: config.py
import os

# =============================================================================
# 1. CONSTANTES FICHIERS & CHEMINS (Centralisation)
# =============================================================================
DATA_DIR = "data"

PATHS = {
    # Référentiels Géographiques
    "COMMUNES": os.path.join(DATA_DIR, "Communes_France_Metro.xlsx"),
    "CENTRES_DEPARTEMENTS": os.path.join(DATA_DIR, "Centres_departements.xlsx"),

    # Données Socio-Démographiques
    "IRIS_SOCIO": os.path.join(DATA_DIR, "iris_socio_data_final.parquet"),

    # Données Business & Trafic
    "COEFF_TRAFIC": os.path.join(DATA_DIR, "coefficient_temps_trajet.xlsx"),
    "DVF": os.path.join(DATA_DIR, "Valeurs_foncieres_geoloc_2020_2025.parquet"),

    # Données Risques & Climat
    "ZONES_INONDABLES": os.path.join(DATA_DIR, "zones_inondables_v2.parquet"),
    "RGA_SECHERESSE": os.path.join(DATA_DIR, "rga_secheresse_v2.parquet"),
    "CLIMAT_2050": os.path.join(DATA_DIR, "climat_2050_optimized.parquet")
}

# =============================================================================
# 2. CONFIGURATION POINTS D'INTÉRÊT (POI)
# =============================================================================
POI_CONFIG = {
    "Gares": {
        "tags": {"railway": "station"},
        "singular": "Gare",
        "icon": {'icon': 'train', 'color': 'darkblue', 'prefix': 'fa'}
    },
    "Écoles": {
        "tags": {"amenity": "school"},
        "singular": "École",
        "icon": {'icon': 'graduation-cap', 'color': 'green', 'prefix': 'fa'}
    },
    "Universités": {
        "tags": {"amenity": "university"},
        "singular": "Université",
        "icon": {'icon': 'university', 'color': 'darkgreen', 'prefix': 'fa'}
    },
    "Hôpitaux": {
        "tags": {"amenity": "hospital"},
        "singular": "Hôpital",
        "icon": {'icon': 'hospital', 'color': 'red', 'prefix': 'fa'}
    },
    "Pharmacies": {
        "tags": {"amenity": "pharmacy"},
        "singular": "Pharmacie",
        "icon": {'icon': 'plus-square', 'color': 'pink', 'prefix': 'fa'}
    },
    "Mairies": {
        "tags": {"amenity": "townhall"},
        "singular": "Mairie",
        "icon": {'icon': 'landmark', 'color': 'orange', 'prefix': 'fa'}
    },
    "Supermarchés": {
        "tags": {"shop": "supermarket"},
        "singular": "Supermarché",
        "icon": {'icon': 'shopping-cart', 'color': 'purple', 'prefix': 'fa'}
    }
}

# =================================================================
# 3. CONFIGURATION LOCOMOTIVES (SCORING FLUX)
# =================================================================
LOCOMOTIVES_CONFIG = {
    "Gares & Transports": {
        "tags": {"railway": "station", "aeroway": "terminal"},
        "poids": 10,
        "description": "Gares, Métros"
    },
    "Écoles / Lycées": {
        "tags": {"amenity": ["college", "university", "school"]},
        "poids": 8,
        "description": "Enseignement"
    },
    "Supermarchés / Mall": {
        "tags": {"shop": ["supermarket", "mall", "department_store"]},
        "poids": 7,
        "description": "GMS, Mall"
    },
    "Santé (Hôpital)": {
        "tags": {"amenity": "hospital"},
        "poids": 6,
        "description": "Hôpitaux"
    },
    "Fast Food": {
        "tags": {"amenity": "fast_food", "cuisine": "burger"},
        "poids": 4,
        "description": "Resto Rapide"
    },
    "Services Publics": {
        "tags": {"amenity": ["townhall", "post_office"]},
        "poids": 3,
        "description": "Mairie, Poste"
    }
}