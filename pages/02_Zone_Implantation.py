# Fichier: pages/02_Zone_Implantation.py (RÉÉCRITURE INTÉGRALE ET VÉRIFIÉE)
import streamlit as st
import pandas as pd
import geopandas as gpd
import plotly.graph_objects as go
import plotly.express as px
from shapely.geometry import Point, shape
from streamlit_folium import st_folium
import numpy as np

# --- IMPORTS NOUVELLE ARCHITECTURE ---
from backend.database import connect_to_db
from backend.data_loaders import (
    charger_communes, charger_donnees_iris_socio,
    charger_zones_risques, charger_donnees_dvf
)
from backend.queries_siren import get_concurrents_sql, \
    calculer_stats_anciennete
from backend.calculators import (
    preparer_donnees_socio, calculer_cannibalisation,
    auditer_risque_batiments, calculer_comparatif_radar,
    _calculer_score_attractivite, generer_avis_synthetique
)
from frontend.components import (
    sidebar_filtres_socio, sidebar_filtres_poi, sidebar_filtres_reseau,
    sidebar_filtres_batiments, sidebar_filtres_risques, selection_point_central
)
from frontend.maps import (
    creer_carte_implantation,
    _ajouter_couche_dvf_points
)
from frontend.charts import plot_radar_comparatif, plot_evolution_prix_dvf, plot_repartition_risques, \
    plot_locomotives_histogram
from utils.geo_tools import (
    calculer_isochrone_api, rechercher_poi_overpass,
    rechercher_batiments_osm, get_code_insee_lat_lon, get_historique_catnat,
    analyser_environnement_naturel, projeter_climat_2050, extraire_ville_depuis_adresse,
    transfo_geodataframe
)
from config import POI_CONFIG, PATHS

# --- CONFIG ---
st.title("📍 Diagnostic Territorial & Risques")
engine = connect_to_db()


# --- BLOC DE CHARGEMENT SÉCURISÉ ---
@st.cache_data(show_spinner="Chargement des référentiels...")
def load_and_prepare_data():
    try:
        df_communes = charger_communes()
        df_dvf = charger_donnees_dvf()
        if not isinstance(df_dvf, pd.DataFrame): df_dvf = pd.DataFrame()
        gdf_inond_full = charger_zones_risques("INONDATION")
        gdf_rga_full = charger_zones_risques("RGA")
        gdf_iris = charger_donnees_iris_socio()
        dict_geo = preparer_donnees_socio(gdf_iris, df_communes)

        return df_communes, df_dvf, gdf_inond_full, gdf_rga_full, dict_geo
    except Exception as e:
        st.error(f"Échec critique du chargement des données statiques: {e}")
        return pd.DataFrame(), pd.DataFrame(), gpd.GeoDataFrame(), gpd.GeoDataFrame(), {}


df_communes, df_dvf_full, gdf_inond_full, gdf_rga_full, dict_geo = load_and_prepare_data()

# Initialisation des variables d'état UI
if 'afficher_dvf' not in st.session_state: st.session_state.afficher_dvf = False
if 'dvf_type_map' not in st.session_state: st.session_state.dvf_type_map = "Tous"
if 'mode_visu_map' not in st.session_state: st.session_state.mode_visu_map = "Points"
if 'dvf_local_filter' not in st.session_state: st.session_state.dvf_local_filter = "Tous"

# --- SIDEBAR (MISE EN FORME UX CORRIGÉE) ---
with st.sidebar:
    st.header("🎛️ Paramètres de la Carte")

    # --- AJOUT DIAGNOSTIC ---
    debug_climat = st.toggle("🛠️ Debug Climat", value=False)
    if debug_climat:
        st.error("🕵️‍♂️ ANALYSE FICHIER CLIMAT")
        try:
            # Lecture directe sans cache pour voir le vrai fichier
            df_clim_debug = pd.read_parquet(PATHS["CLIMAT_2050"])
            st.write(f"Lignes : {len(df_clim_debug)}")
            st.write("Colonnes détectées :")
            st.write(df_clim_debug.columns.tolist())
            st.write("Aperçu (5 premières lignes) :")
            st.dataframe(df_clim_debug.head(1000))
        except Exception as e:
            st.error(f"Impossible de lire le fichier : {e}")
    # ------------------------

    # BLOC 1 : Socio, POI et Risques (Regroupés dans un conteneur comme P01)
    with st.container(border=True):
        # 1. Socio
        gdf_socio_full, col_socio, lbl_socio, maille = sidebar_filtres_socio(dict_geo)
        st.divider()

        # 2. POI
        pois_selected = sidebar_filtres_poi()
        st.divider()

        # 3. Audit & Risques (Spécifique P02 mais intégré au style P01)
        st.markdown("### 🏗️ Audit & Risques")

        # Filtre Bâtiments
        show_batiments, surf_min, surf_max = sidebar_filtres_batiments()

        # Filtres Risques (Appels spécifiques P02 conservés pour la granularité)
        show_inond, reg_inond, dep_inond = sidebar_filtres_risques(df_communes, "Inondation", gdf_inond_full)
        show_rga, reg_rga, dep_rga = sidebar_filtres_risques(df_communes, "Sécheresse (RGA)", gdf_rga_full)

    st.divider()

    # BLOC 2 : Cannibalisation (Conteneur séparé pour bien distinguer)
    with st.container(border=True):
        st.markdown("### 📉 Analyse Réseau")
        mode_cannibale, gdf_reseau_client, nom_enseigne_reseau, rayon_search = sidebar_filtres_reseau()

# --- INPUT CENTRAL ---
target = selection_point_central(engine)

# --- INIT DES VARIABLES DE RÉSULTAT ---
final_lat, final_lon = None, None
geom_zone = None
surface_zone_km2 = 0.1
taux_can = 0
gdf_iso_reseau_visu = gpd.GeoDataFrame()
gdf_poi = gpd.GeoDataFrame()  # POI filtrés par zone
gdf_socio_local = gpd.GeoDataFrame()  # Socio filtré par zone
gdf_bats = gpd.GeoDataFrame()
df_dvf_local = pd.DataFrame()
final_nom, final_adresse_str = "Point d'intérêt", "N/A"
is_polygonal = False
naf_ref = None
dep_ref_code = None
age_stats = None

# --- VARIABLES AJOUTÉES POUR ÉVITER LE CRASH ---
score_final = 0
statut_zone = "En attente"  # Initialisation par défaut
couleur_statut = "gray"     # Initialisation par défaut
parts = {}                  # Pour éviter crash sur parts.get()
malus_c = 0                 # Pour éviter crash sur malus_c
malus_i = 0
malus_r = 0
ex = {}                     # Pour éviter crash sur ex.get()

