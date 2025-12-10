# Fichier: pages/02_Zone_Implantation.py

import streamlit as st
import geopandas as gpd
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from streamlit_folium import st_folium
from shapely.geometry import Point, shape

# Imports Métiers
from fonctions_basiques import (
    charger_communes, charger_donnees_iris_socio, preparer_donnees_socio,
    charger_zones_inondables, charger_donnees_rga, charger_donnees_dvf,
    connect_to_db, calculer_comparatif_radar,
    auditer_risque_batiments, transfo_geodataframe,
    recuperer_reseau_existant, calculer_score_cannibalisation_isochrone,
    projeter_climat_2050
)
from fonctions_cartographie import (
    creer_carte_implantation, calculer_isochrone_et_cacher,
    rechercher_poi_osm, rechercher_batiments_osm, geocoder_adresse_nominatim_ui,
    analyser_environnement_naturel,analyser_locomotives
)
from fonctions_api import get_code_insee_lat_lon, get_historique_catnat, get_stats_sinistralite
from interface import (
    interface_selection_socio, interface_selection_poi, POI_CONFIG,
    interface_selection_batiments, interface_filtre_geo_risque, interface_point_interet
)

# =============================================================================
# CONFIGURATION
# =============================================================================
PATH_COMMUNES = "data/Communes_France_Metro.xlsx"
PATH_IRIS_SOCIO = "data/iris_socio_data_final.parquet"
PATH_ZONES_INONDABLES = "data/zones_inondables_v2.parquet"
PATH_RGA_SECHERESSE = "data/rga_secheresse_v2.parquet"
PATH_DVF_PARQUET = "data/Valeurs_foncieres_geoloc_2020_2025.parquet"


# =============================================================================
# HELPERS LOCAUX
# =============================================================================

def generer_avis_synthetique(note_globale, malus_inond_pondere):
    """Génère l'avis avec prise en compte du malus pondéré."""
    statut, couleur = "ZONE DÉGRADÉE", "red"
    if malus_inond_pondere >= 15:
        statut, couleur = "SITE À RISQUE ÉLEVÉ", "red"
    elif note_globale >= 75:
        statut, couleur = "EMPLACEMENT PREMIUM", "green"
    elif note_globale >= 55:
        statut, couleur = "BON POTENTIEL", "orange"
    elif note_globale >= 40:
        statut, couleur = "POTENTIEL STANDARD", "#A67C00"  # Doré foncé
    return statut, couleur


def _calculer_score_attractivite(pop_zone, revenu_zone, nb_ventes_immo,
                                 niveau_inond_max, ratio_surf_inond,
                                 niveau_rga_max, ratio_surf_rga,
                                 taux_cannib, surface_km2):
    """
    Calcule le GeoScore avec des explications textuelles intelligentes.
    """
    score = 0
    surface_km2 = max(surface_km2, 0.1)

    densite_pop = pop_zone / surface_km2
    densite_ventes = nb_ventes_immo / surface_km2

    # 1. POTENTIEL (40 pts)
    s_densite = min(densite_pop / 2500, 1) * 20
    s_revenu = min(revenu_zone / 28000, 1) * 20 if revenu_zone else 10
    part_potentiel = s_densite + s_revenu
    score += part_potentiel

    # 2. DYNAMISME (30 pts)
    s_immo = min(densite_ventes / 10, 1) * 30
    part_dynamisme = s_immo
    score += part_dynamisme

    # 3. RÉSILIENCE CLIMATIQUE (30 pts)
    base_malus_i = 20 if niveau_inond_max == 3 else 10 if niveau_inond_max == 2 else 5 if niveau_inond_max == 1 else 0
    base_malus_r = 10 if niveau_rga_max == 3 else 5 if niveau_rga_max == 2 else 2 if niveau_rga_max == 1 else 0

    malus_i_effectif = base_malus_i * ratio_surf_inond
    malus_r_effectif = base_malus_r * ratio_surf_rga

    part_resilience = max(0, 30 - malus_i_effectif - malus_r_effectif)
    score += part_resilience

    # 4. SATURATION (Malus Externe)
    malus_c = 0
    if taux_cannib > 10:
        malus_c = min((taux_cannib - 10) * 1.5, 30)

    score_final = max(0, score - malus_c)

    # --- FORMATAGE TEXTUEL INTELLIGENT ---
    def format_texte_risque(malus, ratio):
        if malus < 0.1:  # Si le malus est quasi nul
            if ratio > 0.01:  # Mais qu'on est dans la zone (>1%)
                return f"✅ Impact Nul ({ratio:.0%} de la zone classée 'Faible')"
            else:
                return "⚪ Aucun risque détecté"
        else:
            return f"⚠️ -{malus:.1f} pts (sur {ratio:.0%} de la zone)"

    explications = {
        "Densité Pop": f"{int(densite_pop)} hab/km²",
        "Revenu Médian": f"{int(revenu_zone)} €",
        "Densité Ventes (2 ans)": f"{densite_ventes:.1f} act./km²",
        "Malus Inondation": format_texte_risque(malus_i_effectif, ratio_surf_inond),
        "Malus Sécheresse": format_texte_risque(malus_r_effectif, ratio_surf_rga),
        "Malus Saturation": f"-{int(malus_c)} pts" if malus_c > 0 else "✅ Aucune (Tolérance <10%)"
    }

    parts = {
        "Potentiel": round(part_potentiel, 1),
        "Dynamisme": round(part_dynamisme, 1),
        "Résilience": round(part_resilience, 1)
    }

    return int(score_final), parts, int(malus_c), malus_i_effectif, malus_r_effectif, explications


