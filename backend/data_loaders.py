# Fichier: backend/data_loaders.py
import pandas as pd
import geopandas as gpd
import streamlit as st
from config import PATHS


# =============================================================================
# CHARGEURS DE DONNÉES (FILESYSTEM)
# =============================================================================

@st.cache_data(show_spinner=False)
def charger_communes() -> pd.DataFrame:
    """Charge le référentiel des communes (Excel)."""
    path = PATHS["COMMUNES"]
    try:
        df = pd.read_excel(path)
        if 'Num_Dep' in df.columns:
            df['Num_Dep'] = df['Num_Dep'].astype(str)
        return df
    except FileNotFoundError:
        st.error(f"Fichier introuvable : {path}")
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def charger_centres_departements() -> pd.DataFrame:
    """Charge les lat/lon des centres de départements (Excel)."""
    path = PATHS["CENTRES_DEPARTEMENTS"]
    try:
        return pd.read_excel(path)
    except FileNotFoundError:
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def charger_donnees_iris_socio() -> gpd.GeoDataFrame:
    """Charge les données IRIS (Parquet) et force la projection GPS."""
    path = PATHS["IRIS_SOCIO"]
    try:
        gdf = gpd.read_parquet(path)
        if gdf.crs is not None and gdf.crs.to_string() != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
        elif gdf.crs is None:
            gdf.set_crs("EPSG:4326", inplace=True)
        return gdf
    except Exception as e:
        st.error(f"Erreur chargement IRIS : {e}")
        return gpd.GeoDataFrame()


@st.cache_data(show_spinner=False)
def charger_coefficients_trafic() -> pd.DataFrame:
    """Charge la table des coefficients de trafic (Excel)."""
    path = PATHS["COEFF_TRAFIC"]
    try:
        return pd.read_excel(path)
    except FileNotFoundError:
        return pd.DataFrame(columns=['ville', 'coefficient'])


@st.cache_data(show_spinner="Chargement DVF...")
def charger_donnees_dvf() -> pd.DataFrame:
    """Charge le fichier DVF consolidé (Parquet) de manière optimisée."""
    path = PATHS["DVF"]
    try:
        cols_a_charger = [
            'latitude', 'longitude', 'prix_m2', 'type_local',
            'date_mutation', 'valeur_fonciere', 'surface_reelle_bati'
        ]
        df = pd.read_parquet(path, columns=cols_a_charger)

        if not pd.api.types.is_datetime64_any_dtype(df['date_mutation']):
            df['date_mutation'] = pd.to_datetime(df['date_mutation'], errors='coerce')

        if 'annee' not in df.columns:
            df['annee'] = df['date_mutation'].dt.year

        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(show_spinner="Chargement Risques...")
def charger_zones_risques(type_risque: str) -> gpd.GeoDataFrame:
    """Chargeur générique pour les risques (Inondation ou RGA)."""
    if type_risque == "INONDATION":
        path = PATHS["ZONES_INONDABLES"]
    elif type_risque == "RGA":
        path = PATHS["RGA_SECHERESSE"]
    else:
        return gpd.GeoDataFrame()

    try:
        return gpd.read_parquet(path)
    except Exception:
        return gpd.GeoDataFrame()

@st.cache_data(show_spinner="Chargement Moteur Climat...")
def charger_moteur_climat() -> pd.DataFrame:
    """
    Charge le fichier Parquet du Moteur Climat 2050.
    """
    path = PATHS["CLIMAT_2050"] # Utilise la clé définie dans config.py
    if not os.path.exists(path):
        st.warning(f"Fichier Climat 2050 introuvable: {path}")
        return pd.DataFrame()
    try:
        # Optimisation : On ne charge que les colonnes nécessaires
        cols = ['lat_round', 'lon_round'] + [c for c in pd.read_parquet(path, columns=['lat_round', 'lon_round']).columns if 'RCP' in c]
        df = pd.read_parquet(path, columns=cols)
        return df
    except Exception as e:
        st.error(f"Erreur chargement climat: {e}")
        return pd.DataFrame()