if target and target.get("valeur"):

    valeur_data = target["valeur"]
    lat, lon = valeur_data.get("latitude"), valeur_data.get("longitude")

    if lat and lon:
        final_lat, final_lon = float(lat), float(lon)
        mode, radius = target['mode'], target['radius']

        final_nom = valeur_data.get("denominationunitelegale", f"Point {final_lat:.4f}")
        final_adresse_str = valeur_data.get("adresse", "Manuel")

        # Détermination du NAF et Département de référence
        if target["source"] == "SIREN/SIRET":
            naf_ref = valeur_data.get("activiteprincipaleetablissement")
            dep_ref_code = valeur_data.get("numero_dep")

        # --- CALCUL ZONE (Isochrone / Cercle) ---
        with st.spinner(f"Calcul de la zone d'analyse ({mode})..."):
            try:
                if mode == 'Isochrones':
                    # Temps par défaut à 10 minutes (600s)
                    geo_iso = calculer_isochrone_api(final_lon, final_lat,radius)
                    geom_zone = shape(geo_iso['geometry']) if geo_iso else None
                elif mode == "Cercle d'influence":
                    p = gpd.GeoDataFrame(geometry=[Point(final_lon, final_lat)], crs="EPSG:4326")
                    zone_l93 = p.to_crs("EPSG:2154").buffer(radius).iloc[0]
                    geom_zone = \
                        gpd.GeoDataFrame(geometry=[zone_l93], crs="EPSG:2154").to_crs("EPSG:4326").geometry.iloc[0]
            except Exception:
                geom_zone = None

            if geom_zone and geom_zone.geom_type in ['Polygon', 'MultiPolygon']:

                is_polygonal = True
                gdf_zone_l93 = gpd.GeoDataFrame(geometry=[geom_zone], crs="EPSG:4326").to_crs("EPSG:2154")
                surface_zone_km2 = gdf_zone_l93.area.iloc[0] / 1_000_000
                bbox = geom_zone.bounds

                # 1. POI (Recherche + Filtre Spatial + Enrichissement Categorie)
                if pois_selected:
                    list_gdf_poi = [rechercher_poi_overpass(bbox, POI_CONFIG[c]['tags']).assign(categorie=c) for c in
                                    pois_selected]
                    res = [g for g in list_gdf_poi if not g.empty]
                    if res:
                        gdf_poi_brut = pd.concat(res, ignore_index=True)
                        # --- CORRECTION V2 : Filtre spatial POI sur geom_zone ---
                        gdf_poi = gdf_poi_brut[gdf_poi_brut.within(geom_zone)].copy()

                # 2. Socio-Démo (Filtre Spatial)
                if gdf_socio_full is not None and col_socio is not None:
                    # --- CORRECTION V2 : Filtre spatial Socio sur geom_zone ---
                    gdf_zone_analyse = gpd.GeoDataFrame({'geometry': [geom_zone]}, crs="EPSG:4326")
                    gdf_socio_local = gpd.sjoin(gdf_socio_full, gdf_zone_analyse, how="inner", predicate="intersects")
                    # Nettoyage si sjoin ajoute des colonnes inutiles
                    gdf_socio_local = gdf_socio_local.drop(columns=['index_right'], errors='ignore')

                # 3. Bâtiments & Risques (Audit)
                minx, miny, maxx, maxy = geom_zone.bounds

                if show_batiments:
                    raw_bats = rechercher_batiments_osm(bbox)
                    if not raw_bats.empty:
                        # --- CORRECTION : APPLICATION DU FILTRE SURFACE ICI ---
                        # On ne garde que les bâtiments dans la fourchette demandée (ex: 100 à 150m²)
                        raw_bats = raw_bats[
                            (raw_bats['surface_m2'] >= surf_min) &
                            (raw_bats['surface_m2'] <= surf_max)
                        ].copy()

                        if not raw_bats.empty:
                            gdf_bats_temp = auditer_risque_batiments(raw_bats, gdf_inond_full, "Inondation")
                            gdf_bats = auditer_risque_batiments(gdf_bats_temp, gdf_rga_full, "Argile")
                            gdf_bats = gdf_bats[gdf_bats.intersects(geom_zone)].copy()
                        else:
                            gdf_bats = gpd.GeoDataFrame()
                    else:
                        gdf_bats = gpd.GeoDataFrame()

                # 3. Bâtiments & Risques (Audit)
                # OPTIMISATION : On définit d'abord la boite englobante (bbox) pour filtrer AVANT de calculer
                minx, miny, maxx, maxy = geom_zone.bounds

                if show_batiments:
                    raw_bats = rechercher_batiments_osm(bbox)
                    if not raw_bats.empty:
                        gdf_bats_temp = auditer_risque_batiments(raw_bats, gdf_inond_full, "Inondation")
                        gdf_bats = auditer_risque_batiments(gdf_bats_temp, gdf_rga_full, "Argile")
                        # CORRECTION : 'intersects' est plus tolérant que 'within' pour les bâtiments en bordure
                        gdf_bats = gdf_bats[gdf_bats.intersects(geom_zone)].copy()

                # 4. Cannibalisation
                if mode_cannibale and not gdf_reseau_client.empty:
                    taux_can, gdf_iso_reseau_visu = calculer_cannibalisation(geom_zone, gdf_reseau_client)

                # 5. Immobilier (Filtre spatial STRICT : Intersection Géométrique)
                # On filtre d'abord large (carré) pour la performance
                df_dvf_temp = df_dvf_full[
                    (df_dvf_full.latitude.between(miny, maxy)) &
                    (df_dvf_full.longitude.between(minx, maxx))
                ].copy()

                # Puis on filtre FIN (Geopandas : within zone)
                if not df_dvf_temp.empty:
                    gdf_dvf_temp = gpd.GeoDataFrame(
                        df_dvf_temp,
                        geometry=gpd.points_from_xy(df_dvf_temp.longitude, df_dvf_temp.latitude),
                        crs="EPSG:4326"
                    )
                    df_dvf_local = gpd.sjoin(gdf_dvf_temp, gpd.GeoDataFrame(geometry=[geom_zone], crs="EPSG:4326"), how="inner", predicate="within")
                    df_dvf_local = pd.DataFrame(df_dvf_local.drop(columns=['geometry', 'index_right'], errors='ignore'))
                else:
                    df_dvf_local = pd.DataFrame()

                # 6. Calculs GeoScore & Risques Pondérés
                pop = gdf_socio_local['Population_totale'].sum() if not gdf_socio_local.empty else 5000
                rev = gdf_socio_local['Revenu_median'].mean() if not gdf_socio_local.empty and 'Revenu_median' in gdf_socio_local.columns else 20000
                nb_dvf = len(df_dvf_local)

                # --- FONCTION HELPER CALCUL SURFACE ---
                def analyser_repartition_risque(gdf_full, geometry_zone, surface_zone_km2, minx, miny, maxx, maxy):
                    """Retourne un dict {'Fort': 0.x, 'Moyen': 0.x, 'Faible': 0.x, 'Aucun': 0.x}"""
                    stats = {"Fort": 0.0, "Moyen": 0.0, "Faible": 0.0, "Aucun": 1.0}
                    if gdf_full.empty: return stats

                    try:
                        # 1. Filtre Spatial Rapide (Index)
                        gdf_small = gdf_full.cx[minx:maxx, miny:maxy]
                        if gdf_small.empty: return stats

                        # 2. Découpage Précis (Overlay)
                        gdf_zone_calc = gpd.GeoDataFrame(geometry=[geometry_zone], crs="EPSG:4326").to_crs("EPSG:2154")
                        gdf_clip = gpd.overlay(gdf_small.to_crs("EPSG:2154"), gdf_zone_calc, how='intersection')

                        if gdf_clip.empty: return stats

                        # 3. Somme des surfaces par niveau
                        total_risk_pct = 0.0

                        if 'NIVEAU_ALEA' in gdf_clip.columns:
                            for idx, row in gdf_clip.iterrows():
                                # Calcul surface du morceau en km2
                                area_pct = (row.geometry.area / 1_000_000) / surface_zone_km2
                                level = str(row['NIVEAU_ALEA']).lower()

                                if 'fort' in level: stats["Fort"] += area_pct
                                elif 'moyen' in level: stats["Moyen"] += area_pct
                                elif 'faible' in level: stats["Faible"] += area_pct
                                # Sinon on ignore ou on compte en faible par défaut

                        # Normalisation (Au cas où superposition géométrique > 100%)
                        sum_risks = stats["Fort"] + stats["Moyen"] + stats["Faible"]
                        if sum_risks > 1.0:
                            stats["Fort"] /= sum_risks
                            stats["Moyen"] /= sum_risks
                            stats["Faible"] /= sum_risks
                            stats["Aucun"] = 0.0
                        else:
                            stats["Aucun"] = 1.0 - sum_risks

                    except Exception as e:
                        print(f"Erreur calcul surface risque: {e}")

                    return stats

                # CALCUL DES REPARTITIONS
                stats_inond = analyser_repartition_risque(gdf_inond_full, geom_zone, surface_zone_km2, minx, miny, maxx, maxy)
                stats_rga = analyser_repartition_risque(gdf_rga_full, geom_zone, surface_zone_km2, minx, miny, maxx, maxy)

                # APPEL CALCULATEUR (Nouvelle Signature)
                score_final, parts, malus_c, malus_i, malus_r, ex = _calculer_score_attractivite(
                    pop, rev, nb_dvf,
                    stats_inond, stats_rga, # On passe les dicts complets
                    taux_can, surface_zone_km2
                )

                statut_zone, couleur_statut = generer_avis_synthetique(score_final, malus_i)

                # 7. Ancienneté
                if naf_ref and dep_ref_code:
                    age_stats = calculer_stats_anciennete(engine, naf_ref, "Département", dep_ref_code)

            else:
                score_final, statut_zone, couleur_statut = 0, "Point sélectionné (Pas d'analyse de zone)", "info"