def _filtrer_risque_geo(gdf, regions, depts):
    """Filtre un GDF de risque selon les choix utilisateur."""
    if gdf.empty: return gdf
    # Création colonne filtre combinée si nécessaire
    if 'NOM_DEP' in gdf.columns and 'Num_Dep' in gdf.columns:
        gdf['affichage_dep'] = gdf['Num_Dep'] + " - " + gdf['NOM_DEP'].str.upper()

    if regions and 'NOM_REG' in gdf.columns:
        return gdf[gdf['NOM_REG'].isin(regions)]
    elif depts and 'affichage_dep' in gdf.columns:
        return gdf[gdf['affichage_dep'].isin(depts)]
    return gdf


# =============================================================================
# MAIN EXECUTION
# =============================================================================

st.title("📍 Diagnostic Territorial & Risques")
engine = connect_to_db()

with st.spinner("Chargement des référentiels..."):
    df_communes = charger_communes(PATH_COMMUNES)
    gdf_inondations_full = charger_zones_inondables(PATH_ZONES_INONDABLES)
    gdf_rga_full = charger_donnees_rga(PATH_RGA_SECHERESSE)
    df_iris_base = charger_donnees_iris_socio(PATH_IRIS_SOCIO)
    df_dvf_total = charger_donnees_dvf(PATH_DVF_PARQUET)

if 'dict_geodatas' not in st.session_state:
    st.session_state['dict_geodatas'] = preparer_donnees_socio(df_iris_base, df_communes)
dict_geodatas = st.session_state['dict_geodatas']

# --- SIDEBAR ---
with st.sidebar:
    st.header("🎛️ Calques & Filtres")

    # 1. Socio & POI
    gdf_socio_filtre, indicateur, nom_indicateur, maille = interface_selection_socio(dict_geodatas)
    poi_selectionnes_sidebar = interface_selection_poi()

    st.divider()

    # 2. Bâtiments & Risques
    st.markdown("### 🏗️ Bâtiments & Risques")

    # Bâtiments
    if 'show_batiments' not in st.session_state: st.session_state.show_batiments = False


    def toggle_bati():
        st.session_state.show_batiments = not st.session_state.show_batiments


    cb_bati = st.checkbox("Afficher Bâtiments (OSM)", value=st.session_state.show_batiments, key="cb_bati_sidebar",
                          on_change=toggle_bati)

    if st.session_state.show_batiments:
        c1, c2 = st.columns(2)
        surface_min = c1.number_input("Min m²", 0, 10000, 0, step=50)
        surface_max = c2.number_input("Max m²", 0, 100000, 3000, step=100)
    else:
        surface_min, surface_max = 0, 3000

    # Risques (Filtres Géographiques)
    show_inond = st.checkbox("Afficher Inondations", value=False)
    reg_inond, dep_inond = [], []
    if show_inond: reg_inond, dep_inond = interface_filtre_geo_risque(df_communes, "inond")

    show_rga = st.checkbox("Afficher Sécheresse", value=False)
    reg_rga, dep_rga = [], []
    if show_rga: reg_rga, dep_rga = interface_filtre_geo_risque(df_communes, "rga")

    st.divider()

    # 🆕 3. SATURATION / RÉSEAU (CANNIBALISATION)
    st.markdown("### 🕸️ Réseau & Cannibalisation")
    mode_cannibale = st.toggle("Activer l'analyse Réseau", value=False)

    gdf_reseau_client = gpd.GeoDataFrame()
    nom_enseigne_reseau = None
    source_reseau = None
    rayon_search = 15  # Valeur par défaut

    if mode_cannibale:
        source_reseau = st.radio("Source du réseau :", ["Base de Données (SIRENE)", "Fichier Client (CSV/Excel)"],
                                 horizontal=True)

        if source_reseau == "Fichier Client (CSV/Excel)":
            uploaded_reseau = st.file_uploader("Charger points de vente existants", type=["csv", "xlsx"])
            if uploaded_reseau:
                try:
                    if uploaded_reseau.name.endswith('.csv'):
                        df_res = pd.read_csv(uploaded_reseau)
                    else:
                        df_res = pd.read_excel(uploaded_reseau)
                    # Détection auto colonnes lat/lon
                    lat_col = next((c for c in df_res.columns if 'lat' in c.lower()), None)
                    lon_col = next((c for c in df_res.columns if 'lon' in c.lower()), None)
                    if lat_col and lon_col:
                        gdf_reseau_client = transfo_geodataframe(df_res, lon_col, lat_col)
                        st.success(f"✅ {len(gdf_reseau_client)} points chargés.")
                    else:
                        st.error("Colonnes Latitude/Longitude introuvables.")
                except Exception as e:
                    st.error(f"Erreur fichier : {e}")

        else:  # Mode BDD SIRENE
            c_ens, c_ray = st.columns([2, 1])
            nom_enseigne_reseau = c_ens.text_input("Enseigne à éviter", placeholder="Ex: Carrefour City, Sephora...")
            rayon_search = c_ray.number_input("Rayon (km)", 1, 100, 15, help="Rayon de recherche autour de la cible")

            if nom_enseigne_reseau:
                st.caption(f"Recherche de '{nom_enseigne_reseau}' dans {rayon_search}km.")

    st.divider()

    # 4. Immobilier
    st.markdown("### 🏠 Immobilier")
    afficher_dvf = st.checkbox("Afficher Transactions (Récent)", value=False)
    dvf_type_map = "Tous"
    mode_visu_map = "Points"
    if afficher_dvf:
        dvf_type_map = st.selectbox("Type de bien", ["Tous", "Commerce", "Maison", "Appartement"])
        mode_visu_map = st.selectbox("Style carte", ["Points", "Heatmap"])

