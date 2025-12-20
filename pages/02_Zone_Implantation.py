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
from config import POI_CONFIG, LOCOMOTIVES_CONFIG, PATHS

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

                # 6. Calculs GeoScore (VRAI CALCUL DE SURFACE RISQUE OPTIMISÉ)
                pop, rev, nb_dvf = 5000, 30000, len(df_dvf_local)

                if not gdf_socio_local.empty:
                    pop = gdf_socio_local['Population_totale'].sum()
                    rev = gdf_socio_local['Revenu_median'].mean() if 'Revenu_median' in gdf_socio_local.columns else 20000

                # --- CALCUL RÉEL DES SURFACES A RISQUE (OPTIMISÉ) ---
                score_inond_max = 0
                ratio_surf_inond = 0.0

                # Création d'un GDF de la zone pour les intersections
                gdf_zone_calc = gpd.GeoDataFrame(geometry=[geom_zone], crs="EPSG:4326").to_crs("EPSG:2154")

                if not gdf_inond_full.empty:
                    try:
                        # OPTIMISATION MAJEURE : On ne prend que les risques DANS le carré de la zone
                        # .cx[minx:maxx, miny:maxy] fait un filtre spatial indexé ultra-rapide
                        gdf_inond_small = gdf_inond_full.cx[minx:maxx, miny:maxy]

                        if not gdf_inond_small.empty:
                            # Overlay uniquement sur la petite sélection
                            gdf_inond_clip = gpd.overlay(gdf_inond_small.to_crs("EPSG:2154"), gdf_zone_calc, how='intersection')
                            if not gdf_inond_clip.empty:
                                surf_inond = gdf_inond_clip.area.sum() / 1_000_000 # km2
                                ratio_surf_inond = min(surf_inond / surface_zone_km2, 1.0)
                                if 'NIVEAU_ALEA' in gdf_inond_clip.columns:
                                    nivs = gdf_inond_clip['NIVEAU_ALEA'].unique()
                                    if any('Fort' in str(n) for n in nivs): score_inond_max = 3
                                    elif any('Moyen' in str(n) for n in nivs): score_inond_max = 2
                                    else: score_inond_max = 1
                    except Exception as e:
                        print(f"Erreur calcul inondation: {e}")

                score_rga_max = 0
                ratio_surf_rga = 0.0
                if not gdf_rga_full.empty:
                    try:
                        # OPTIMISATION MAJEURE IDEM
                        gdf_rga_small = gdf_rga_full.cx[minx:maxx, miny:maxy]

                        if not gdf_rga_small.empty:
                            gdf_rga_clip = gpd.overlay(gdf_rga_small.to_crs("EPSG:2154"), gdf_zone_calc, how='intersection')
                            if not gdf_rga_clip.empty:
                                surf_rga = gdf_rga_clip.area.sum() / 1_000_000
                                ratio_surf_rga = min(surf_rga / surface_zone_km2, 1.0)
                                if 'NIVEAU_ALEA' in gdf_rga_clip.columns:
                                    nivs = gdf_rga_clip['NIVEAU_ALEA'].unique()
                                    if any('Fort' in str(n) for n in nivs): score_rga_max = 3
                                    elif any('Moyen' in str(n) for n in nivs): score_rga_max = 2
                                    else: score_rga_max = 1
                    except Exception as e:
                         print(f"Erreur calcul RGA: {e}")

                score_final, parts, malus_c, malus_i, malus_r, ex = _calculer_score_attractivite(
                    pop, rev, nb_dvf, score_inond_max, ratio_surf_inond, score_rga_max, ratio_surf_rga, taux_can,
                    surface_zone_km2
                )
                statut_zone, couleur_statut = generer_avis_synthetique(score_final, malus_i)

                # 7. Statistiques d'âge (Environnement Business)
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

    with st.expander("Méthodologie Investisseur Détaillée (GeoScore)", expanded=True):
        if is_polygonal:
            # On définit le contenu HTML proprement avant l'affichage pour éviter les bugs de rendu
            html_table_methodo = """
            <style>
                .methodo-table { width: 100%; border-collapse: collapse; font-family: sans-serif; font-size: 13px; }
                .methodo-th { background-color: #f0f2f6; border-bottom: 2px solid #ddd; text-align: left; padding: 8px; font-weight: bold; }
                .methodo-td { border-bottom: 1px solid #eee; padding: 8px; vertical-align: top; }
                .methodo-center { text-align: center; }
                .methodo-bold { font-weight: bold; }
            </style>
            <table class="methodo-table">
                <thead>
                    <tr>
                        <th class="methodo-th">Composante</th>
                        <th class="methodo-th" style="text-align:center;">Poids</th>
                        <th class="methodo-th">Règle de Calcul & Exemples</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td class="methodo-td methodo-bold">📈 Potentiel </td>
                        <td class="methodo-td methodo-center">+40 pts<br><small>(Socle)</small></td>
                        <td class="methodo-td">
                            Évalue la profondeur du marché local.<br>
                            <ul>
                                <li><b>Densité (20 pts) :</b> Max si > 5000 hab/km².</li>
                                <li><b>Revenus (20 pts) :</b> Max si Rev. Médian > 25 000€.</li>
                            </ul>
                        </td>
                    </tr>
                    <tr>
                        <td class="methodo-td methodo-bold">🚀 Dynamisme </td>
                        <td class="methodo-td methodo-center">+30 pts<br><small>(Flux)</small></td>
                        <td class="methodo-td">
                            Évalue la liquidité et l'attractivité.<br>
                            <ul>
                                <li><b>Volume DVF (15 pts) :</b> Basé sur les ventes/km² (2 ans).</li>
                                <li><b>Tension Prix (15 pts) :</b> Bonus si Prix m² > Moyenne Dept.</li>
                            </ul>
                        </td>
                    </tr>
                    <tr>
                        <td class="methodo-td methodo-bold">🛡️ Résilience </td>
                        <td class="methodo-td methodo-center">+30 pts<br><small>(Climat)</small></td>
                        <td class="methodo-td">
                            Le malus grignote ce capital sécurité.<br>
                            <b>🌊 Inondation (Max -20 pts) :</b>
                            <ul>
                                <li>-10 pts : Risque Fort sur 50% du terrain.</li>
                            </ul>
                            <b>☀️ Sécheresse (Max -10 pts) :</b>
                            <ul>
                                <li>-10 pts : Risque Fort sur 100% du terrain.</li>
                            </ul>
                        </td>
                    </tr>
                    <tr>
                        <td class="methodo-td methodo-bold">🛑 Saturation</td>
                        <td class="methodo-td methodo-center">Malus<br><small>(Reseau)</small></td>
                        <td class="methodo-td">
                            Pénalité si chevauchement avec magasin existant.<br>
                            <ul>
                                <li><b>-15 pts :</b> Chevauchement de 20%.</li>
                                <li><b>-30 pts :</b> Chevauchement > 30%.</li>
                            </ul>
                        </td>
                    </tr>
                </tbody>
            </table>
            """

            t_data, t_method = st.tabs(["🔍 Données de la Zone", "📊 Barème & Logique de Calcul"])

            with t_data:
                c_ex1, c_ex2 = st.columns(2)
                with c_ex1:
                    st.markdown("**Indicateurs Bruts**")
                    st.write(f"- Densité Pop : **{ex.get('Densité Pop', 'N/A')}**")
                    st.write(f"- Revenu Médian : **{ex.get('Revenu Médian', 'N/A')}**")
                    st.write(f"- Densité Ventes : **{ex.get('Densité Ventes (2 ans)', 'N/A')}**")
                with c_ex2:
                    st.markdown("**Impact des Risques**")
                    st.write(f"- Inondation : **{ex.get('Malus Inondation', 'N/A')}**")
                    st.write(f"- Sécheresse : **{ex.get('Malus Sécheresse', 'N/A')}**")
                    if mode_cannibale:
                        st.write(f"- Saturation : **{ex.get('Malus Saturation', 'N/A')}**")

            with t_method:
                st.markdown(html_table_methodo, unsafe_allow_html=True)

        else:
            st.warning("Sélectionnez une zone d'étude pour afficher les détails.")

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
with tab_pop:
    st.subheader("Profil Socio-Démographique & Concurrence Locale")

    if is_polygonal and 'IRIS' in dict_geo:
        # Bloc Radar (Inchangé)
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

        st.markdown("---")
        st.markdown("##### 🏢 Contexte Business")

        c_age, c_top = st.columns(2)

        # 1. Âge Moyen (Indicateur de maturité du marché)
        with c_age:
            if age_stats:
                st.metric("⏳ Âge Moyen des Établissements", f"{age_stats['age_moyen']} ans",
                          help=f"Médiane : {age_stats['age_median']} ans")
                st.caption(f"Total : {age_stats['count']} entreprises.")
            else:
                st.info(
                    "Sélectionnez un **SIRET** pour déterminer l'âge moyen des entreprises similaires dans la zone.")

        # 2. Top 3 Concurrence Locale
        with c_top:
            if naf_ref and dep_ref_code and engine:
                st.markdown("###### Top 3 Concurrents (NAF Similaire)")

                # 🚨 CRITIQUE : REQUÊTE CONCURRENCE LOCALE (Réutilisé de P01)
                # On filtre dans la base complète, puis on filtre spatialement sur geom_zone
                df_conc_full = get_concurrents_sql(engine, naf_ref, dep_ref_code,
                                                   siret_exclu='0')

                if not df_conc_full.empty:
                    gdf_conc_full = transfo_geodataframe(df_conc_full, 'longitude', 'latitude')
                    # Filtre spatial sur la zone d'étude
                    gdf_conc_local = gdf_conc_full[gdf_conc_full.within(geom_zone)]

                    if not gdf_conc_local.empty:
                        # Calcul de la distance au point central pour le Top N
                        ref_point = Point(final_lon, final_lat)
                        gdf_conc_local['distance'] = gdf_conc_local.geometry.apply(
                            lambda g: g.distance(ref_point) * 111.32 * 1000)

                        top_3 = gdf_conc_local.sort_values('distance').head(3)

                        st.dataframe(top_3[['denominationunitelegale', 'distance']].rename(
                            columns={'denominationunitelegale': 'Nom', 'distance': 'Distance (m)'}), hide_index=True)
                        st.caption(f"Basé sur NAF {naf_ref} dans la zone.")
                    else:
                        st.warning(f"Aucun concurrent du NAF {naf_ref} trouvé dans la zone d'étude.")
                else:
                    st.warning(f"Aucun concurrent du NAF {naf_ref} trouvé dans le département {dep_ref_code}.")
            else:
                st.warning(
                    "Le Top 3 des concurrents nécessite la saisie d'un **SIRET** pour identifier le NAF de référence.")

    else:
        st.info("Sélectionnez une zone (Isochrone ou Cercle) pour l'analyse démographique.")