# --- VISUALISATION DES DONNÉES ---
st.markdown("---")

# 1. AFFICHAGE GEO SCORE
with st.container():
    st.markdown("#### 🏆 GeoScore")

    col_kpi, col_avis = st.columns([1, 2])
    with col_kpi:
        st.metric("Score Global", f"{score_final}/100")
    with col_avis:
        if couleur_statut == "green":
            st.success(f"**Verdict : {statut_zone}**")
        elif couleur_statut == "orange":
            st.warning(f"**Verdict : {statut_zone}**")
        elif couleur_statut == "red":
            st.error(f"**Verdict : {statut_zone}**")
        else:
            st.info(f"**{statut_zone}**")

    # PROGRESS BARS
    if is_polygonal:
        st.caption("Décomposition Facteurs Clés :")
        k1, k2, k3 = st.columns(3)
        k1.progress(min(parts.get('Potentiel', 0) / 40, 1.0), f"📈 Potentiel ({parts.get('Potentiel', 0):.1f} pts)")
        k2.progress(min(parts.get('Dynamisme', 0) / 30, 1.0), f"🚀 Dynamisme ({parts.get('Dynamisme', 0):.1f} pts)")
        k3.progress(min(parts.get('Résilience', 0) / 30, 1.0), f"🛡️ Résilience ({parts.get('Résilience', 0):.1f} pts)")
        if mode_cannibale:
            st.progress(min(taux_can / 100, 1.0), f"🛑 Saturation Réseau ({taux_can:.1f}%)")

    # CRITIQUE : NOTE MÉTHODOLOGIQUE DÉTAILLÉE (BIEN PRÉSENTÉE)
    st.markdown("---")
    st.markdown("##### ℹ️ Note Méthodologique & Détails du GeoScore")

    # Bloc Méthodologie V6 (CORRIGÉ & STABILISÉ)
    with st.expander("ℹ️ Comprendre le calcul de votre GeoScore", expanded=False):
        if is_polygonal:
            t_resume, t_detail = st.tabs(["📝 Synthèse Notation", "📖 Guide Méthodologique"])

            # 1. TAB SYNTHÈSE (Tableau de notes)
            with t_resume:
                # ÉTAPE 1 : Le CSS (Style) dans une chaîne brute sans f-string pour éviter les bugs
                css_style = """
                    <style>
                        .geo-table {border-collapse: collapse; width: 100%; font-family: sans-serif; font-size: 14px;}
                        .geo-table td {border-bottom: 1px solid #e0e0e0; padding: 10px 8px; vertical-align: middle;}
                        .geo-table th {border-bottom: 2px solid #333; font-weight: bold; padding: 12px 8px; text-align: left; background-color: #f8f9fa; color: #333;}
                        .geo-header {background-color: #f1f3f4; font-weight: bold; color: #1a73e8; text-transform: uppercase; font-size: 12px; letter-spacing: 0.5px;}
                        .score-pos {color: #188038; font-weight: bold; background-color: #e6f4ea; padding: 4px 8px; border-radius: 4px; display: inline-block;}
                        .score-neg {color: #d93025; font-weight: bold; background-color: #fce8e6; padding: 4px 8px; border-radius: 4px; display: inline-block;}
                        .val-mono {font-family: monospace; color: #555; font-size: 13px;}
                    </style>
                    """

                # ÉTAPE 2 : Le HTML (Contenu) avec f-string pour insérer les variables
                html_content = f"""
                    <table class="geo-table">
                    <thead>
                      <tr>
                        <th>Critère</th>
                        <th>Mesure sur Zone</th>
                        <th>Impact Score</th>
                        <th>Objectif / Seuil</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr class="geo-header"><td colspan="4">📈 Pilier 1 : Potentiel (40 pts)</td></tr>
                      <tr>
                        <td>Densité Population</td>
                        <td class="val-mono">{ex['Densité']['val']}</td>
                        <td><span class="score-pos">+{ex['Densité']['note']}</span></td>
                        <td>Cible : {ex['Densité']['cible']}</td>
                      </tr>
                      <tr>
                        <td>Pouvoir d'Achat</td>
                        <td class="val-mono">{ex['Revenus']['val']}</td>
                        <td><span class="score-pos">+{ex['Revenus']['note']}</span></td>
                        <td>Cible : {ex['Revenus']['cible']}</td>
                      </tr>

                      <tr class="geo-header"><td colspan="4">🚀 Pilier 2 : Dynamisme (30 pts)</td></tr>
                      <tr>
                        <td>Intensité Transactions</td>
                        <td class="val-mono">{ex['Ventes']['val']}</td>
                        <td><span class="score-pos">+{ex['Ventes']['note']}</span></td>
                        <td>Cible : {ex['Ventes']['cible']}</td>
                      </tr>

                      <tr class="geo-header"><td colspan="4">🛡️ Pilier 3 : Résilience (Capital 30 pts)</td></tr>
                      <tr>
                        <td>🌊 Inondation</td>
                        <td class="val-mono">{ex['Inondation']['val']}</td>
                        <td><span class="score-neg">{ex['Inondation']['malus']}</span></td>
                        <td><i>Pondération Surface</i></td>
                      </tr>
                      <tr>
                        <td>☀️ Sécheresse</td>
                        <td class="val-mono">{ex['Secheresse']['val']}</td>
                        <td><span class="score-neg">{ex['Secheresse']['malus']}</span></td>
                        <td><i>Pondération Surface</i></td>
                      </tr>

                      <tr style="height:15px; border:none;"><td colspan="4" style="border:none;"></td></tr>
                      <tr style="background-color:#fff5f5; border-left:4px solid #d93025;">
                        <td>🛑 <b>Malus Saturation</b></td>
                        <td class="val-mono">{ex['Saturation']['val']}</td>
                        <td><span class="score-neg">{ex['Saturation']['malus']}</span></td>
                        <td>Seuil tolérance : 10%</td>
                      </tr>
                    </tbody>
                    </table>
                    """

                # Rendu combiné
                st.markdown(css_style + html_content, unsafe_allow_html=True)

            # 2. TAB LOGIQUE (Visuelle & Détaillée)
            with t_detail:
                # ATTENTION : La chaîne HTML ci-dessous est volontairement collée à gauche.
                # Ne rajoutez PAS d'espaces devant les balises <div>, sinon le rendu plantera.
                html_guide_content = """
<div style="font-family: sans-serif; color: #333;">
    <div style="margin-bottom: 20px; padding: 15px; background: #e8f0fe; border-left: 5px solid #1a73e8; border-radius: 4px;">
        <h4 style="color: #1a73e8; margin: 0 0 5px 0;">🧮 Principe de Calcul</h4>
        <p style="margin: 0; font-size: 14px; line-height: 1.5;">
            Le GeoScore est un indice de performance sur <b>100 points</b>. <br>
            Il additionne deux forces positives (le marché) et soustrait les risques d'un capital résilience initial.
        </p>
    </div>
    <div style="display: flex; gap: 15px; flex-wrap: wrap;">
        <div style="flex: 1; min-width: 280px; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="background: #f1f8e9; padding: 10px 15px; border-bottom: 1px solid #c5e1a5;">
                <h5 style="margin: 0; color: #2e7d32; font-size: 15px;">📈 1. Potentiel (40 pts)</h5>
            </div>
            <div style="padding: 15px; font-size: 13px;">
                <p style="margin-top:0;"><b>Objectif :</b> Mesurer la profondeur du marché.</p>
                <ul style="padding-left: 20px; margin-bottom: 0; color: #555;">
                    <li style="margin-bottom: 8px;"><b>Densité (20 pts) :</b> Note proportionnelle à la densité brute.<br>
                        <span style="color: #888; font-size: 12px;">➔ 20/20 si > 4 000 hab/km².</span>
                    </li>
                    <li><b>Revenus (20 pts) :</b> Note proportionnelle au niveau de vie.<br>
                        <span style="color: #888; font-size: 12px;">➔ 20/20 si > 30 000 €/an.</span>
                    </li>
                </ul>
            </div>
        </div>
        <div style="flex: 1; min-width: 280px; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="background: #fff8e1; padding: 10px 15px; border-bottom: 1px solid #ffe082;">
                <h5 style="margin: 0; color: #f9a825; font-size: 15px;">🚀 2. Dynamisme (30 pts)</h5>
            </div>
            <div style="padding: 15px; font-size: 13px;">
                <p style="margin-top:0;"><b>Objectif :</b> Valider la liquidité de l'actif.</p>
                <ul style="padding-left: 20px; margin-bottom: 0; color: #555;">
                    <li><b>Transactions (30 pts) :</b> Basé sur le volume de ventes DVF (2 ans).<br>
                        <span style="color: #888; font-size: 12px;">➔ 30/30 si > 15 ventes/km².</span>
                    </li>
                </ul>
                <div style="margin-top: 15px; padding: 8px; background: #fff; border: 1px dashed #ddd; border-radius: 4px; font-size: 12px; color: #666;">
                    <i>💡 Un marché liquide réduit le risque de vacance et facilite la revente.</i>
                </div>
            </div>
        </div>
    </div>
    <div style="margin-top: 15px; border: 1px solid #ffcdd2; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
        <div style="background: #ffebee; padding: 10px 15px; border-bottom: 1px solid #ef9a9a;">
            <h5 style="margin: 0; color: #c62828; font-size: 15px;">🛡️ 3. Résilience & Risques (Capital 30 pts)</h5>
        </div>
        <div style="padding: 15px; font-size: 13px;">
            <div style="display: flex; gap: 20px; flex-wrap: wrap;">
                <div style="flex: 1; min-width: 200px;">
                    <p style="margin-top: 0; font-weight: bold; color: #333;">Mécanisme de Malus Pondéré :</p>
                    <p style="color: #555;">Vous débutez avec <b>30/30</b>. Chaque m² exposé à un aléa réduit ce score proportionnellement à sa surface.</p>
                </div>
                <div style="flex: 1; min-width: 180px; background: #fff; padding: 10px; border-radius: 6px; border: 1px solid #f0f0f0;">
                    <strong style="color: #0d47a1; display: block; margin-bottom: 5px;">🌊 Inondation (Max -20)</strong>
                    <table style="width: 100%; font-size: 12px; color: #555;">
                        <tr><td>Fort</td><td style="text-align: right; color: #d32f2f; font-weight: bold;">-20 pts</td></tr>
                        <tr><td>Moyen</td><td style="text-align: right; color: #f57c00; font-weight: bold;">-10 pts</td></tr>
                        <tr><td>Faible</td><td style="text-align: right; color: #fbc02d; font-weight: bold;">-5 pts</td></tr>
                    </table>
                </div>
                <div style="flex: 1; min-width: 180px; background: #fff; padding: 10px; border-radius: 6px; border: 1px solid #f0f0f0;">
                    <strong style="color: #e65100; display: block; margin-bottom: 5px;">☀️ Sécheresse (Max -15)</strong>
                    <table style="width: 100%; font-size: 12px; color: #555;">
                        <tr><td>Fort</td><td style="text-align: right; color: #d32f2f; font-weight: bold;">-15 pts</td></tr>
                        <tr><td>Moyen</td><td style="text-align: right; color: #f57c00; font-weight: bold;">-8 pts</td></tr>
                        <tr><td>Faible</td><td style="text-align: right; color: #fbc02d; font-weight: bold;">-3 pts</td></tr>
                    </table>
                </div>
            </div>
        </div>
    </div>
</div>
"""
                st.markdown(html_guide_content, unsafe_allow_html=True)
