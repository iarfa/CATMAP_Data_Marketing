# Dictionnaire de configuration centralisé pour les Points d'Intérêt (POI)
POI_CONFIG = {
    "Gares":         {"tags": {"railway": "station"},    "singular": "Gare",         "icon": {'icon': 'train', 'color': 'darkblue', 'prefix': 'fa'}},
    "Écoles":        {"tags": {"amenity": "school"},     "singular": "École",        "icon": {'icon': 'graduation-cap', 'color': 'green', 'prefix': 'fa'}},
    "Universités":   {"tags": {"amenity": "university"}, "singular": "Université",   "icon": {'icon': 'university', 'color': 'darkgreen', 'prefix': 'fa'}},
    "Hôpitaux":      {"tags": {"amenity": "hospital"},   "singular": "Hôpital",      "icon": {'icon': 'hospital', 'color': 'red', 'prefix': 'fa'}},
    "Pharmacies":    {"tags": {"amenity": "pharmacy"},   "singular": "Pharmacie",    "icon": {'icon': 'plus-square', 'color': 'pink', 'prefix': 'fa'}},
    "Mairies":       {"tags": {"amenity": "townhall"},   "singular": "Mairie",       "icon": {'icon': 'landmark', 'color': 'orange', 'prefix': 'fa'}},
    "Supermarchés":  {"tags": {"shop": "supermarket"},  "singular": "Supermarché",  "icon": {'icon': 'shopping-cart', 'color': 'purple', 'prefix': 'fa'}}
}