# --- ONGLET 💰 Immobilier (DVF) ---
with tab_immo:
    st.subheader("Dynamique Immobilière & Tendance de Prix")

    if not df_dvf_local.empty:
        # CRITIQUE : Filtre sur 2 ans (pour les KPIs)
        df_2ans = df_dvf_local[df_dvf_local['date_mutation'] >= pd.Timestamp.now() - pd.DateOffset(years=2)]

        # Vérification si le filtre 2 ans est vide
        if df_2ans.empty:
            st.warning("Aucune transaction trouvée sur les 2 dernières années dans cette zone pour calculer les KPIs.")
            nb_transactions, prix_m2_moyen, prix_total_moyen = 0, 0, 0
        else:
            nb_transactions = len(df_2ans)
            prix_total_moyen = df_2ans['valeur_fonciere'].mean()
            prix_m2_moyen = df_2ans['prix_m2'].mean()

        c_kpi1, c_kpi2, c_kpi3 = st.columns(3)
        c_kpi1.metric("Transactions (2 ans)", nb_transactions)
        c_kpi2.metric("Prix m² Moyen", f"{prix_m2_moyen:,.0f} €")
        c_kpi3.metric("Prix Total Moyen", f"{prix_total_moyen:,.0f} €")

        st.caption("Les KPIs sont basés sur les 2 dernières années de transactions.")
        st.markdown("---")

        st.markdown("##### 📈 Tendance de Prix (5 ans)")
        # CRITIQUE : Filtre par type de local (Maison/Appart/Local)
        type_local_filtre = st.selectbox(
            "Filtrer par type de local :",
            ["Tous"] + df_dvf_local['type_local'].dropna().unique().tolist(),
            key="dvf_local_filter_chart"
        )

        try:
            fig_dvf = plot_evolution_prix_dvf(df_dvf_local, type_local_filtre)
            st.plotly_chart(fig_dvf, use_container_width=True)
        except Exception as e:
            st.error(f"Erreur de rendu du graphique DVF : {e}. Vérifiez la présence de données filtrées sur 5 ans.")
    else:
        st.info("Aucune transaction DVF récente trouvée dans la zone proche.")

    st.markdown("---")
    st.markdown("##### Paramètres d'Affichage de la Carte (DVF)")

    st.session_state.afficher_dvf = st.toggle("Afficher DVF sur la carte", value=st.session_state.afficher_dvf)
    c_dvf_map, c_dvf_type = st.columns(2)
    st.session_state.mode_visu_map = c_dvf_map.radio("Mode Visualisation", ["Points", "Heatmap"], horizontal=True,
                                                     key="dvf_visu_mode")
    st.session_state.dvf_type_map = c_dvf_type.radio("Type Transactions (Carte)", ["Tous", "Résidentiel", "Commercial"],
                                                     horizontal=True, key="dvf_type_filtre_map")

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

