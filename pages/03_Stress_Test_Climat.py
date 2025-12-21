# Fichier: pages/03_Stress_Climat.py
import streamlit as st
import pandas as pd
import geopandas as gpd
import plotly.express as px
import time
import numpy as np
from shapely.geometry import Point
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from sqlalchemy import text

# --- IMPORTS ARCHITECTURE ---
from backend.database import connect_to_db
from utils.geo_tools import projeter_climat_2050
from backend.data_loaders import charger_zones_risques

# --- CONFIGURATION ---
st.title("📉 Stress Test & Audit Patrimoine")
st.markdown("""
    **Risk Pricing Engine :** Audit complet croisant Projections Climatiques 2050 (DRIAS), 
    Risques Physiques (Inondation/Argile) et Impacts Financiers.
    \n✅ **Compatible :** GPS, Adresses Postales ou Numéros SIRET.
""")

engine = connect_to_db()


# --- 0. FONCTIONS DE RÉSOLUTION GÉOGRAPHIQUE ---
def resolve_siret_to_coords(siret, db_engine):
    """Cherche Lat/Lon via SQL pour un SIRET donné."""
    try:
        # Nettoyage SIRET (chaine de caractères)
        siret_clean = str(siret).replace(" ", "").replace(".", "")
        query = text("SELECT latitude, longitude FROM stock_etablissement WHERE siret = :siret LIMIT 1")
        with db_engine.connect() as conn:
            result = conn.execute(query, {"siret": siret_clean}).fetchone()
            if result and result[0] is not None:
                return float(result[0]), float(result[1])
    except Exception:
        return None, None
    return None, None


def resolve_address_to_coords(address):
    """Géocode une adresse via Nominatim (OSM)."""
    try:
        # User_agent unique pour éviter le blocage
        geolocator = Nominatim(user_agent="geo_audit_app_v1")
        location = geolocator.geocode(address, timeout=10)
        if location:
            return location.latitude, location.longitude
    except Exception:
        return None, None
    return None, None


# --- 0B. CHARGEMENT DES RÉFÉRENTIELS (CACHE) ---
@st.cache_data
def load_risk_layers():
    gdf_inond = charger_zones_risques("INONDATION")
    gdf_rga = charger_zones_risques("RGA")
    return gdf_inond, gdf_rga


with st.spinner("Chargement des couches de risques..."):
    gdf_inond_ref, gdf_rga_ref = load_risk_layers()

# --- 1. IMPORT & CONFIGURATION ---
with st.sidebar:
    st.header("1. Import Portefeuille")
    up = st.file_uploader("Fichier CSV/Excel", type=["csv", "xlsx", "xls"])

    st.divider()

    # SÉLECTEUR DE MODE IMPORTANT
    input_mode = st.radio(
        "📍 Type de données en entrée :",
        ["Coordonnées GPS", "Adresses Postales", "SIRET"],
        help="Si vous n'avez pas les coordonnées GPS, l'outil tentera de les trouver via l'adresse ou le SIRET."
    )