# --- PRÉPARATION MAP (RISQUES) ---
gdf_inond_map = _filtrer_risque_geo(gdf_inondations_full, reg_inond, dep_inond) if show_inond else gpd.GeoDataFrame()
gdf_rga_map = _filtrer_risque_geo(gdf_rga_full, reg_rga, dep_rga) if show_rga else gpd.GeoDataFrame()

# --- DÉFINITION ZONE ---
result_point_central = interface_point_interet(engine=engine)
final_lat, final_lon = None, None
final_nom, final_adresse_str = None, None
mode, radius = result_point_central['mode'], result_point_central['radius']

if result_point_central['source'] == "Adresse":
    res_geo = geocoder_adresse_nominatim_ui(result_point_central['valeur'])
    if res_geo:
        final_lat, final_lon, final_nom, final_adresse_str = res_geo['latitude'], res_geo['longitude'], res_geo[
            'denominationunitelegale'], res_geo['adresse']
elif result_point_central['source'] == "Coordonnées":
    if result_point_central['valeur']:
        final_lat, final_lon, final_nom, final_adresse_str = \
            result_point_central['valeur']['latitude'], result_point_central['valeur'][
                'longitude'], f"Point ({result_point_central['valeur']['latitude']:.4f})", "Manuel"
elif result_point_central['source'] == "SIRET/SIREN":
    if result_point_central['valeur']:
        r = result_point_central['valeur']
        final_lat, final_lon, final_nom, final_adresse_str = r.get('latitude'), r.get('longitude'), r.get(
            'denominationunitelegale'), r.get('adresse')

