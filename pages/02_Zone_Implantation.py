# Fichier: pages/02_Zone_Implantation.py

import streamlit as st
import geopandas as gpd
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots  # NOUVEAU POUR LE DUAL AXIS
from streamlit_folium import st_folium
from shapely.geometry import Point, shape

# Imports Métiers
from fonctions_basiques import (
    charger_communes, charger_donnees_iris_socio, charger_coefficients_trafic,
    preparer_donnees_socio, charger_zones_inondables, charger_donnees_rga,
    charger_donnees_dvf, connect_to_db,
    calculer_comparatif_radar, calculer_cannibalisation, auditer_risque_batiments
)
from fonctions_cartographie import (
    creer_carte_implantation, calculer_isochrone_et_cacher,
    rechercher_poi_osm, rechercher_batiments_osm,
    geocoder_adresse_nominatim_ui, transfo_geodataframe,
    analyser_environnement_naturel
)
# APIs État
from fonctions_api import get_code_insee_lat_lon, get_historique_catnat, get_stats_sinistralite

from interface import (
    interface_selection_socio, interface_selection_poi, POI_CONFIG,
    interface_selection_batiments, interface_selection_risques,
    interface_point_interet, interface_filtre_geo_risque
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
    statut, couleur = "", ""
    # Si le malus réel (après pondération surface) dépasse 15 points, c'est grave
    if malus_inond_pondere >= 15:
        statut, couleur = "SITE À RISQUE ÉLEVÉ", "red"
    elif note_globale >= 75:
        statut, couleur = "EMPLACEMENT PREMIUM", "green"
    elif note_globale >= 55:
        statut, couleur = "BON POTENTIEL", "#orange"
    elif note_globale >= 40:
        statut, couleur = "POTENTIEL STANDARD", "A67C00"
    else:
        statut, couleur = "ZONE DÉGRADÉE", "red"
    return statut, couleur


def _calculer_score_attractivite(pop_zone, revenu_zone, nb_ventes_immo,
                                 niveau_inond_max, ratio_surf_inond,
                                 niveau_rga_max, ratio_surf_rga,
                                 taux_cannib, surface_km2):
    """
    Calcule le GeoScore avec pondération surfacique des risques.
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
    # Cible : > 10 transactions/km² sur 2 ans
    s_immo = min(densite_ventes / 10, 1) * 30
    part_dynamisme = s_immo
    score += part_dynamisme

    # 3. RÉSILIENCE CLIMATIQUE (30 pts - Pondérée par la surface)
    # Définition des Malus Max (si 100% de la surface est touchée)
    base_malus_i = 20 if niveau_inond_max == 3 else 10 if niveau_inond_max == 2 else 5 if niveau_inond_max == 1 else 0
    base_malus_r = 10 if niveau_rga_max == 3 else 5 if niveau_rga_max == 2 else 2 if niveau_rga_max == 1 else 0

    # Application du ratio de surface (Proportionnalité)
    # Ex: Si Risque Fort (-20) mais sur 10% de la zone -> Malus effectif = -2
    malus_i_effectif = base_malus_i * ratio_surf_inond
    malus_r_effectif = base_malus_r * ratio_surf_rga

    part_resilience = max(0, 30 - malus_i_effectif - malus_r_effectif)
    score += part_resilience

    # Malus Externe : Saturation
    malus_c = 0
    if taux_cannib > 10:
        malus_c = min((taux_cannib - 10) * 1.5, 30)

    score_final = max(0, score - malus_c)

    explications = {
        "Densité Pop": f"{int(densite_pop)} hab/km²",
        "Revenu Médian": f"{int(revenu_zone)} €",
        "Densité Ventes (2 ans)": f"{densite_ventes:.1f} act./km²",
        "Malus Inondation": f"-{malus_i_effectif:.1f} (sur {ratio_surf_inond:.0%} zone)",
        "Malus Sécheresse": f"-{malus_r_effectif:.1f} (sur {ratio_surf_rga:.0%} zone)",
        "Malus Saturation": f"-{int(malus_c)}"
    }
    parts = {
        "Potentiel": round(part_potentiel, 1),
        "Dynamisme": round(part_dynamisme, 1),
        "Résilience Climatique": round(part_resilience, 1)
    }
    # On retourne aussi le malus inondation effectif pour la couleur du label
    return int(score_final), parts, int(malus_c), malus_i_effectif, malus_r_effectif, explications


def _filtrer_risque_geo(gdf, regions, depts):
    if gdf.empty: return gdf
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
    if 'show_batiments' not in st.session_state: st.session_state.show_batiments = False


    def toggle_bati():
        st.session_state.show_batiments = not st.session_state.show_batiments


    cb_bati = st.checkbox("Afficher Bâtiments (OSM)", value=st.session_state.show_batiments, key="cb_bati_sidebar",
                          on_change=toggle_bati)
    st.session_state.show_batiments = cb_bati

    if st.session_state.show_batiments:
        c1, c2 = st.columns(2)
        surface_min = c1.number_input("Min m²", 0, 10000, 0, step=50)
        surface_max = c2.number_input("Max m²", 0, 100000, 3000, step=100)
    else:
        surface_min, surface_max = 0, 3000

    show_inond = st.checkbox("Afficher Inondations", value=False)
    reg_inond, dep_inond = [], []
    if show_inond: reg_inond, dep_inond = interface_filtre_geo_risque(df_communes, "inond")

    show_rga = st.checkbox("Afficher Sécheresse", value=False)
    reg_rga, dep_rga = [], []
    if show_rga: reg_rga, dep_rga = interface_filtre_geo_risque(df_communes, "rga")

    # 3. Saturation
    st.divider()
    mode_cannibale = st.toggle("Analyse Saturation / Réseau", value=False)
    gdf_reseau_client = gpd.GeoDataFrame()
    if mode_cannibale:
        uploaded_reseau = st.file_uploader("Fichier Réseau (CSV/Excel)", type=["csv", "xlsx"])
        if uploaded_reseau:
            try:
                if uploaded_reseau.name.endswith('.csv'):
                    df_res = pd.read_csv(uploaded_reseau)
                else:
                    df_res = pd.read_excel(uploaded_reseau)
                lat_col = next((c for c in df_res.columns if 'lat' in c.lower()), None)
                lon_col = next((c for c in df_res.columns if 'lon' in c.lower()), None)
                if lat_col and lon_col:
                    gdf_reseau_client = transfo_geodataframe(df_res, lon_col, lat_col)
                    st.success(f"{len(gdf_reseau_client)} points chargés")
            except:
                st.error("Erreur fichier")

    st.divider()

    # 4. Immobilier
    st.markdown("### 🏠 Immobilier")
    afficher_dvf = st.checkbox("Afficher Transactions (Récent)", value=False)
    dvf_type_map = "Tous"
    mode_visu_map = "Points"
    if afficher_dvf:
        dvf_type_map = st.selectbox("Type de bien", ["Tous", "Commerce", "Maison", "Appartement"])
        mode_visu_map = st.selectbox("Style carte", ["Points", "Heatmap"])

# --- PRÉPARATION MAP ---
gdf_inond_map = _filtrer_risque_geo(gdf_inondations_full, reg_inond, dep_inond) if show_inond else gpd.GeoDataFrame()
gdf_rga_map = _filtrer_risque_geo(gdf_rga_full, reg_rga, dep_rga) if show_rga else gpd.GeoDataFrame()

# --- DÉFINITION ZONE ---
result_point_central = interface_point_interet(engine=engine)
final_lat, final_lon = None, None
final_nom, final_adresse_str = None, None
mode, radius = result_point_central['mode'], result_point_central['radius']

if result_point_central['source'] == "Adresse":
    res_geo = geocoder_adresse_nominatim_ui(result_point_central['valeur'])
    if res_geo: final_lat, final_lon, final_nom, final_adresse_str = res_geo['latitude'], res_geo['longitude'], res_geo[
        'denominationunitelegale'], res_geo['adresse']
elif result_point_central['source'] == "Coordonnées":
    if result_point_central['valeur']: final_lat, final_lon, final_nom, final_adresse_str = \
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
    surface_zone_km2 = 0.1  # Sécurité division par zéro

    if mode == 'Isochrones':
        f = calculer_isochrone_et_cacher(final_lon, final_lat, temps_isochrones * 60 * 0.9)
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
    df_dvf_zone = pd.DataFrame()  # Historique Complet (2020-2025)
    df_dvf_kpi = pd.DataFrame()  # Focus KPI (2024-2025)

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
                    if not risques_locaux.empty: gdf_bat_work = auditer_risque_batiments(gdf_bat_work, risques_locaux,
                                                                                         "Inondation", "NIVEAU_ALEA")
                if not gdf_rga_full.empty:
                    risques_locaux_rga = gdf_rga_full.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]]
                    if not risques_locaux_rga.empty: gdf_bat_work = auditer_risque_batiments(gdf_bat_work,
                                                                                             risques_locaux_rga,
                                                                                             "Argile", "NIVEAU_ALEA")

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

        # --- CALCUL RISQUE PONDÉRÉ PAR LA SURFACE ---
        score_inond_max, ratio_surf_inond = 0, 0.0
        score_rga_max, ratio_surf_rga = 0, 0.0

        # Pour le calcul d'aire précis, on projette en Lambert 93 (mètres)
        gdf_zone_l93 = gpd.GeoDataFrame({'geometry': [zone_analyse_geom]}, crs="EPSG:4326").to_crs("EPSG:2154")
        aire_zone_m2 = gdf_zone_l93.area.iloc[0]

        # A. Inondations
        if not gdf_inondations_full.empty:
            # 1. Filtre bbox (pour rapidité)
            xmin, ymin, xmax, ymax = gdf_zone_l93.total_bounds
            # On prend les risques dans la bbox, projetés en L93
            risques_possibles = gdf_inondations_full.cx[zone_analyse_geom.bounds[0]:zone_analyse_geom.bounds[2],
                                zone_analyse_geom.bounds[1]:zone_analyse_geom.bounds[3]]

            if not risques_possibles.empty:
                risques_l93 = risques_possibles.to_crs("EPSG:2154")
                # 2. Intersection précise (Overlay)
                try:
                    intersection = gpd.overlay(gdf_zone_l93, risques_l93, how='intersection')
                    if not intersection.empty:
                        aire_risque = intersection.area.sum()
                        ratio_surf_inond = min(aire_risque / aire_zone_m2, 1.0)

                        # Niveau max
                        risques_trouves = intersection['NIVEAU_ALEA'].unique()
                        if any('fort' in str(s).lower() for s in risques_trouves):
                            score_inond_max = 3
                        elif any('moyen' in str(s).lower() for s in risques_trouves):
                            score_inond_max = 2
                        else:
                            score_inond_max = 1
                except:
                    pass  # Erreur géométrie

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

        taux_can = 0
        if mode_cannibale and not gdf_reseau_client.empty:
            taux_can = calculer_cannibalisation(zone_analyse_geom, gdf_reseau_client)

        score_final, parts, malus_c, malus_i, malus_r, ex = _calculer_score_attractivite(
            pop, rev, len(df_dvf_kpi),
            score_inond_max, ratio_surf_inond,
            score_rga_max, ratio_surf_rga,
            taux_can, surface_zone_km2
        )
        statut_zone, couleur_statut = generer_avis_synthetique(score_final, malus_i)

        col_avis, col_score = st.columns([1.5, 2])
        with col_avis:
            st.metric("GeoScore", f"{score_final}/100")
            if couleur_statut == "green":
                st.success(f"**{statut_zone}**")
            elif couleur_statut == "orange":
                st.warning(f"**{statut_zone}**")
            else:
                st.error(f"**{statut_zone}**")
        with col_score:
            st.caption("Décomposition des Facteurs Clés :")
            c1, c2, c3 = st.columns(3)
            c1.progress(parts['Potentiel'] / 40, f"Potentiel {parts['Potentiel']} pts")
            c2.progress(parts['Dynamisme'] / 30, f"Dynamisme {parts['Dynamisme']} pts")
            c3.progress(parts['Résilience Climatique'] / 30, f"Résilience Clim. {parts['Résilience Climatique']} pts")
            if mode_cannibale: st.progress(min(taux_can / 100, 1.0), f"Saturation {taux_can:.1f}%")

        # --- NOTE MÉTHODOLOGIQUE ---
        with st.expander("ℹ️ Comprendre la notation (Méthodologie Investisseur)"):
            t_data, t_method = st.tabs(["🔍 Données de la Zone", "📊 Barème & Logique"])
            with t_data:
                c_ex1, c_ex2 = st.columns(2)
                with c_ex1:
                    st.markdown("**Indicateurs Bruts**")
                    st.write(f"- Densité Pop : **{ex['Densité Pop']}**")
                    st.write(f"- Revenu Médian : **{ex['Revenu Médian']}**")
                    st.write(f"- Densité Ventes (2 ans) : **{ex['Densité Ventes (2 ans)']}**")
                with c_ex2:
                    st.markdown("**Malus Appliqués (Pondérés par surface)**")
                    st.write(f"- Inondation : **{ex['Malus Inondation']} pts**")
                    st.write(f"- Sécheresse : **{ex['Malus Sécheresse']} pts**")
                    if mode_cannibale: st.write(f"- Saturation Réseau : **{ex['Malus Saturation']} pts**")
            with t_method:
                html_table = """<table style="width:100%; border-collapse: collapse; font-family: sans-serif; font-size: 14px;"><thead><tr style="background-color: #f0f2f6; border-bottom: 2px solid #ddd;"><th style="text-align: left; padding: 10px;">Composante</th><th style="text-align: center; padding: 10px;">Poids</th><th style="text-align: left; padding: 10px;">Logique de Scoring Détaillée</th></tr></thead><tbody><tr style="border-bottom: 1px solid #eee;"><td style="font-weight: bold; padding: 10px;">📈 Potentiel</td><td style="text-align: center; padding: 10px;">40</td><td style="padding: 10px;"><b>Densité (20 pts)</b> : Calcul linéaire. 0 pts à 0 hab/km² ➔ 20 pts à 2500 hab/km².<br><b>Pouvoir d'Achat (20 pts)</b> : Calcul linéaire. 0 pts à 0€ ➔ 20 pts à 28 000€.</td></tr><tr style="border-bottom: 1px solid #eee;"><td style="font-weight: bold; padding: 10px;">🚀 Dynamisme</td><td style="text-align: center; padding: 10px;">30</td><td style="padding: 10px;"><b>Liquidité (30 pts)</b> : Basé sur la densité de transactions DVF.<br>0 pts si inactif ➔ 30 pts si > 10 ventes/km² (Marché fluide).</td></tr><tr><td style="font-weight: bold; padding: 10px;">🛡️ Résilience Climatique</td><td style="text-align: center; padding: 10px;">30</td><td style="padding: 10px;"><b>Capital Technique Initial (30 pts)</b> auquel on soustrait des Malus PONDÉRÉS PAR LA SURFACE :<br><span style="color:#d62728;">●</span> <b>Inondation :</b> Max -20 pts (si 100% surface). Si 10% surface = -2 pts.<br><span style="color:#ff7f0e;">●</span> <b>Sécheresse :</b> Max -10 pts (si 100% surface). Si 50% surface = -5 pts.</td></tr></tbody></table>"""
                st.markdown(html_table, unsafe_allow_html=True)
                st.caption(
                    "*Note : La 'Résilience Climatique' évalue la pérennité physique du site face au changement climatique.*")

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
        mode_affichage_dvf=mode_visu_map
    )
    st_folium(map_obj, width=800, height=500, returned_objects=[])

    # =========================================================
    # ONGLETS THÉMATIQUES COMPLETS
    # =========================================================
    if zone_analyse_geom:
        tab_pop, tab_immo, tab_tech = st.tabs(["🧬 Environnement", "💰 Immobilier", "🏗️ Risques & Technique"])

        with tab_pop:
            if 'IRIS' in dict_geodatas:
                c_conf, c_blank = st.columns([2, 3])
                with c_conf:
                    niveau_comp = st.radio("Se comparer à :", ["Département", "Région", "France"], horizontal=True,
                                           key="radio_comp_implantation")
                st.divider()
                col_presets, col_custom = st.columns([1, 2])
                if "selected_metrics" not in st.session_state: st.session_state.selected_metrics = ["Revenus", "Jeunes",
                                                                                                    "Actifs", "Seniors",
                                                                                                    "Cadres"]
                with col_presets:
                    st.markdown("**Profils**")
                    if st.button("💎 CSP+", use_container_width=True): st.session_state.selected_metrics = ["Revenus",
                                                                                                           "Cadres",
                                                                                                           "Seniors",
                                                                                                           "Retraités"]
                    if st.button("👨‍👩‍👧 Familial", use_container_width=True): st.session_state.selected_metrics = [
                        "Revenus", "Familles", "Jeunes", "Actifs"]
                    if st.button("🏭 Populaire", use_container_width=True): st.session_state.selected_metrics = [
                        "Revenus", "Ouvriers", "Monoparental", "Actifs"]
                with col_custom:
                    choix = st.multiselect("Indicateurs",
                                           ["Revenus", "Jeunes", "Actifs", "Seniors", "Cadres", "Ouvriers", "Familles",
                                            "Retraités"], default=st.session_state.selected_metrics, key="radar_sel")
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
                                    lbl = row['Metrique']
                                    val = row['Zone']
                                    txt_val = f"{val:,.0f} €" if "Revenu" in lbl else f"{val:.1f}%"
                                    st.metric(label=f"{icon} {lbl}", value=txt_val, delta=f"{delta:+.0f} pts")

        # --- ONGLET IMMOBILIER (COMPLET & OPTIMISÉ) ---
        with tab_immo:
            if not df_dvf_zone.empty:
                st.markdown("#### 🏠 Dynamique Immobilière & Commerciale")

                # FILTRES
                c_filter, c_stats = st.columns([1, 3])
                with c_filter:
                    st.markdown("**Filtres Analyse**")
                    types_dispo = df_dvf_zone['type_local'].unique()
                    choix_type = st.multiselect("Types de biens :", types_dispo, default=types_dispo,
                                                key="multi_type_immo")

                if not choix_type:
                    st.warning("⚠️ Veuillez sélectionner au moins un type de bien pour afficher les données.")
                else:
                    # FILTRES APPLIQUÉS
                    df_filtered_zone = df_dvf_zone[df_dvf_zone['type_local'].isin(choix_type)]
                    df_filtered_kpi = df_dvf_kpi[df_dvf_kpi['type_local'].isin(choix_type)]

                    if not df_filtered_zone.empty:
                        # KPI HAUT : Focus 2024-2025
                        st.markdown("##### 📊 Indicateurs Clés (Focus Récent 2024-2025)")

                        summary = df_filtered_kpi.groupby('type_local').agg({
                            'valeur_fonciere': 'count',
                            'prix_m2': 'median',
                            'surface_reelle_bati': 'mean'
                        }).reset_index()
                        summary.columns = ['Type de Bien', 'Volume (2 ans)', 'Prix m² Actuel', 'Surf. Moy']

                        # Comparatif 2021 (Pour Delta)
                        df_old = df_filtered_zone[df_filtered_zone['annee'] <= 2021]
                        summary_old = df_old.groupby('type_local')['prix_m2'].median().reset_index()
                        summary_old.columns = ['Type de Bien', 'Prix m² Ancien']

                        final_summary = pd.merge(summary, summary_old, on='Type de Bien', how='left')

                        cols_kpi = st.columns(max(len(final_summary), 1))
                        for idx, row in final_summary.iterrows():
                            # GESTION DES VALEURS MANQUANTES (NAN / 0)
                            vol = row['Volume (2 ans)']
                            prix_actuel = row['Prix m² Actuel']

                            val_display = "Aucune vente"
                            delta_str = None

                            if vol > 0 and pd.notnull(prix_actuel):
                                val_display = f"{prix_actuel:,.0f} €/m²"
                                prix_ancien = row['Prix m² Ancien']
                                if pd.notnull(prix_ancien) and prix_ancien > 0:
                                    evol = ((prix_actuel - prix_ancien) / prix_ancien) * 100
                                    delta_str = f"{evol:+.1f}% vs 2021"

                            with cols_kpi[idx]:
                                st.metric(
                                    label=row['Type de Bien'],
                                    value=val_display,
                                    delta=delta_str,
                                    help=f"Volume récent : {vol} ventes"
                                )

                        st.divider()

                        # GRAPHIQUES : TOUT L'HISTORIQUE 2020-2025
                        c_g1, c_g2 = st.columns(2)

                        with c_g1:
                            # Histogramme
                            fig_dist = px.histogram(
                                df_filtered_zone, x="prix_m2", color="type_local", nbins=30,
                                title="Distribution Prix m² (Historique 2020-2025)",
                                labels={"prix_m2": "Prix (€/m²)", "type_local": "Type"},
                                opacity=0.7, barmode="overlay",
                                color_discrete_map={"Maison": "#EF553B", "Appartement": "#636EFA",
                                                    "Commerce": "#FFA15A"}
                            )
                            fig_dist.update_layout(yaxis_title="Volume", legend=dict(orientation="h", y=-0.2))
                            st.plotly_chart(fig_dist, use_container_width=True)

                        with c_g2:
                            # GRAPHIQUE COMBO (OPTIMISÉ) : PRIX (Ligne) + VOLUME (Barres)
                            try:
                                df_trend = df_filtered_zone.groupby([pd.Grouper(key='date_mutation', freq='Q')]) \
                                    .agg({'prix_m2': 'median', 'valeur_fonciere': 'count'}).reset_index()

                                fig_combo = make_subplots(specs=[[{"secondary_y": True}]])

                                # Barres (Volume) en fond
                                fig_combo.add_trace(
                                    go.Bar(x=df_trend['date_mutation'], y=df_trend['valeur_fonciere'],
                                           name="Volume Ventes", marker_color='rgba(200, 200, 200, 0.5)'),
                                    secondary_y=False
                                )
                                # Ligne (Prix) devant
                                fig_combo.add_trace(
                                    go.Scatter(x=df_trend['date_mutation'], y=df_trend['prix_m2'],
                                               name="Prix m² Médian", line=dict(color='#B8860B', width=3)),
                                    secondary_y=True
                                )

                                fig_combo.update_layout(
                                    title="Tendance Prix & Volume (2020-2025)",
                                    legend=dict(orientation="h", y=-0.2)
                                )
                                fig_combo.update_yaxes(title_text="Nombre de Ventes", secondary_y=False)
                                fig_combo.update_yaxes(title_text="Prix (€/m²)", secondary_y=True)

                                st.plotly_chart(fig_combo, use_container_width=True)
                            except Exception as e:
                                st.error(f"Erreur graphique tendance : {e}")

                        # NOUVEAU : TABLEAU ÉVOLUTION DÉTAILLÉE PAR ANNÉE
                        st.markdown("---")
                        with st.expander("📈 Voir l'évolution détaillée par Année (Tableau)", expanded=False):
                            stats_evol = df_filtered_zone.groupby(['annee', 'type_local']).agg({
                                'valeur_fonciere': 'count',
                                'prix_m2': 'median'
                            }).reset_index()
                            stats_evol.columns = ['Année', 'Type', 'Volume', 'Prix m² Médian']

                            stats_evol = stats_evol.sort_values(['Type', 'Année'])
                            stats_evol['Évolution %'] = stats_evol.groupby('Type')['Prix m² Médian'].pct_change() * 100

                            st.dataframe(
                                stats_evol,
                                column_config={
                                    "Année": st.column_config.NumberColumn(format="%d"),
                                    "Prix m² Médian": st.column_config.NumberColumn(format="%.0f €"),
                                    "Évolution %": st.column_config.NumberColumn(format="%.1f %%"),
                                },
                                use_container_width=True, hide_index=True
                            )
                    else:
                        st.warning("Aucune transaction trouvée avec ces filtres.")
            else:
                st.info("Pas de données DVF disponibles sur cette zone.")

        with tab_tech:
            # 1. CatNat
            st.subheader("📜 Historique CatNat (Commune)")
            code_insee, nom_com = None, "Inconnue"
            if 'final_lat' in locals(): code_insee, nom_com = get_code_insee_lat_lon(final_lat, final_lon)

            if code_insee:
                st.caption(f"Données officielles Ministère Transition Écologique pour : **{nom_com} ({code_insee})**")
                df_catnat = get_historique_catnat(code_insee)
                if not df_catnat.empty:
                    nb_tot, nb_recent, top_peril = get_stats_sinistralite(df_catnat)
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

            # 2. Audit Bâti
            if not st.session_state.show_batiments:
                st.info("💡 L'audit détaillé à la parcelle est masqué.")
                if st.button("Lancer l'Audit Bâtimentaire"):
                    st.session_state.show_batiments = True
                    st.rerun()

            c1, c2 = st.columns(2)
            cats_order = ['Aléa fort', 'Aléa moyen', 'Aléa faible', 'Aucun']
            ref_cats = pd.DataFrame({'Niveau': cats_order})

            with c1:
                st.subheader("🌊 Inondation")
                if not gdf_batiments_audit.empty:
                    counts = gdf_batiments_audit['niveau_Inondation'].fillna('Aucun').value_counts().reset_index()
                    counts.columns = ['Niveau', 'Nombre']
                    df_final = ref_cats.merge(counts, on='Niveau', how='left').fillna(0)
                    fig_i = px.pie(df_final, values='Nombre', names='Niveau', hole=0.4, color='Niveau',
                                   color_discrete_map={'Aléa fort': '#d62728', 'Aléa moyen': '#ff7f0e',
                                                       'Aléa faible': '#fecb52', 'Aucun': '#2ca02c'})
                    st.plotly_chart(fig_i, use_container_width=True)
                else:
                    st.info("Pas de bâtiments.")

            with c2:
                st.subheader("☀️ Sécheresse (Argiles)")
                if not gdf_batiments_audit.empty:
                    counts = gdf_batiments_audit['niveau_Argile'].fillna('Aucun').value_counts().reset_index()
                    counts.columns = ['Niveau', 'Nombre']
                    df_final = ref_cats.merge(counts, on='Niveau', how='left').fillna(0)
                    fig_r = px.bar(df_final, x='Niveau', y='Nombre', color='Niveau',
                                   color_discrete_map={'Aléa fort': '#d62728', 'Aléa moyen': '#ff7f0e',
                                                       'Aléa faible': '#fecb52', 'Aucun': '#2ca02c'})
                    st.plotly_chart(fig_r, use_container_width=True)
                else:
                    st.info("Pas de bâtiments.")

            # 3. Risques Émergents
            st.markdown("---")
            st.subheader("🔥 Risques Émergents (Climat 2050)")
            dist_foret, ratio_veg = 9999, 0
            if zone_analyse_geom:
                bbox = zone_analyse_geom.bounds
                try:
                    dist_foret, ratio_veg = analyser_environnement_naturel(bbox)
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

            with st.expander("ℹ️ Note Méthodologique (Sources & Définitions)"):
                st.caption(
                    "**1. Historique CatNat :** Source officielle API GASPAR (Géorisques).\n**2. Inondation & Sécheresse :** Croisement spatial avec les cartes réglementaires (TRI/RGA).\n**3. Incendie :** Calculé sur la base OpenStreetMap (OSM).\n**4. Chaleur :** Ratio estimatif surfaces vertes / surfaces totales (OSM).")