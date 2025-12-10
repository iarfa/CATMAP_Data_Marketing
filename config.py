# Fichier: config.py

# Configuration existante POI (pour l'affichage carte)
POI_CONFIG = {
    "Gares":         {"tags": {"railway": "station"},    "singular": "Gare",         "icon": {'icon': 'train', 'color': 'darkblue', 'prefix': 'fa'}},
    "Écoles":        {"tags": {"amenity": "school"},     "singular": "École",        "icon": {'icon': 'graduation-cap', 'color': 'green', 'prefix': 'fa'}},
    "Universités":   {"tags": {"amenity": "university"}, "singular": "Université",   "icon": {'icon': 'university', 'color': 'darkgreen', 'prefix': 'fa'}},
    "Hôpitaux":      {"tags": {"amenity": "hospital"},   "singular": "Hôpital",      "icon": {'icon': 'hospital', 'color': 'red', 'prefix': 'fa'}},
    "Pharmacies":    {"tags": {"amenity": "pharmacy"},   "singular": "Pharmacie",    "icon": {'icon': 'plus-square', 'color': 'pink', 'prefix': 'fa'}},
    "Mairies":       {"tags": {"amenity": "townhall"},   "singular": "Mairie",       "icon": {'icon': 'landmark', 'color': 'orange', 'prefix': 'fa'}},
    "Supermarchés":  {"tags": {"shop": "supermarket"},   "singular": "Supermarché",  "icon": {'icon': 'shopping-cart', 'color': 'purple', 'prefix': 'fa'}}
}

# NOUVEAU : Configuration pour le Scoring "Locomotives"
# Poids : Note sur 10 de l'impact trafic

# Fichier: config.py

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