st.markdown("---")

# 2. CARTE INTERACTIVE
st.subheader("Cartographie")

afficher_dvf_global = st.session_state.afficher_dvf
df_dvf_a_afficher = df_dvf_local if afficher_dvf_global else None

# Préparation des GDF Risques MAP (DÉCOUPE STRICTE POUR VISUEL PROPRE)
gdf_inond_map_safe = gpd.GeoDataFrame()
gdf_rga_map_safe = gpd.GeoDataFrame()

if is_polygonal and geom_zone:
    gdf_zone_visu = gpd.GeoDataFrame(geometry=[geom_zone], crs="EPSG:4326")

    # On découpe les risques pour ne garder que ce qui est DANS la zone (Overlay)
    if show_inond and not gdf_inond_full.empty:
        try:
            gdf_inond_map_safe = gpd.overlay(gdf_inond_full.to_crs("EPSG:4326"), gdf_zone_visu, how='intersection')
        except:
            pass

    if show_rga and not gdf_rga_full.empty:
        try:
            gdf_rga_map_safe = gpd.overlay(gdf_rga_full.to_crs("EPSG:4326"), gdf_zone_visu, how='intersection')
        except:
            pass

if final_lat is not None:
    try:
        # Appel modifié pour récupérer la légende socio (cmap_socio)
        m, cmap_socio = creer_carte_implantation(
            final_lat, final_lon, geom_zone,
            gdf_poi_trouves=gdf_poi,
            gdf_socio=gdf_socio_local, colonne_socio=col_socio, nom_indicateur_socio=lbl_socio,
            gdf_batiments=gdf_bats,
            gdf_inondations=gdf_inond_map_safe,
            gdf_rga=gdf_rga_map_safe,
            nom_point_central=final_nom, adresse_point_central=final_adresse_str,
            df_dvf=df_dvf_a_afficher, mode_affichage_dvf=st.session_state.mode_visu_map,
            dvf_type_filtre=st.session_state.dvf_type_map,
            gdf_reseau_cannibale=gdf_iso_reseau_visu
        )

        # MISE EN PAGE : 3/4 Carte | 1/4 Légende Latérale
        c_map, c_legend = st.columns([3, 1])

        with c_map:
            st_folium(m, height=500, use_container_width=True,
                      key="folium_map_p02_stable",
                      returned_objects=[])

        with c_legend:
            st.markdown("#### Légende")
            with st.container(border=True):

                # A. Légende Socio-Démographique (si active)
                if cmap_socio and col_socio:
                    st.caption(f"📊 {lbl_socio}")
                    # Barre de dégradé visuelle
                    st.markdown(
                        '<div style="background: linear-gradient(to right, #ffffcc, #fd8d3c, #800026); width: 100%; height: 10px; border-radius: 5px; margin-bottom:5px;"></div>',
                        unsafe_allow_html=True)
                    # Bornes Min/Max récupérées de l'objet cmap
                    st.caption(f"Min: {cmap_socio.vmin:,.0f} | Max: {cmap_socio.vmax:,.0f}")
                    st.divider()

                # B. Légende Risques (si active)
                if show_inond:
                    st.caption("🌊 Inondation")
                    st.markdown(
                        """<div style="font-size:13px; line-height:1.5; margin-bottom:10px;">
                        <span style="color:#08306b;">■</span> Aléa Fort<br>
                        <span style="color:#2171b5;">■</span> Aléa Moyen<br>
                        <span style="color:#6baed6;">■</span> Aléa Faible
                        </div>""", unsafe_allow_html=True)

                if show_rga:
                    st.caption("☀️ Sécheresse")
                    st.markdown(
                        """<div style="font-size:13px; line-height:1.5;">
                        <span style="color:#5D4037;">■</span> Aléa Fort<br>
                        <span style="color:#8D6E63;">■</span> Aléa Moyen<br>
                        <span style="color:#D7CCC8;">■</span> Aléa Faible
                        </div>""", unsafe_allow_html=True)

                # Message si rien n'est affiché
                if not (cmap_socio and col_socio) and not show_inond and not show_rga:
                    st.info("Aucun calque actif.")

    except Exception as e:
        st.error(f"Erreur critique de rendu cartographique : {e}. Affichage du point central par défaut.")
        st.map(pd.DataFrame({'lat': [final_lat], 'lon': [final_lon]}), size=10)