# --- CALCULS ANALYTIQUES ---
if final_lat and final_lon:

    # 1. Géométrie Zone
    temps_isochrones = 5
    if mode == 'Isochrones': temps_isochrones = st.slider("Temps de trajet (min)", 2, 20, 5, 1)

    zone_analyse_geom = None
    surface_zone_km2 = 0.1

    if mode == 'Isochrones':
        f = calculer_isochrone_et_cacher(final_lon, final_lat, temps_isochrones * 60)
        if f:
            zone_analyse_geom = shape(f['geometry'])
            gdf_iso = gpd.GeoDataFrame(geometry=[zone_analyse_geom], crs="EPSG:4326").to_crs("EPSG:2154")
            surface_zone_km2 = gdf_iso.area.iloc[0] / 1_000_000
    elif mode == "Cercle d'influence":
        p = gpd.GeoDataFrame(geometry=[Point(final_lon, final_lat)], crs="EPSG:4326")
        zone_l93 = p.to_crs("EPSG:2154").buffer(radius).iloc[0]
        surface_zone_km2 = zone_l93.area / 1_000_000
        zone_analyse_geom = gpd.GeoDataFrame(geometry=[zone_l93], crs="EPSG:2154").to_crs("EPSG:4326").geometry.iloc[0]
    elif mode == "Point seul":
        st.info("Mode Visualisation simple.")
        zone_analyse_geom = None

    # 2. DVF (Filtres et Séparation)
    df_dvf_zone = pd.DataFrame()
    df_dvf_kpi = pd.DataFrame()

    if not df_dvf_total.empty:
        m = 0.02
        df_dvf_zone = df_dvf_total[
            (df_dvf_total['latitude'] > final_lat - m) & (df_dvf_total['latitude'] < final_lat + m) &
            (df_dvf_total['longitude'] > final_lon - m) & (df_dvf_total['longitude'] < final_lon + m)
            ].copy()

        if not df_dvf_zone.empty:
            if 'annee' not in df_dvf_zone.columns:
                df_dvf_zone['date_mutation'] = pd.to_datetime(df_dvf_zone['date_mutation'])
                df_dvf_zone['annee'] = df_dvf_zone['date_mutation'].dt.year
            df_dvf_kpi = df_dvf_zone[df_dvf_zone['annee'] >= 2024].copy()

    # 3. Bâtiments
    gdf_batiments_audit = gpd.GeoDataFrame()
    if zone_analyse_geom and st.session_state.show_batiments:
        with st.spinner("Analyse technique et environnementale..."):
            gdf_bat_brut = rechercher_batiments_osm(zone_analyse_geom.bounds)
            if not gdf_bat_brut.empty:
                gdf_bat_work = gdf_bat_brut.copy()
                bbox = zone_analyse_geom.bounds

                if not gdf_inondations_full.empty:
                    risques_locaux = gdf_inondations_full.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]]
                    if not risques_locaux.empty:
                        gdf_bat_work = auditer_risque_batiments(gdf_bat_work, risques_locaux, "Inondation",
                                                                "NIVEAU_ALEA")

                if not gdf_rga_full.empty:
                    risques_locaux_rga = gdf_rga_full.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]]
                    if not risques_locaux_rga.empty:
                        gdf_bat_work = auditer_risque_batiments(gdf_bat_work, risques_locaux_rga, "Argile",
                                                                "NIVEAU_ALEA")

                for col in ['has_Inondation', 'has_Argile']:
                    if col not in gdf_bat_work.columns: gdf_bat_work[col] = False
                for col in ['niveau_Inondation', 'niveau_Argile']:
                    if col not in gdf_bat_work.columns: gdf_bat_work[col] = "Aucun"

                gdf_batiments_audit = gdf_bat_work[gdf_bat_work.within(zone_analyse_geom)]

    # 4. POI
    gdf_poi_trouves = gpd.GeoDataFrame()
    if zone_analyse_geom and poi_selectionnes_sidebar:
        bbox = zone_analyse_geom.bounds
        l = [rechercher_poi_osm(bbox, POI_CONFIG[c]['tags']).assign(categorie=c) for c in poi_selectionnes_sidebar]
        res = [g for g in l if not g.empty]
        if res: gdf_poi_trouves = pd.concat(res, ignore_index=True)[lambda x: x.within(zone_analyse_geom)]

    # 5. CALCUL CANNIBALISATION (LOGIQUE INTÉGRÉE)
    taux_can = 0
    gdf_iso_reseau_visu = gpd.GeoDataFrame()

    # On charge le réseau BDD ici si besoin (pour avoir la lat/lon du point central)
    if mode_cannibale and source_reseau == "Base de Données (SIRENE)" and nom_enseigne_reseau:
        with st.spinner(f"Recherche '{nom_enseigne_reseau}' dans {rayon_search}km..."):
            gdf_reseau_client = recuperer_reseau_existant(engine, nom_enseigne_reseau, final_lat, final_lon,
                                                          rayon_search)
            if not gdf_reseau_client.empty:
                st.toast(f"{len(gdf_reseau_client)} magasins '{nom_enseigne_reseau}' trouvés.", icon="🚩")
            else:
                st.toast("Aucun magasin de l'enseigne trouvé à proximité.", icon="ℹ️")

    # Si on a un réseau (fichier ou bdd) et une zone, on calcule l'intersection
    if mode_cannibale and not gdf_reseau_client.empty and zone_analyse_geom:
        # On utilise le même temps isochrone que pour la zone principale pour cohérence
        temps_iso_ref = temps_isochrones if mode == 'Isochrones' else 10
        with st.spinner("Calcul des chevauchements de zones..."):
            taux_can, gdf_iso_reseau_visu = calculer_score_cannibalisation_isochrone(zone_analyse_geom,
                                                                                     gdf_reseau_client, temps_iso_ref)

    # =========================================================
    #  🏆 SCORE & DASHBOARD
    # =========================================================
    if zone_analyse_geom:
        st.markdown("---")

        # Socio
        pop, rev = 0, 0
        if 'IRIS' in dict_geodatas and not dict_geodatas['IRIS'].empty:
            df_iris_zone = gpd.sjoin(dict_geodatas['IRIS'],
                                     gpd.GeoDataFrame({'geometry': [zone_analyse_geom]}, crs="EPSG:4326"), how="inner",
                                     predicate="intersects")
            if not df_iris_zone.empty:
                pop = df_iris_zone['Population_totale'].sum() if 'Population_totale' in df_iris_zone.columns else 0
                rev = df_iris_zone['Revenu_median'].mean() if 'Revenu_median' in df_iris_zone.columns else 0

        # Risque
        score_inond_max, ratio_surf_inond = 0, 0.0
        score_rga_max, ratio_surf_rga = 0, 0.0

        # Calcul d'aire précis en Lambert 93
        gdf_zone_l93 = gpd.GeoDataFrame({'geometry': [zone_analyse_geom]}, crs="EPSG:4326").to_crs("EPSG:2154")
        aire_zone_m2 = gdf_zone_l93.area.iloc[0]

        # A. Inondations
        if not gdf_inondations_full.empty:
            risques_possibles = gdf_inondations_full.cx[zone_analyse_geom.bounds[0]:zone_analyse_geom.bounds[2],
                                zone_analyse_geom.bounds[1]:zone_analyse_geom.bounds[3]]
            if not risques_possibles.empty:
                risques_l93 = risques_possibles.to_crs("EPSG:2154")
                try:
                    intersection = gpd.overlay(gdf_zone_l93, risques_l93, how='intersection')
                    if not intersection.empty:
                        aire_risque = intersection.area.sum()
                        ratio_surf_inond = min(aire_risque / aire_zone_m2, 1.0)
                        risques_trouves = intersection['NIVEAU_ALEA'].unique()
                        if any('fort' in str(s).lower() for s in risques_trouves):
                            score_inond_max = 3
                        elif any('moyen' in str(s).lower() for s in risques_trouves):
                            score_inond_max = 2
                        else:
                            score_inond_max = 1
                except:
                    pass

        # B. Sécheresse
        if not gdf_rga_full.empty:
            risques_possibles = gdf_rga_full.cx[zone_analyse_geom.bounds[0]:zone_analyse_geom.bounds[2],
                                zone_analyse_geom.bounds[1]:zone_analyse_geom.bounds[3]]
            if not risques_possibles.empty:
                risques_l93 = risques_possibles.to_crs("EPSG:2154")
                try:
                    intersection = gpd.overlay(gdf_zone_l93, risques_l93, how='intersection')
                    if not intersection.empty:
                        aire_risque = intersection.area.sum()
                        ratio_surf_rga = min(aire_risque / aire_zone_m2, 1.0)
                        risques_trouves = intersection['NIVEAU_ALEA'].unique()
                        if any('fort' in str(s).lower() for s in risques_trouves):
                            score_rga_max = 3
                        elif any('moyen' in str(s).lower() for s in risques_trouves):
                            score_rga_max = 2
                        else:
                            score_rga_max = 1
                except:
                    pass

        # Scoring
        score_final, parts, malus_c, malus_i, malus_r, ex = _calculer_score_attractivite(
            pop, rev, len(df_dvf_kpi),
            score_inond_max, ratio_surf_inond,
            score_rga_max, ratio_surf_rga,
            taux_can, surface_zone_km2
        )
        statut_zone, couleur_statut = generer_avis_synthetique(score_final, malus_i)

        # =========================================================
        #  AFFICHAGE DU DASHBOARD
        # =========================================================

        # 1. LE VERDICT
        c_score, c_statut = st.columns([1, 2])

        with c_score:
            st.metric("GeoScore", f"{score_final}/100")

        with c_statut:
            if couleur_statut == "green":
                st.success(f"### {statut_zone}")
            elif couleur_statut == "orange":
                st.warning(f"### {statut_zone}")
            else:
                st.error(f"### {statut_zone}")

        st.markdown("---")

        # 2. LES FACTEURS CLÉS
        st.caption("Décomposition des Facteurs Clés :")
        k1, k2, k3 = st.columns(3)

        with k1:
            st.progress(parts['Potentiel'] / 40, f"📈 Potentiel ({parts['Potentiel']} pts)")
        with k2:
            st.progress(parts['Dynamisme'] / 30, f"🚀 Dynamisme ({parts['Dynamisme']} pts)")
        with k3:
            st.progress(parts['Résilience'] / 30, f"🛡️ Résilience ({parts['Résilience']} pts)")

        if mode_cannibale:
            st.write("")
            st.progress(min(taux_can / 100, 1.0), f"🛑 Saturation Réseau ({taux_can:.1f}%)")

        # Note Méthodologique
        with st.expander("ℹ️ Comprendre la notation (Méthodologie Investisseur)"):
            t_data, t_method = st.tabs(["🔍 Données de la Zone", "📊 Barème & Logique de Calcul"])

            with t_data:
                c_ex1, c_ex2 = st.columns(2)
                with c_ex1:
                    st.markdown("**Indicateurs Bruts**")
                    st.write(f"- Densité Pop : **{ex['Densité Pop']}**")
                    st.write(f"- Revenu Médian : **{ex['Revenu Médian']}**")
                    st.write(f"- Densité Ventes : **{ex['Densité Ventes (2 ans)']}**")
                with c_ex2:
                    st.markdown("**Impact des Risques**")
                    st.write(f"- Inondation : **{ex['Malus Inondation']}**")
                    st.write(f"- Sécheresse : **{ex['Malus Sécheresse']}**")
                    if mode_cannibale:
                        st.write(f"- Saturation : **{ex['Malus Saturation']}**")

            with t_method:
                html_table = """
                <table style="width:100%; border-collapse: collapse; font-family: sans-serif; font-size: 13px;">
                <thead>
                    <tr style="background-color: #f0f2f6; border-bottom: 2px solid #ddd;">
                        <th style="text-align: left; padding: 8px;">Composante</th>
                        <th style="text-align: center; padding: 8px;">Poids</th>
                        <th style="text-align: left; padding: 8px;">Règle de Calcul & Exemples</th>
                    </tr>
                </thead>
                <tbody>
                    <tr style="border-bottom: 1px solid #eee;">
                        <td style="font-weight: bold; padding: 8px;">🛡️ Résilience (Climat)</td>
                        <td style="text-align: center; padding: 8px;">+30 pts<br><small>(Capital départ)</small></td>
                        <td style="padding: 8px;">
                            Le malus dépend de la <b>Gravité</b> (Faible/Moyen/Fort) et de la <b>Surface Touchée</b>.<br>
                            <br>
                            <b>🌊 Inondation (Max -20 pts) :</b>
                            <ul>
                                <li><b>Pour perdre 10 pts :</b> Avoir un risque <b>Fort</b> sur <b>50%</b> du terrain.</li>
                                <li><b>Pour perdre 2 pts :</b> Avoir un risque <b>Moyen</b> sur <b>20%</b> du terrain.</li>
                            </ul>
                            <b>☀️ Sécheresse (Max -10 pts) :</b>
                            <ul>
                                <li><b>Pour perdre 10 pts :</b> Avoir un risque <b>Fort</b> sur <b>100%</b> du terrain.</li>
                                <li><b>Pour perdre 5 pts :</b> Avoir un risque <b>Fort</b> sur <b>50%</b> du terrain.</li>
                            </ul>
                            <i>Si le risque est "Faible" ou "Nul", le malus est de 0, même si on est 100% dans la zone.</i>
                        </td>
                    </tr>
                    <tr style="border-bottom: 1px solid #eee;">
                        <td style="font-weight: bold; padding: 8px;">🛑 Saturation (Réseau)</td>
                        <td style="text-align: center; padding: 8px;">Malus<br><small>(Max -30)</small></td>
                        <td style="padding: 8px;">
                            Pénalité si la zone empiète sur un magasin existant (rayon 2km).<br>
                            <br>
                            <b>Exemples de pénalités :</b>
                            <ul>
                                <li><b>0 pt :</b> Chevauchement de <b>10%</b> (Tolérance).</li>
                                <li><b>-15 pts :</b> Chevauchement de <b>20%</b> (10% excédent x 1.5).</li>
                                <li><b>-30 pts (Max) :</b> Chevauchement de <b>30%</b> ou plus.</li>
                            </ul>
                        </td>
                    </tr>
                </tbody>
                </table>
                """
                st.markdown(html_table, unsafe_allow_html=True)

    # --- CARTE ---
    df_dvf_map = df_dvf_kpi
    if afficher_dvf and dvf_type_map != "Tous" and not df_dvf_map.empty:
        df_dvf_map = df_dvf_map[df_dvf_map['type_local'] == dvf_type_map]

    map_obj, l1, l2, l3 = creer_carte_implantation(
        lat_centre=final_lat, lon_centre=final_lon, zone_analyse_geom=zone_analyse_geom,
        gdf_poi_trouves=gdf_poi_trouves, gdf_socio=gdf_socio_filtre, colonne_socio=indicateur,
        nom_indicateur_socio=nom_indicateur,
        gdf_batiments=gdf_batiments_audit if st.session_state.show_batiments else None,
        gdf_inondations=gdf_inond_map, gdf_rga=gdf_rga_map,
        nom_point_central=final_nom, adresse_point_central=final_adresse_str,
        analysis_mode=mode, df_dvf=df_dvf_map if afficher_dvf else None, dvf_type_filtre=dvf_type_map,
        mode_affichage_dvf=mode_visu_map,
        gdf_reseau_cannibale=gdf_iso_reseau_visu if mode_cannibale else None
    )
    st_folium(map_obj, width=800, height=350, returned_objects=[])

    # =========================================================
    # ONGLETS THÉMATIQUES
    # =========================================================
    if zone_analyse_geom:
        tab_pop, tab_immo, tab_loco, tab_tech = st.tabs(["🧬 Environnement", "💰 Immobilier", "🚦 Générateurs de Trafic", "🏗️ Risques & Technique"])

        with tab_pop:
            if 'IRIS' in dict_geodatas:
                c_conf, _ = st.columns([2, 3])
                with c_conf:
                    niveau_comp = st.radio("Se comparer à :", ["Département", "Région", "France"], horizontal=True,
                                           key="radio_comp_implantation")
                st.divider()
                col_custom, _ = st.columns([2, 1])
                with col_custom:
                    choix = st.multiselect("Indicateurs",
                                           ["Revenus", "Jeunes", "Actifs", "Seniors", "Cadres", "Ouvriers", "Familles",
                                            "Retraités"], default=["Revenus", "Jeunes", "Actifs", "Seniors", "Cadres"],
                                           key="radar_sel")
                if choix:
                    df_rad, nom_ref = calculer_comparatif_radar(dict_geodatas['IRIS'], zone_analyse_geom,
                                                                metriques_demandees=choix, df_communes_ref=df_communes,
                                                                niveau_comparaison=niveau_comp)
                    if df_rad is not None and not df_rad.empty:
                        c_radar, c_kpi = st.columns([1.5, 1])
                        with c_radar:
                            fig = go.Figure()
                            fig.add_trace(go.Scatterpolar(r=[100] * len(df_rad), theta=df_rad['Metrique'],
                                                          name=f"Ref ({nom_ref})", line_color='gray'))
                            fig.add_trace(
                                go.Scatterpolar(r=df_rad['Indice_100'], theta=df_rad['Metrique'], fill='toself',
                                                name='Zone', line_color='#B8860B'))
                            st.plotly_chart(fig, use_container_width=True)
                        with c_kpi:
                            st.markdown("#### Positionnement")
                            for _, row in df_rad.iterrows():
                                delta = row['Indice_100'] - 100
                                if abs(delta) > 5:
                                    icon = "🟢" if delta > 0 else "🔴"
                                    st.metric(label=f"{icon} {row['Metrique']}", value=f"{row['Zone']:.0f}",
                                              delta=f"{delta:+.0f} pts")

        with tab_immo:
            if not df_dvf_zone.empty:
                st.markdown("#### 🏠 Dynamique Immobilière")
                c_filter, _ = st.columns([1, 3])
                with c_filter:
                    types_dispo = df_dvf_zone['type_local'].unique()
                    choix_type = st.multiselect("Types:", types_dispo, default=types_dispo, key="multi_type_immo")

                if choix_type:
                    df_filtered_zone = df_dvf_zone[df_dvf_zone['type_local'].isin(choix_type)]
                    df_filtered_kpi = df_dvf_kpi[df_dvf_kpi['type_local'].isin(choix_type)]

                    if not df_filtered_kpi.empty:
                        summary = df_filtered_kpi.groupby('type_local').agg(
                            {'valeur_fonciere': 'count', 'prix_m2': 'median'}).reset_index()
                        cols_kpi = st.columns(len(summary))
                        for idx, row in summary.iterrows():
                            with cols_kpi[idx]: st.metric(row['type_local'], f"{row['prix_m2']:,.0f} €/m²",
                                                          f"{row['valeur_fonciere']} ventes (2 ans)")

                    # Graphique Tendance
                    if not df_filtered_zone.empty:
                        try:
                            df_trend = df_filtered_zone.groupby([pd.Grouper(key='date_mutation', freq='Q')]).agg(
                                {'prix_m2': 'median'}).reset_index()
                            fig_combo = px.line(df_trend, x='date_mutation', y='prix_m2',
                                                title="Tendance Prix m² (Trimestriel)")
                            st.plotly_chart(fig_combo, use_container_width=True)
                        except:
                            pass
            else:
                st.info("Pas de données DVF disponibles.")# --- ONGLET GÉNÉRATEURS DE TRAFIC (Design Robuste) ---# --- ONGLET GÉNÉRATEURS DE TRAFIC (Affichage Précis) ---

        with tab_loco:
            st.markdown("#### 🚦 Pôles d'Attraction")

            with st.spinner("Analyse des flux..."):
                df_loco, score_trafic = analyser_locomotives(zone_analyse_geom)

            if not df_loco.empty:
                # 1. CALCULS & LOGIQUE
                # On récupère la ligne du "Moteur Principal"
                row_top = df_loco.sort_values("Impact Trafic", ascending=False).iloc[0]
                top_cat = row_top['Catégorie']

                # ASTUCE : On récupère le 1er nom dans la liste des exemples pour être précis
                # Ex: "Gare de Cesson, Gare de Savigny" -> On prend "Gare de Cesson"
                top_name = row_top['Exemples'].split(',')[0] if row_top['Exemples'] else top_cat

                # Définition du profil (Texte propre sans émoji)
                if score_trafic > 80:
                    txt_profil = "Hub à Fort Trafic"
                    type_alert = "error"    # Rouge
                    icon_alert = "🔥"
                elif score_trafic > 40:
                    txt_profil = "Zone de Destination"
                    type_alert = "success"  # Vert
                    icon_alert = "✅"
                else:
                    txt_profil = "Zone de Passage (Flux Modéré)"
                    type_alert = "info"     # Bleu (plus neutre que orange)
                    icon_alert = "ℹ️"

                # 2. AFFICHAGE BANDEAU (Metric + Context)

                # Ligne 1 : Les Chiffres et le Nom Précis
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.metric("Score Flux", f"{score_trafic}", help="Indice d'attractivité sur 100")
                with c2:
                    # On affiche la Catégorie ET le Nom précis en dessous
                    st.metric("Moteur Principal", top_cat, delta=top_name)

                # Ligne 2 : Le Verdict Visuel (Propre)
                if type_alert == "error":
                    st.error(f"**Verdict : {txt_profil}**", icon=icon_alert)
                elif type_alert == "success":
                    st.success(f"**Verdict : {txt_profil}**", icon=icon_alert)
                else:
                    st.info(f"**Verdict : {txt_profil}**", icon=icon_alert)

                st.markdown("---")

                # 3. GRAPHIQUE LEADERBOARD
                fig_bar = px.bar(
                    df_loco,
                    x="Impact Trafic",
                    y="Catégorie",
                    orientation='h',
                    text="Nombre",
                    color="Impact Trafic",
                    color_continuous_scale="Blues", # Bleu plus pro que Orange
                    title="Répartition de l'impact par catégorie"
                )
                fig_bar.update_layout(
                    yaxis={'categoryorder':'total ascending'},
                    plot_bgcolor='rgba(0,0,0,0)',
                    xaxis_title="Points d'impact",
                    yaxis_title="",
                    height=250,
                    margin=dict(l=0, r=0, t=30, b=0)
                )
                fig_bar.update_traces(textposition='outside')
                st.plotly_chart(fig_bar, use_container_width=True)

                # 4. TABLEAU DÉTAILLÉ (Avec les noms précis)
                with st.expander("Voir le détail des enseignes/lieux détectés"):
                    st.dataframe(
                        df_loco[['Catégorie', 'Nombre', 'Exemples']],
                        use_container_width=True,
                        hide_index=True
                    )

            else:
                st.info("📉 Aucun générateur de trafic majeur détecté.")
                st.caption("La zone semble purement résidentielle ou isolée.")# --- ONGLET RISQUES & TECHNIQUE (Labels Corrigés) ---
