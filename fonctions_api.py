# Fichier: fonctions_api.py

import requests
import pandas as pd
import streamlit as st


# =============================================================================
# 1. API GÉO (ETALAB) - Récupération Code INSEE
# =============================================================================
@st.cache_data(ttl=3600)
def get_code_insee_lat_lon(lat, lon):
    """
    Interroge l'API Géo (api.gouv.fr) pour trouver la commune exacte.
    Indispensable pour interroger GASPAR ensuite.
    """
    if not lat or not lon: return None, None

    url = "https://geo.api.gouv.fr/communes"
    params = {
        "lat": lat,
        "lon": lon,
        "fields": "code,nom",
        "format": "json",
        "geometry": "centre"
    }

    try:
        r = requests.get(url, params=params, timeout=3)
        if r.status_code == 200 and len(r.json()) > 0:
            data = r.json()[0]
            return data.get('code'), data.get('nom')
    except Exception:
        return None, None
    return None, None


# =============================================================================
# 2. API GASPAR (GÉORISQUES) - Historique CatNat
# =============================================================================
@st.cache_data(ttl=3600)
def get_historique_catnat(code_insee):
    """
    Récupère les arrêtés CatNat via l'API Géorisques.
    Preuve juridique du risque.
    """
    if not code_insee: return pd.DataFrame()

    url = "https://georisques.gouv.fr/api/v1/gaspar/catnat"
    params = {"code_insee": code_insee, "page_size": 100}

    try:
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if "data" in data:
                records = []
                for item in data["data"]:
                    records.append({
                        "Péril": item.get("libelleRisqueJo", "Inconnu"),
                        "Début": item.get("dateDebutEvenement")[:10],  # YYYY-MM-DD
                        "Fin": item.get("dateFinEvenement")[:10],
                        "Arrêté": item.get("dateArrete")[:10]
                    })
                df = pd.DataFrame(records)
                if not df.empty:
                    df = df.sort_values("Début", ascending=False)
                return df
    except Exception:
        pass
    return pd.DataFrame()


def get_stats_sinistralite(df_catnat):
    """Calcule les KPIs sinistralité."""
    if df_catnat.empty: return 0, 0, "Aucun"

    nb_total = len(df_catnat)

    # Sinistres < 10 ans
    cutoff = (pd.Timestamp.now() - pd.DateOffset(years=10)).strftime('%Y-%m-%d')
    nb_recent = len(df_catnat[df_catnat['Début'] >= cutoff])

    # Péril dominant
    top_peril = df_catnat['Péril'].mode()[0] if not df_catnat.empty else "Divers"

    return nb_total, nb_recent, top_peril