# --- ONGLETS THÉMATIQUES ---
st.markdown("---")

tab_pop, tab_immo, tab_loco, tab_tech = st.tabs([
    "🧬 Environnement",
    "💰 Immobilier",
    "🚦 Générateurs de Trafic",
    "🏗️ Risques & Technique"
])

# --- ONGLET 🧬 Environnement (Socio / Radar / Top Concurrence) ---
# --- ONGLET 🧬 Environnement (Socio / Radar / Top Concurrence) ---
with tab_pop:
    st.subheader("Profil Socio-Démographique & Concurrence Locale")

    if is_polygonal and 'IRIS' in dict_geo:
        # --- 1. RADAR (INCHANGÉ) ---
        st.markdown("##### 📡 Radar de Positionnement")
        c_conf, _ = st.columns([2, 3])
        with c_conf:
            niveau_comp = st.radio("Se comparer à :", ["Département", "Région", "France"], horizontal=True,
                                   key="radio_comp_implantation")
        stats, ref_nom = calculer_comparatif_radar(dict_geo['IRIS'], geom_zone, df_communes_ref=df_communes,
                                                   niveau_comparaison=niveau_comp)
        try:
            if stats is not None:
                st.plotly_chart(plot_radar_comparatif(stats, ref_nom), use_container_width=True)
            else:
                st.warning("Données insuffisantes pour le calcul radar.")
        except Exception:
            st.error("Erreur de rendu du Radar Plotly.")

        # --- 2. CONTEXTE BUSINESS (NOUVELLE VERSION FORMATÉE) ---
        st.markdown("---")
        st.subheader("🏢 Contexte Business & Concurrence")

        if naf_ref:
            # Récupération du libellé d'activité (Sécurisé)
            libelle_act = valeur_data.get('denominationunitelegale', "Activité Similaire")
            # Si le libellé est le nom de l'entreprise, on essaie de trouver le libellé NAF, sinon on laisse vide
            sous_titre_naf = f"Code : {naf_ref}"

            # --- CALCULS ---
            age_moyen_str = "N/A"
            nb_total_concs = 0
            df_concurrents = pd.DataFrame()

            try:
                # Requête SQL directe pour avoir les données fraîches
                df_conc_full = get_concurrents_sql(engine, naf_ref, dep_ref_code, siret_exclu='0')

                if not df_conc_full.empty:
                    # Filtre spatial strict (Geopandas)
                    gdf_conc_full = transfo_geodataframe(df_conc_full, 'longitude', 'latitude')
                    gdf_concurrents = gdf_conc_full[gdf_conc_full.within(geom_zone)].copy()
                    nb_total_concs = len(gdf_concurrents)

                    if nb_total_concs > 0:
                        df_concurrents = gdf_concurrents

                        # Calcul Âge Moyen
                        col_date = next((c for c in df_concurrents.columns if c.lower() == 'datecreationetablissement'),
                                        None)
                        if col_date:
                            now = pd.Timestamp.now()
                            df_concurrents[col_date] = pd.to_datetime(df_concurrents[col_date], errors='coerce')
                            df_concurrents['Age'] = (now - df_concurrents[col_date]).dt.days / 365.25
                            val_age = df_concurrents['Age'].mean()
                            age_moyen_str = f"{val_age:.1f} ans"

                        # Calcul Distances
                        df_concurrents = df_concurrents.to_crs("EPSG:2154")
                        point_clic_proj = \
                        gpd.GeoSeries([Point(final_lon, final_lat)], crs="EPSG:4326").to_crs("EPSG:2154").iloc[0]
                        df_concurrents['dist_m'] = df_concurrents.geometry.distance(point_clic_proj)
                        df_concurrents = df_concurrents.sort_values('dist_m')

            except Exception:
                pass

            # --- AFFICHAGE "CARTES" (HTML) AU LIEU DE METRIC (POUR ÉVITER LES "...") ---
            k1, k2, k3 = st.columns(3)


            # Fonction pour générer une carte KPI propre
            def kpi_card(titre, valeur, sous_titre, couleur_bord="#ddd"):
                return f"""
                <div style="background-color:white; border:1px solid {couleur_bord}; border-radius:8px; padding:15px; text-align:center; height:100%; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <div style="color:#666; font-size:12px; font-weight:bold; text-transform:uppercase; margin-bottom:5px;">{titre}</div>
                    <div style="color:#333; font-size:20px; font-weight:bold; margin-bottom:5px;">{valeur}</div>
                    <div style="color:#888; font-size:11px; line-height:1.2;">{sous_titre}</div>
                </div>
                """


            with k1:
                st.markdown(kpi_card("🎯 Cible Analysée", f"NAF {naf_ref}", "Filtre Activité Principale", "#4A90E2"),
                            unsafe_allow_html=True)
            with k2:
                st.markdown(
                    kpi_card("🏪 Densité Locale", f"{nb_total_concs} Établ.", "Concurrents dans la zone", "#50E3C2"),
                    unsafe_allow_html=True)
            with k3:
                st.markdown(kpi_card("⏳ Pérennité", age_moyen_str, "Ancienneté Moyenne", "#F5A623"),
                            unsafe_allow_html=True)

            st.write("")  # Petit espace

            # --- LISTE DES VOISINS ---
            st.markdown("##### 📍 Les 3 Voisins les plus proches (Même activité)")

            if not df_concurrents.empty:
                top_3 = df_concurrents.head(3)
                cols = st.columns(3)
                for idx, (index, row) in enumerate(top_3.iterrows()):
                    with cols[idx]:
                        dist_val = row['dist_m']
                        if dist_val < 5:
                            dist_txt = "📍 C'est ici (0 m)"
                            badge_bg = "#28a745"
                        elif dist_val < 1000:
                            dist_txt = f"📏 {dist_val:.0f} m"
                            badge_bg = "#6c757d"
                        else:
                            dist_txt = f"🚗 {dist_val / 1000:.1f} km"
                            badge_bg = "#007bff"

                        nom_ent = row.get('denominationunitelegale', row.get('Denomination', 'Nom inconnu'))
                        if pd.isna(nom_ent): nom_ent = "Nom Non Communiqué"
                        siret_ent = row.get('siret', row.get('Siret', 'N/A'))

                        st.markdown(f"""
                        <div style="border:1px solid #eee; border-radius:8px; padding:12px; background-color:#fcfcfc; height:100%;">
                            <div style="font-weight:bold; font-size:13px; color:#333; margin-bottom:4px; line-height:1.4;">
                                {nom_ent}
                            </div>
                            <div style="font-size:11px; color:#999; margin-bottom:8px;">SIRET : {siret_ent}</div>
                            <span style="background-color:{badge_bg}; color:white; padding:4px 8px; border-radius:12px; font-size:10px; font-weight:bold;">
                                {dist_txt}
                            </span>
                        </div>
                        """, unsafe_allow_html=True)
            else:
                st.info("Aucun concurrent direct détecté dans cette zone.")

            st.caption(
                "ℹ️ *Analyse basée uniquement sur les entreprises présentes à l'intérieur de la géométrie dessinée.*")

        else:
            # Cas où on n'a pas sélectionné via SIRET
            if target.get("source") != "SIREN/SIRET":
                st.info(
                    "💡 L'analyse concurrentielle nécessite de sélectionner un point via son SIRET (Barre latérale).")
            else:
                st.warning("Code NAF non détecté pour cet établissement.")

    else:
        st.info("Sélectionnez une zone (Isochrone ou Cercle) pour l'analyse.")