if up:
    # Lecture
    try:
        if up.name.endswith('.csv'):
            up.seek(0)
            df = pd.read_csv(up, sep=None, engine='python')
        else:
            df = pd.read_excel(up)
    except Exception as e:
        st.error(f"Erreur lecture fichier : {e}")
        st.stop()

    # Mapping Dynamique des Colonnes
    cols = df.columns.tolist()

    st.markdown(f"**2. Configuration des Colonnes ({input_mode})**")
    c1, c2, c3 = st.columns(3)

    col_lat, col_lon, col_addr, col_siret = None, None, None, None

    # Logique d'affichage selon le mode choisi
    if input_mode == "Coordonnées GPS":
        def get_col(candidates):
            return next((c for c in cols if any(x in c.lower() for x in candidates)), cols[0])


        col_lat = c1.selectbox("Colonne Latitude", cols, index=cols.index(get_col(['lat', 'y_'])))
        col_lon = c2.selectbox("Colonne Longitude", cols, index=cols.index(get_col(['lon', 'lng', 'x_'])))

    elif input_mode == "Adresses Postales":
        col_addr = c1.selectbox("Colonne Adresse Complète", cols, index=0)
        st.caption("⚠️ Le géocodage d'adresses peut prendre du temps (env. 1 sec/ligne).")

    elif input_mode == "SIRET":
        col_siret = c1.selectbox("Colonne SIRET", cols, index=0)
        st.caption("ℹ️ Nécessite que le SIRET soit présent dans votre base de données locale.")

    # Options communes
    col_surf = c3.selectbox("Surface (m²) - Optionnel", ["Inconnu"] + cols, index=0)

    with st.expander("Options Avancées (Valeur & Business)"):
        col_id = st.selectbox("Identifiant/Nom Site", ["Auto"] + cols, index=0)
        valeur_m2 = st.number_input("Valeur Moyenne (€/m²) si inconnue", value=2000, step=100)

    # --- 2. LANCEMENT AUDIT ---
    if st.button("🚀 Lancer l'Audit et la Localisation", type="primary"):

        results = []
        progress_bar = st.progress(0, text="Initialisation...")
        start_time = time.time()

        total = len(df)
        sites_resolus = 0

        # --- PHASE 1 : RÉSOLUTION GÉOGRAPHIQUE & CLIMAT (BOUCLE) ---
        # On boucle ligne par ligne car on doit géocoder ou projeter le climat

        final_rows = []  # Liste pour stocker les objets pré-calculés

        for i, (idx, row) in enumerate(df.iterrows()):

            # Mise à jour barre progression
            pct = int((i / total) * 100)
            progress_bar.progress(pct / 100, text=f"Traitement site {i + 1}/{total}...")

            # 1. RÉCUPÉRATION LAT/LON
            lat, lon = None, None

            if input_mode == "Coordonnées GPS":
                try:
                    lat = float(row[col_lat])
                    lon = float(row[col_lon])
                except:
                    pass

            elif input_mode == "Adresses Postales":
                addr = str(row[col_addr])
                lat, lon = resolve_address_to_coords(addr)
                # Petit sleep pour être gentil avec l'API Nominatim si c'est gratuit
                time.sleep(0.5)

            elif input_mode == "SIRET":
                siret = str(row[col_siret])
                lat, lon = resolve_siret_to_coords(siret, engine)

            # 2. TRAITEMENT SI COORDONNÉES TROUVÉES
            if lat is not None and lon is not None and not np.isnan(lat):
                sites_resolus += 1

                # Info Site
                nom_site = str(row[col_id]) if col_id != "Auto" else f"Site {i + 1}"
                if input_mode == "SIRET": nom_site += f" ({row[col_siret]})"

                surface = 1000.0
                if col_surf != "Inconnu":
                    try:
                        surface = float(row[col_surf])
                    except:
                        surface = 1000.0

                # A. Projection Climat (DRIAS)
                try:
                    climat = projeter_climat_2050(lat, lon)
                    rcp85 = climat.get("RCP 8.5", {})
                    canicule_j = rcp85.get("Jours Canicule", 0)
                    nuits_trop = rcp85.get("Nuits Tropicales", 0)
                except:
                    canicule_j, nuits_trop = 0, 0

                # On stocke pour la phase 2 (Risques Physiques Vectoriels)
                final_rows.append({
                    "ID": nom_site,
                    "geometry": Point(lon, lat),  # Pour GeoPandas
                    "Latitude": lat, "Longitude": lon, "Surface": surface,
                    "Jours Canicule 2050": canicule_j,
                    "Nuits Tropicales 2050": nuits_trop
                })

            else:
                # Site non localisé
                pass

        # --- PHASE 2 : RISQUES PHYSIQUES MASSIFS (OPTIMISATION) ---
        if final_rows:
            progress_bar.progress(0.9, text="Croisement Risques Physiques (Inondation/RGA)...")

            # Création GeoDataFrame
            gdf_sites = gpd.GeoDataFrame(final_rows, crs="EPSG:4326")

            # Inondation (SJOIN)
            gdf_sites["Risque Inondation"] = "Aucun"
            if not gdf_inond_ref.empty:
                joined = gpd.sjoin(gdf_sites, gdf_inond_ref[['geometry', 'NIVEAU_ALEA']], how='left',
                                   predicate='intersects')
                # Dédoublonnage (prendre le pire risque)
                if 'NIVEAU_ALEA' in joined.columns:
                    # Astuce de tri : Fort > Moyen > Faible
                    priorite = {'Fort': 3, 'Moyen': 2, 'Faible': 1}
                    joined['prio'] = joined['NIVEAU_ALEA'].map(priorite).fillna(0)
                    joined = joined.sort_values('prio', ascending=False)
                    joined = joined[~joined.index.duplicated(keep='first')]
                    gdf_sites.loc[joined.index, "Risque Inondation"] = joined['NIVEAU_ALEA'].fillna("Aucun")

            # RGA (SJOIN)
            gdf_sites["Risque Argile"] = "Aucun"
            if not gdf_rga_ref.empty:
                joined_rga = gpd.sjoin(gdf_sites, gdf_rga_ref[['geometry', 'NIVEAU_ALEA']], how='left',
                                       predicate='intersects')
                joined_rga = joined_rga[~joined_rga.index.duplicated(keep='first')]
                gdf_sites.loc[joined_rga.index, "Risque Argile"] = joined_rga['NIVEAU_ALEA'].fillna("Aucun")

            # --- PHASE 3 : CALCULS FINANCIERS FINAUX ---
            final_results = []
            for idx, row in gdf_sites.iterrows():
                # Calculs Business
                valeur_site = row['Surface'] * valeur_m2

                # Modèle de perte simplifié
                perte_pct = 0.0
                risk_inond = str(row["Risque Inondation"])
                risk_rga = str(row["Risque Argile"])
                canicule = row["Jours Canicule 2050"]

                if "Fort" in risk_inond:
                    perte_pct += 0.20
                elif "Moyen" in risk_inond:
                    perte_pct += 0.10

                if "Fort" in risk_rga: perte_pct += 0.05

                if canicule > 20: perte_pct += 0.05  # Malus thermique fort

                perte_estimee = valeur_site * min(perte_pct, 1.0)
                co2 = (row['Surface'] * 20) / 1000  # 20kg/m2

                # Objet final propre (sans geometry)
                final_results.append({
                    "ID": row['ID'],
                    "Latitude": row['Latitude'], "Longitude": row['Longitude'],
                    "Surface": row['Surface'],
                    "Valeur Actif (€)": valeur_site,
                    "Perte Estimée (€)": perte_estimee,
                    "Impact CO2 (t/an)": co2,
                    "Risque Inondation": risk_inond,
                    "Risque Argile": risk_rga,
                    "Jours Canicule 2050": row["Jours Canicule 2050"],
                    "Score Risque Global": perte_pct * 100
                })

            df_res = pd.DataFrame(final_results)

            progress_bar.progress(1.0, text="Terminé !")

            # --- DASHBOARD ---
            st.divider()

            # Feedback Localisation
            if sites_resolus < total:
                st.warning(
                    f"⚠️ Attention : Seulement {sites_resolus} sites sur {total} ont pu être localisés. Vérifiez les adresses/SIRET.")
            else:
                st.success(f"✅ 100% des sites localisés et audités ({total} sites).")

            # A. KPIs
            total_valeur = df_res["Valeur Actif (€)"].sum()
            total_perte = df_res["Perte Estimée (€)"].sum()

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Valorisation Totale", f"{total_valeur / 1e6:.1f} M€")
            k2.metric("Value at Risk (VAR)", f"{total_perte / 1e6:.1f} M€",
                      delta=f"-{(total_perte / total_valeur) * 100:.1f}%", delta_color="inverse")
            k3.metric("Sites Critiques", len(df_res[df_res["Score Risque Global"] > 15]), "Risque > 15%")
            k4.metric("Canicule Max", f"+{df_res['Jours Canicule 2050'].max()} j", "Horizon 2050")

            # B. TABS
            tab_map, tab_biz, tab_data = st.tabs(["🗺️ Cartographie", "🚦 Matrice Stratégique", "📥 Données"])

            with tab_map:
                fig_map = px.scatter_mapbox(
                    df_res, lat="Latitude", lon="Longitude",
                    color="Score Risque Global", size="Valeur Actif (€)",
                    hover_name="ID",
                    color_continuous_scale="RdYlGn_r", size_max=25, zoom=5,
                    mapbox_style="carto-positron", title="Carte des Risques (Couleur = Danger, Taille = Valeur)"
                )
                st.plotly_chart(fig_map, use_container_width=True)

            with tab_biz:
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.markdown("##### Matrice 'Double Peine'")
                    fig_scatter = px.scatter(
                        df_res, x="Valeur Actif (€)", y="Score Risque Global",
                        color="Risque Inondation", size="Surface",
                        hover_name="ID", text="ID"
                    )
                    # Ligne de danger
                    fig_scatter.add_hline(y=15, line_dash="dot", line_color="red", annotation_text="Seuil Critique")
                    st.plotly_chart(fig_scatter, use_container_width=True)
                with c2:
                    st.write("### Répartition Inondation")
                    st.write(df_res["Risque Inondation"].value_counts())

            with tab_data:
                st.dataframe(df_res)
                csv = df_res.to_csv(index=False, sep=";").encode('utf-8-sig')
                st.download_button("Télécharger Rapport Complet", csv, "audit_climat.csv", "text/csv")

        else:
            st.error("Aucun site n'a pu être localisé. Vérifiez vos Adresses ou SIRET.")

else:
    st.info("Veuillez charger un fichier pour commencer.")
    st.markdown("### Exemples de formats acceptés")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.caption("Option 1 : GPS")
        st.code("id,lat,lon\nSite A,48.85,2.35")
    with c2:
        st.caption("Option 2 : Adresse")
        st.code("id,adresse\nSite B,10 rue de Rivoli Paris")
    with c3:
        st.caption("Option 3 : SIRET")
        st.code("id,siret\nSite C,80293847200012")