with tab_tech:
            # =========================================================
            # 1. HISTORIQUE CATNAT (Juridique)
            # =========================================================
            st.subheader("📜 Historique CatNat (Commune)")
            code_insee, nom_com = None, "Inconnue"
            if 'final_lat' in locals() and final_lat:
                code_insee, nom_com = get_code_insee_lat_lon(final_lat, final_lon) #

            if code_insee:
                st.caption(f"Données officielles Ministère Transition Écologique pour : **{nom_com} ({code_insee})**")
                df_catnat = get_historique_catnat(code_insee) #
                if not df_catnat.empty:
                    nb_tot, nb_recent, top_peril = get_stats_sinistralite(df_catnat) #
                    k1, k2, k3 = st.columns(3)
                    k1.metric("Arrêtés Total", nb_tot)
                    k2.metric("10 dernières années", nb_recent, delta="Tendance", delta_color="inverse")
                    k3.metric("Risque Majeur", top_peril)
                    with st.expander("Voir le détail chronologique"):
                        st.dataframe(df_catnat, use_container_width=True, hide_index=True)
                else:
                    st.success("Aucun arrêté CatNat recensé sur cette commune.")
            else:
                st.warning("Impossible de récupérer l'historique (Code INSEE non trouvé).")

            st.markdown("---")

            # =========================================================
            # 2. AUDIT TECHNIQUE BÂTIMENTS (OSM) - REVISITÉ
            # =========================================================
            st.subheader("🏗️ Audit Technique des Bâtiments (OSM)")

            # Gestion de l'affichage (Bouton pour éviter calcul inutile)
            if not st.session_state.show_batiments:
                st.info("💡 L'audit détaillé à la parcelle est masqué pour alléger l'affichage.")
                if st.button("Lancer l'Audit Bâtimentaire"):
                    st.session_state.show_batiments = True
                    st.rerun()

            else:
                if not gdf_batiments_audit.empty: #
                    # KPI Global
                    nb_total_bat = len(gdf_batiments_audit)
                    st.markdown(f"**Périmètre analysé :** `{nb_total_bat}` bâtiments détectés dans la zone.")

                    # --- FONCTION LOCALE POUR GRAPHIQUES ---
                    def preparer_graphique_risque(gdf, col_niveau):
                        """Génère un Bar Chart avec 0 forcé et chiffres lisibles"""
                        # Ordre et Couleurs fixes
                        cats_order = ['Aléa fort', 'Aléa moyen', 'Aléa faible', 'Aucun']
                        colors = {
                            'Aléa fort': '#d62728',  # Rouge
                            'Aléa moyen': '#ff7f0e', # Orange
                            'Aléa faible': '#fecb52',# Jaune
                            'Aucun': '#2ca02c'       # Vert
                        }

                        # Comptage intelligent (force les 0)
                        if col_niveau in gdf.columns:
                            counts = gdf[col_niveau].fillna('Aucun').value_counts()
                            # On reindex pour garantir que toutes les clés apparaissent
                            counts = counts.reindex(cats_order, fill_value=0).reset_index()
                            counts.columns = ['Niveau', 'Nombre']
                        else:
                            # Cas de secours si colonne absente
                            counts = pd.DataFrame({'Niveau': cats_order, 'Nombre': [0,0,0,len(gdf)]})

                        # Graphique
                        fig = px.bar(
                            counts,
                            x='Niveau',
                            y='Nombre',
                            color='Niveau',
                            color_discrete_map=colors,
                            text_auto=True, # Affiche la valeur
                            title=None
                        )

                        # Optimisation visuelle (Chiffres au-dessus)
                        fig.update_traces(
                            textposition='outside',
                            cliponaxis=False
                        )
                        fig.update_layout(
                            showlegend=False,
                            margin=dict(t=20, b=0, l=0, r=0),
                            height=250,
                            yaxis=dict(showgrid=True, title=None),
                            xaxis=dict(title=None)
                        )
                        return fig

                    # --- AFFICHAGE CÔTE À CÔTE ---
                    c1, c2 = st.columns(2)

                    with c1:
                        st.markdown("##### 🌊 Inondation")
                        # Vérification de la colonne existante
                        if 'niveau_Inondation' in gdf_batiments_audit.columns:
                             fig_i = preparer_graphique_risque(gdf_batiments_audit, 'niveau_Inondation')
                             st.plotly_chart(fig_i, use_container_width=True)
                        else:
                            st.info("Données inondation non disponibles pour ces bâtiments.")

                    with c2:
                        st.markdown("##### ☀️ Sécheresse (Argiles)")
                        if 'niveau_Argile' in gdf_batiments_audit.columns:
                            fig_r = preparer_graphique_risque(gdf_batiments_audit, 'niveau_Argile')
                            st.plotly_chart(fig_r, use_container_width=True)
                        else:
                             st.info("Données sécheresse non disponibles pour ces bâtiments.")

                else:
                    st.warning("Aucun bâtiment n'a été trouvé dans cette zone géometrique (Zone vide ou erreur OSM).")

            st.markdown("---")

            # =========================================================
            # 3. RISQUES ÉMERGENTS (CLIMAT 2050)
            # =========================================================
            st.subheader("🔥 Risques Émergents (Climat 2050)")
            dist_foret, ratio_veg = 9999, 0

            # Recalcul ou récupération des indicateurs nature
            if zone_analyse_geom:
                bbox = zone_analyse_geom.bounds
                try:
                    dist_foret, ratio_veg = analyser_environnement_naturel(bbox) #
                except:
                    pass

            c_feu, c_chau = st.columns(2)
            with c_feu:
                st.caption("🌲 Risque Incendie (Proximité Forêt)")
                if dist_foret < 2:
                    st.error(f"🚨 **RISQUE MAXIMAL** (Contact)"); st.write(
                        "Le site est **dans** ou **au contact** d'un massif.")
                elif dist_foret < 50:
                    st.error(f"🚨 **ÉLEVÉ** (< 50m)"); st.write(
                        f"Distance lisière : **{dist_foret:.0f} m**"); st.caption(
                        "Débroussaillement obligatoire probable.")
                elif dist_foret < 200:
                    st.warning(f"🟠 **MODÉRÉ** (< 200m)"); st.write(f"Distance lisière : **{dist_foret:.0f} m**")
                elif dist_foret == 9999:
                    st.info("Données non disponibles.")
                else:
                    st.success(f"✅ **FAIBLE**"); st.write("Pas de massif forestier immédiat.")

            with c_chau:
                st.caption("🌡️ Confort Thermique")
                st.metric("Taux de Végétalisation", f"{ratio_veg:.1f}%")
                val_prog = min(max(ratio_veg / 100, 0.0), 1.0)
                if ratio_veg < 10:
                    st.progress(val_prog, "Zone minérale (Risque ICU fort)")
                elif ratio_veg < 40:
                    st.progress(val_prog, "Zone mixte")
                else:
                    st.progress(val_prog, "Ilot de fraîcheur potentiel")

            # =========================================================
            # 4. NOTE MÉTHODOLOGIQUE
            # =========================================================
            with st.expander("ℹ️ Note Méthodologique (Sources & Définitions)"):
                st.caption(
                    "**1. Historique CatNat :** Source officielle API GASPAR (Géorisques).\n"
                    "**2. Inondation & Sécheresse :** Croisement spatial avec les cartes réglementaires (TRI/RGA).\n"
                    "**3. Incendie :** Calculé sur la base OpenStreetMap (OSM).\n"
                    "**4. Chaleur :** Ratio estimatif surfaces vertes / surfaces totales (OSM)."
                )