# --- ONGLET 💰 Immobilier (DVF) ---
with tab_immo:
    st.subheader("Dynamique Immobilière & Tendance de Prix")

    if not df_dvf_local.empty:

        # --- 1. FILTRE GLOBAL (KPIs + GRAPHIQUE) ---
        # On définit les options intelligentes
        types_dispos = sorted(df_dvf_local['type_local'].dropna().unique().tolist())
        options_filtre = ["Tous", "Résidentiel", "Commercial"]
        # On ajoute les types spécifiques s'ils ne sont pas déjà couverts par les catégories macro
        options_filtre += [t for t in types_dispos if
                           t not in ["Maison", "Appartement", "Local industriel. commercial ou assimilé"]]

        filtre_immo = st.selectbox(
            "🔎 Filtrer l'analyse par type de bien :",
            options_filtre,
            index=0,
            key="dvf_global_filter"
        )

        # --- 2. APPLICATION DU FILTRE (CENTRALISÉE) ---
        # On filtre le DataFrame UNE SEULE FOIS pour tout l'onglet
        df_filtered = df_dvf_local.copy()

        if filtre_immo == "Résidentiel":
            df_filtered = df_filtered[df_filtered['type_local'].isin(['Maison', 'Appartement'])]
        elif filtre_immo == "Commercial":
            df_filtered = df_filtered[df_filtered['type_local'].str.contains('Local', case=False, na=False)]
        elif filtre_immo != "Tous":
            df_filtered = df_filtered[df_filtered['type_local'] == filtre_immo]

        # --- 3. CALCUL DES KPIS (SUR DONNÉES FILTRÉES - 2 ANS) ---
        # On prend les 2 dernières années par rapport à aujourd'hui
        date_ref_kpi = pd.Timestamp.now() - pd.DateOffset(years=2)
        df_kpi_2ans = df_filtered[df_filtered['date_mutation'] >= date_ref_kpi]

        if df_kpi_2ans.empty:
            st.info(f"ℹ️ Aucune transaction '{filtre_immo}' recensée sur les 2 dernières années.")
            c1, c2, c3 = st.columns(3)
            c1.metric("Transactions (2 ans)", "0")
            c2.metric("Prix m² Moyen", "-")
            c3.metric("Prix Total Moyen", "-")
        else:
            nb_transac = len(df_kpi_2ans)
            px_m2 = df_kpi_2ans['prix_m2'].mean()
            px_tot = df_kpi_2ans['valeur_fonciere'].mean()

            c1, c2, c3 = st.columns(3)
            c1.metric("Transactions (2 ans)", nb_transac)
            c2.metric("Prix m² Moyen", f"{px_m2:,.0f} €")
            c3.metric("Prix Total Moyen", f"{px_tot:,.0f} €")

        st.markdown("---")

        # --- 4. GRAPHIQUE INTELLIGENT (Business Rule) ---
        st.markdown(f"##### 📈 Tendance de Prix - {filtre_immo} (5 ans)")

        # Seuil de significativité statistique (ex: 10 ventes sur 5 ans min pour faire un graphe)
        MIN_VENTES_POUR_GRAPHE = 10
        vol_total_hist = len(df_filtered)

        if vol_total_hist < MIN_VENTES_POUR_GRAPHE:
            # Cas : Pas assez de données -> Message Propre
            st.warning(
                f"⚠️ **Données insuffisantes pour dégager une tendance fiable.**\n\n"
                f"Il n'y a eu que **{vol_total_hist} vente(s)** de type '{filtre_immo}' sur la zone historique.\n"
                f"Un minimum de **{MIN_VENTES_POUR_GRAPHE} transactions** est requis pour générer une courbe pertinente."
            )
        else:
            # Cas : Données suffisantes -> Affichage Graphique
            try:
                # Astuce : On passe "Tous" à la fonction de chart car on lui donne déjà un DF filtré (df_filtered)
                # Cela évite que la fonction chart refasse un filtrage strict qui pourrait casser le "Commercial"
                fig_dvf = plot_evolution_prix_dvf(df_filtered, "Tous")

                if fig_dvf:
                    # On personnalise le titre pour refléter le filtre actuel
                    fig_dvf.update_layout(title=f"Évolution {filtre_immo} (Volume & Prix)")
                    st.plotly_chart(fig_dvf, use_container_width=True)
                else:
                    st.warning("Impossible de générer le graphique.")
            except Exception as e:
                st.error(f"Erreur technique graphique : {e}")

        st.markdown("---")

        # --- 5. CONTRÔLES CARTE (Fix Session State conservé) ---
        st.markdown("##### 🗺️ Options de la Carte (DVF)")

        c_check, c_visu, c_type = st.columns([1, 2, 2])

        with c_check:
            st.write("")
            st.write("")
            st.toggle("Afficher Calque", key="afficher_dvf")

        with c_visu:
            st.radio("Style", ["Points", "Heatmap"], horizontal=True, key="mode_visu_map")

        with c_type:
            # Ce filtre reste indépendant pour la carte (car on peut vouloir voir le résidentiel
            # sur la carte tout en analysant le commercial sur les graphiques)
            st.radio("Filtre Carte", ["Tous", "Résidentiel", "Commercial"], horizontal=True, key="dvf_type_map")

    else:
        st.info("Aucune donnée DVF brute disponible dans le périmètre géographique sélectionné.")

