# Fichier: pages/03_Stress_Test_Climat.py
import streamlit as st
import pandas as pd
import geopandas as gpd
from backend.data_loaders import charger_zones_risques
from backend.calculators import (
    estimer_valeur_portefeuille, calculer_pertes_sectorielles, estimer_empreinte_carbone
)
from utils.geo_tools import geocoder_adresse_nominatim
from frontend.maps import \
    creer_carte_implantation  # On réutilise la carte générique simplifiée ou on en fait une spécifique

st.title("🌪️ Stress Test Climatique (Horizon 2050)")

# --- 1. IMPORT ---
up = st.file_uploader("Portefeuille (CSV/Excel) - Colonnes: adresse, ville, surface...", type=["csv", "xlsx"])

if up:
    df = pd.read_csv(up) if up.name.endswith('.csv') else pd.read_excel(up)

    # --- 2. CONFIG ---
    with st.expander("Paramètres de Simulation", expanded=True):
        c1, c2 = st.columns(2)
        scenario = c1.selectbox("Scénario GIEC", ["RCP 4.5 (Modéré)", "RCP 8.5 (Pessimiste)"])
        cout_m2 = c2.number_input("Coût Reconstruction (€/m²)", 2000)

    # --- 3. TRAITEMENT ---
    with st.spinner("Modélisation..."):
        # A. Géocodage si manquant
        if 'latitude' not in df.columns:
            st.warning("Géocodage en cours (ceci peut être long)...")
            # Boucle simple (dans la vraie vie on parallélise)
            coords = df['adresse'].apply(geocoder_adresse_nominatim)
            df['latitude'] = coords.apply(lambda x: x['latitude'] if x else None)
            df['longitude'] = coords.apply(lambda x: x['longitude'] if x else None)
            df = df.dropna(subset=['latitude'])

        # B. Valorisation & Risques
        df_val = estimer_valeur_portefeuille(df, cout_m2)

        # C. Spatialisation Risques
        gdf_pt = gpd.GeoDataFrame(
            df_val, geometry=gpd.points_from_xy(df_val.longitude, df_val.latitude), crs="EPSG:4326"
        )

        # Chargement Risques
        inond = charger_zones_risques("INONDATION")
        rga = charger_zones_risques("RGA")

        # Spatial Join (Sjoin)
        if not inond.empty:
            gdf_pt = gpd.sjoin(gdf_pt, inond[['NIVEAU_ALEA', 'geometry']], how='left', predicate='intersects')
            gdf_pt = gdf_pt.rename(columns={'NIVEAU_ALEA': 'alea_inondation'})
            # Clean duplicate columns if sjoin created index_right
            if 'index_right' in gdf_pt.columns: del gdf_pt['index_right']

        if not rga.empty:
            gdf_pt = gpd.sjoin(gdf_pt, rga[['NIVEAU_ALEA', 'geometry']], how='left', predicate='intersects')
            gdf_pt = gdf_pt.rename(columns={'NIVEAU_ALEA': 'alea_secheresse'})

        # D. Calcul Pertes
        gdf_final = calculer_pertes_sectorielles(gdf_pt, scenario, col_naf='code_naf')
        gdf_final = estimer_empreinte_carbone(gdf_final, col_naf='code_naf')

    # --- 4. DASHBOARD ---
    perte_totale = gdf_final['perte_estimee'].sum()
    valeur_totale = gdf_final['valeur_assuree'].sum()
    ratio = (perte_totale / valeur_totale * 100) if valeur_totale > 0 else 0

    k1, k2, k3 = st.columns(3)
    k1.metric("Valeur Portefeuille", f"{valeur_totale / 1e6:.1f} M€")
    k2.metric("Pertes Estimées (EL)", f"{perte_totale / 1e6:.1f} M€", f"-{ratio:.1f}%", delta_color="inverse")
    k3.metric("Carbone Latent", f"{gdf_final['emission_tco2'].sum():.0f} tCO2")

    st.dataframe(gdf_final.drop(columns='geometry'))

    # Carte rapide
    st.map(gdf_final, size=20, color='#ff0000')