# --- ONGLET 🚦 Générateurs de Trafic (Locomotives) ---
with tab_loco:
    if not is_polygonal:
        st.info("Sélectionnez une zone pour analyser les générateurs de trafic.")
    else:
        st.subheader("Pôles d'Attraction (Locomotives)")

        # --- VRAI CALCUL SPATIAL (Plus de dummy data) ---
        from config import LOCOMOTIVES_CONFIG

        loco_results = []
        total_score_flux = 0

        with st.spinner("Analyse des flux réels dans la zone..."):
            # On boucle sur la config pour chercher chaque type de locomotive
            for cat, conf in LOCOMOTIVES_CONFIG.items():
                tags = conf['tags']
                poids = conf['poids']

                # 1. Recherche large (Bbox)
                gdf_tmp = rechercher_poi_overpass(geom_zone.bounds, tags)

                if not gdf_tmp.empty:
                    # 2. Filtre Strict (Dans l'Isochrone)
                    gdf_in_zone = gdf_tmp[gdf_tmp.within(geom_zone)]

                    count = len(gdf_in_zone)
                    if count > 0:
                        # Calcul du score (Poids x Nombre, plafonné pour éviter l'explosion)
                        score_cat = min(count * poids, 30)
                        total_score_flux += score_cat

                        # Récupération des noms pour l'affichage
                        exemples = ", ".join(gdf_in_zone['name'].fillna('Inconnu').head(3).tolist())

                        loco_results.append({
                            "Catégorie": cat,
                            "Nombre": count,
                            "Impact Trafic": score_cat,  # Score relatif
                            "Exemples": exemples
                        })

            # Normalisation du score total sur 100
            score_final_loco = min(total_score_flux, 100)

        if loco_results:
            df_loc = pd.DataFrame(loco_results).sort_values("Impact Trafic", ascending=False)

            c_score, c_chart = st.columns([1, 2])
            with c_score:
                st.metric("Score de Flux", f"{score_final_loco}/100")
                if score_final_loco > 70:
                    st.success("Zone de fort passage")
                elif score_final_loco > 40:
                    st.info("Passage modéré")
                else:
                    st.warning("Zone calme")

            with c_chart:
                fig_loco = px.bar(
                    df_loc, x="Impact Trafic", y="Catégorie", orientation='h',
                    text="Nombre", color="Impact Trafic", title="Contribution au Trafic"
                )
                st.plotly_chart(fig_loco, use_container_width=True)

            st.dataframe(df_loc[['Catégorie', 'Nombre', 'Exemples']], hide_index=True, use_container_width=True)
        else:
            st.warning("📉 Aucun générateur de trafic majeur (Gare, Lycée, Mall...) détecté DANS votre zone.")

# --- ONGLET 🏗️ Risques & Technique ---
with tab_tech:
    st.subheader("Audit et Résilience du Site")

    # 🚨 CRITIQUE : DÉPLACEMENT ET AFFICHAGE DE L'AUDIT BÂTIMENTAIRE
    if show_batiments and is_polygonal:
        st.markdown("##### 🏗️ Audit Technique des Bâtiments (OSM)")

        if not gdf_bats.empty:
            c_a, c_b = st.columns(2)
            try:
                with c_a:
                    st.plotly_chart(
                        plot_repartition_risques(gdf_bats, "niveau_Inondation", "Risque Inondation"),
                        use_container_width=True)
                with c_b:
                    st.plotly_chart(plot_repartition_risques(gdf_bats, "niveau_Argile", "Risque Sécheresse"),
                                    use_container_width=True)
            except Exception:
                st.error("Erreur de rendu des graphiques de répartition des risques.")

            with st.expander("Détail des Bâtiments Audités", expanded=False):
                st.dataframe(gdf_bats.drop(columns='geometry', errors='ignore'))

        else:
            st.info("Aucun bâtiment trouvé dans la zone d'étude (vérifiez les filtres de surface).")

    st.markdown("---")

    # 🚨 CRITIQUE : RESTAURATION DONNÉES DRIAS/CLIMAT 2050
    st.markdown("##### 🔥 Projection Climatique (DRIAS 2050)")

    if final_lat is not None and is_polygonal:
        try:
            projections = projeter_climat_2050(final_lat, final_lon)

            c_r4, c_r8 = st.columns(2)

            with c_r4:
                st.markdown("**RCP 4.5 (Modéré)**")
                st.metric("🌡️ Jours Canicule", f"+{projections['RCP 4.5']['Jours Canicule']} j/an")
                st.metric("🌙 Nuits Tropicales", f"+{projections['RCP 4.5']['Nuits Tropicales']} j/an")

            with c_r8:
                st.markdown("**RCP 8.5 (Pessimiste)**")
                st.metric("🌡️ Jours Canicule", f"+{projections['RCP 8.5']['Jours Canicule']} j/an")
                st.metric("🌙 Nuits Tropicales", f"+{projections['RCP 8.5']['Nuits Tropicales']} j/an")

            # --- AJOUT DE LA NOTE DE LECTURE (SEULE MODIFICATION) ---
            st.info(
                "ℹ️ **Note de lecture :** À l'horizon 2050 (court terme climatique), les scénarios RCP 4.5 et 8.5 ne divergent pas encore fortement. "
                "Il est normal d'observer localement des valeurs très proches, voire ponctuellement supérieures pour le scénario modéré, en raison de la variabilité naturelle des modèles."
            )

        except Exception:
            st.warning("Projections DRIAS/Climat 2050 non disponibles ou erreur de calcul pour ce point.")

    st.markdown("---")

    st.markdown("##### 🌲 Risques Secondaires (OSM)")

    bbox_analysis = geom_zone.bounds if geom_zone else [final_lon - 0.01, final_lat - 0.01, final_lon + 0.01,
                                                        final_lat + 0.01]

    dist_foret, ratio_veg = 9999.0, 0.0
    try:
        dist_foret, ratio_veg = analyser_environnement_naturel(bbox_analysis)
    except Exception:
        pass

    c_feu, c_chau = st.columns(2)
    with c_feu:
        st.caption("🌲 Risque Incendie (Distance Forêt)")
        if dist_foret < 50:
            st.error(f"🚨 RISQUE ÉLEVÉ (< 50m) : {dist_foret:.0f} m")
        else:
            st.success(f"✅ FAIBLE ({dist_foret:.0f} m)")

    with c_chau:
        st.caption("🌡️ Confort Thermique (Ilot de Fraîcheur)")
        st.metric("Taux de Végétalisation", f"{ratio_veg:.1f}%")
        st.progress(min(ratio_veg / 100, 1.0), "Score de végétalisation")

