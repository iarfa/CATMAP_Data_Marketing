# Fichier: pages/01_Analyse_Concurrence.py (V19 - BASE V15 + ALL REQUESTED FIXES - NO DELETION)

import streamlit as st
import pandas as pd
import geopandas as gpd
from streamlit_folium import st_folium
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from sqlalchemy import text
import folium

# --- IMPORTS ---
from backend.database import connect_to_db
from backend.data_loaders import (
    charger_communes, charger_donnees_iris_socio, charger_zones_risques
)
from backend.queries_siren import (
    get_concurrents_sql, get_etablissement_par_siret, calculer_stats_anciennete
)
from backend.calculators import preparer_donnees_socio, calculer_comparatif_radar
from frontend.components import (
    sidebar_filtres_socio, render_selection_territoire_compact, sidebar_filtres_poi, sidebar_filtres_risques
)
from frontend.maps import creer_carte_concurrence
from frontend.charts import plot_radar_comparatif
from utils.geo_tools import (
    transfo_geodataframe, rechercher_poi_overpass, extraction_adresse_OSM, executer_recherche_osm_masse,
    extraire_ville_depuis_adresse
)
from config import POI_CONFIG


# =============================================================================
# 0. UTILITAIRES SÉCURITÉ & DESIGN
# =============================================================================
def detecter_colonnes_geo(df):
    """Cherche lat/lon (insensible à la casse) pour éviter les crashs."""
    if df is None or df.empty: return None, None
    cols_lower = {c.lower(): c for c in df.columns}

    lon_candidates = ['longitude', 'lon', 'lng', 'long', 'longitude_centre', 'gps_lng', 'x']
    lon_col = next((cols_lower[c] for c in lon_candidates if c in cols_lower), None)

    lat_candidates = ['latitude', 'lat', 'latitude_centre', 'gps_lat', 'y']
    lat_col = next((cols_lower[c] for c in lat_candidates if c in cols_lower), None)

    return lon_col, lat_col


def compter_resultats_sql(engine, code_naf, num_dep, siret_exclu="0"):
    """Compte ultra-rapide avant de charger les données."""
    try:
        siren_exclu = str(siret_exclu)[:9]
        q = text("""
            SELECT COUNT(*) 
            FROM etablissements
            WHERE activiteprincipaleetablissement = :code_naf 
            AND numero_dep = :num_dep 
            AND siren != :siren_exclu;
        """)
        with engine.connect() as conn:
            return conn.execute(q, {"code_naf": code_naf, "num_dep": str(num_dep), "siren_exclu": siren_exclu}).scalar()
    except Exception:
        return -1


def display_kpi_card(title, value, subtext=None, is_active=True):
    """Affiche une carte KPI HTML propre (évite de couper le texte). Ajout gestion opacité."""
    opacity = "1.0" if is_active else "0.5"
    color_val = "#000" if is_active else "#888"
    sub_html = f"<div style='font-size:12px; color:#666; margin-top:4px; line-height:1.2;'>{subtext}</div>" if subtext else ""
    html = f"""
    <div style="background-color: white; padding: 15px; border-radius: 8px; border: 1px solid #e0e0e0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); height: 100%; opacity: {opacity};">
        <div style="font-size: 13px; font-weight: 600; color: #555; text-transform: uppercase; margin-bottom: 5px;">{title}</div>
        <div style="font-size: 20px; font-weight: bold; color: {color_val};">{value}</div>
        {sub_html}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# =============================================================================
# 1. INITIALISATION & AUTO-RÉPARATION DES DONNÉES
# =============================================================================
st.title("📊 Analyse de la Concurrence")

if 'data_loaded' not in st.session_state:
    st.session_state['data_loaded'] = False

if not st.session_state['data_loaded']:
    with st.status("🚀 Démarrage de GeoRisk...", expanded=True) as status:
        st.write("🔌 Connexion Base de Données...")
        engine = connect_to_db()
        st.session_state['engine'] = engine

        st.write("🗺️ Chargement Référentiel Communes...")
        df_communes = charger_communes()

        st.write("👥 Chargement Données Socio-Démographiques...")
        raw_iris = charger_donnees_iris_socio()
        dict_geo = preparer_donnees_socio(raw_iris, df_communes)
        st.session_state['dict_geo'] = dict_geo

        # --- RÉPARATION AUTOMATIQUE DES COORDONNÉES (Fix V12) ---
        lon_check, lat_check = detecter_colonnes_geo(df_communes)

        if (not lon_check or not lat_check) and dict_geo and 'Commune' in dict_geo:
            st.write("🔧 Réparation des coordonnées géographiques...")
            try:
                gdf_shapes = dict_geo['Commune'].copy()

                # Calcul des centres
                gdf_shapes['repair_lon'] = gdf_shapes.geometry.centroid.x
                gdf_shapes['repair_lat'] = gdf_shapes.geometry.centroid.y

                # Jointure
                df_communes['Code_Join'] = df_communes['Code_INSEE'].astype(str).str.zfill(5)
                gdf_shapes['JOIN_KEY'] = gdf_shapes['CODE_COM'].astype(str).str.zfill(5)

                df_merged = df_communes.merge(gdf_shapes[['JOIN_KEY', 'repair_lon', 'repair_lat']], left_on='Code_Join',
                                              right_on='JOIN_KEY', how='left')
                df_merged['longitude'] = df_merged['repair_lon']
                df_merged['latitude'] = df_merged['repair_lat']

                df_communes = df_merged.drop(columns=['Code_Join', 'JOIN_KEY', 'repair_lon', 'repair_lat'],
                                             errors='ignore')
                st.toast("✅ Coordonnées reconstruites.", icon="🛠️")
            except Exception as e:
                st.error(f"Echec réparation: {e}")

        st.session_state['df_communes'] = df_communes
        status.update(label="Chargement terminé !", state="complete", expanded=False)
    st.session_state['data_loaded'] = True

engine = st.session_state.get('engine')
df_communes = st.session_state.get('df_communes')
dict_geo = st.session_state.get('dict_geo')

# =============================================================================
# 2. SIDEBAR
# =============================================================================
with st.sidebar:
    st.header("🎛️ Paramètres de la Carte")

    # Debug Optionnel
    debug_mode = st.toggle("🛠️ Mode Diagnostic", value=False)

    with st.container(border=True):
        # 1. Socio
        gdf_socio_full, col_socio, lbl_socio, maille_socio = sidebar_filtres_socio(dict_geo)

        st.divider()

        # 2. POI
        poi_selectionnes_sidebar = sidebar_filtres_poi()
        st.divider()

        # 3. Risques (Avec Multiselect V11)
        show_risk, types_risk_selected, regions_filtrees, departements_filtres_codes = sidebar_filtres_risques(
            df_communes)


# =============================================================================
# 3. FONCTIONS DE PRÉPARATION
# =============================================================================
def preparer_calques_carte_optimise(nums_deps_zone, geo_communes_df):
    """
    Prépare les couches géographiques. Intègre les correctifs V12 (CRS + Multiselect).
    """
    socio_layer = None
    if gdf_socio_full is not None and nums_deps_zone:
        socio_layer = gdf_socio_full[gdf_socio_full['CODE_DEPT'].isin(nums_deps_zone)]

    inond_layer, rga_layer = gpd.GeoDataFrame(), gpd.GeoDataFrame()

    if show_risk and not geo_communes_df.empty:
        try:
            lon_col, lat_col = detecter_colonnes_geo(geo_communes_df)
            if not lon_col: return socio_layer, inond_layer, rga_layer

            temp_gdf = transfo_geodataframe(geo_communes_df, lon_col, lat_col)
            if temp_gdf.empty: return socio_layer, inond_layer, rga_layer

            minx, miny, maxx, maxy = temp_gdf.unary_union.bounds
            bbox_geo = [minx - 0.1, miny - 0.1, maxx + 0.1, maxy + 0.1]

            with st.spinner("Chargement risques..."):
                raw_inond = charger_zones_risques("INONDATION")
                raw_rga = charger_zones_risques("RGA")

            if types_risk_selected and "Inondation" in types_risk_selected and not raw_inond.empty:
                if raw_inond.crs and raw_inond.crs.to_string() != "EPSG:4326": raw_inond = raw_inond.to_crs("EPSG:4326")
                inond_layer = raw_inond.cx[bbox_geo[0]:bbox_geo[2], bbox_geo[1]:bbox_geo[3]].copy()
                if departements_filtres_codes and 'Num_Dep' in inond_layer.columns:
                    inond_layer = inond_layer[inond_layer['Num_Dep'].isin(departements_filtres_codes)]
                if not inond_layer.empty: inond_layer['geometry'] = inond_layer['geometry'].simplify(0.0001)

            if types_risk_selected and "Sécheresse (RGA)" in types_risk_selected and not raw_rga.empty:
                if raw_rga.crs and raw_rga.crs.to_string() != "EPSG:4326": raw_rga = raw_rga.to_crs("EPSG:4326")
                rga_layer = raw_rga.cx[bbox_geo[0]:bbox_geo[2], bbox_geo[1]:bbox_geo[3]].copy()
                if departements_filtres_codes and 'Num_Dep' in rga_layer.columns:
                    rga_layer = rga_layer[rga_layer['Num_Dep'].isin(departements_filtres_codes)]
                if not rga_layer.empty: rga_layer['geometry'] = rga_layer['geometry'].simplify(0.0001)

        except Exception:
            pass

    return socio_layer, inond_layer, rga_layer


def preparer_poi_pour_carte(geo_communes_df, pois_selectionnes):
    """
    Prépare les POI avec la boucle 'Fix Tout Hopital' (V12) et BBox souple.
    """
    gdf_total = gpd.GeoDataFrame()
    if not pois_selectionnes or geo_communes_df.empty: return gdf_total

    try:
        lon_col, lat_col = detecter_colonnes_geo(geo_communes_df)
        if not lon_col: return gdf_total

        temp_gdf = transfo_geodataframe(geo_communes_df, lon_col, lat_col)
        minx, miny, maxx, maxy = temp_gdf.unary_union.bounds
        bbox_agrandie = [minx - 0.02, miny - 0.02, maxx + 0.02, maxy + 0.02]

        list_gdfs = []
        for cat in pois_selectionnes:
            if cat in POI_CONFIG:
                tags_cat = POI_CONFIG[cat]['tags']
                gdf_cat = rechercher_poi_overpass(bbox_agrandie, tags_cat)
                if not gdf_cat.empty:
                    gdf_cat['categorie'] = cat
                    list_gdfs.append(gdf_cat)

        if list_gdfs: gdf_total = pd.concat(list_gdfs, ignore_index=True)

    except Exception:
        pass
    return gdf_total


# =============================================================================
# 4. AFFICHAGE RÉSULTATS
# =============================================================================
def afficher_resultats_persistants(key_data, source_name):
    data = st.session_state[key_data]
    gdf = data['gdf']
    nums_deps = data['nums_deps']
    age_stats = data.get('age_stats')
    siret_info = st.session_state.get('ref_etab_data', {})
    geo_communes_df = data.get('geo_communes_df', pd.DataFrame())

    # Sécurisation Locale
    if geo_communes_df is not None and not geo_communes_df.empty:
        l, _ = detecter_colonnes_geo(geo_communes_df)
        if not l and df_communes is not None:
            try:
                geo_communes_df = geo_communes_df.merge(
                    df_communes[['Code_INSEE', 'latitude', 'longitude']],
                    on='Code_INSEE', how='left', suffixes=('_old', '')
                )
            except:
                pass

    # Debug Optionnel
    if debug_mode:
        with st.expander("🕵️ INSPECTEUR DONNÉES", expanded=True):
            cols_ok = [c for c in ['Nom_Ville', 'latitude', 'longitude'] if c in geo_communes_df.columns]
            if cols_ok: st.dataframe(geo_communes_df[cols_ok].head())

    # Préparation
    gdf_poi = preparer_poi_pour_carte(geo_communes_df, poi_selectionnes_sidebar)
    socio, inond, rga = preparer_calques_carte_optimise(nums_deps, geo_communes_df)

    st.divider()

    # --- KPI LOGIC (V16) ---
    nb = len(gdf)

    # 1. Gestion affichage Zone (Adresse vs Etablissement)
    zone_str = "N/A"
    is_osm = (source_name == "OpenStreetMap")

    if is_osm:
        # Pour OSM, on affiche la ville recherchée en priorité
        if 'ville_recherche' in gdf.columns and not gdf['ville_recherche'].dropna().empty:
            zone_str = gdf['ville_recherche'].iloc[0]
        elif not geo_communes_df.empty and 'Nom_Ville' in geo_communes_df.columns:
            zone_str = geo_communes_df['Nom_Ville'].iloc[0]
    else:
        # Pour SIREN
        if siret_info:
            v = extraire_ville_depuis_adresse(siret_info.get('adresse', ''))
            d = siret_info.get('nom_dep', '')
            zone_str = f"{v} ({d})"
        elif 'ville' in gdf.columns:
            zone_str = gdf['ville'].mode()[0] if not gdf['ville'].empty else "Zone Multiple"

    # 2. Gestion affichage Age (Caché/Grisé si OSM)
    age_txt = f"{age_stats.get('age_moyen', 0)} ans" if (not is_osm and age_stats) else "N/A"

    # 3. Affichage KPI via cartes HTML propres
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        display_kpi_card("Établissements", nb)
    with c2:
        display_kpi_card("Zone / Ville", zone_str, "Périmètre")
    with c3:
        display_kpi_card("Source", source_name)
    with c4:
        display_kpi_card("Ancienneté Moy.", age_txt, is_active=(not is_osm))

    st.markdown("---")

    # --- CARTE (AVEC CONTROLES ET UNITES) ---
    c_map, c_legend = st.columns([3, 1])
    with c_map:
        # Contrôles
        c_ctrl1, c_ctrl2 = st.columns([1, 2])
        with c_ctrl1:
            st.markdown("**Mode Affichage**")
            mode_aff = st.radio("Mode", ["Points", "Cercles", "Isochrones"], horizontal=True,
                                label_visibility="collapsed", key=f"mode_{key_data}")
        with c_ctrl2:
            st.markdown("**Paramètres**")
            if mode_aff == "Cercles":
                # Ajout format km
                rayon = st.slider("Rayon (m)", 500, 5000, 1000, 100, format="%d m", label_visibility="collapsed",
                                  key=f"rad_{key_data}")
            else:
                rayon = 1000

            if mode_aff == "Isochrones":
                # Ajout format min
                temps = st.slider("Temps (min)", 5, 30, 10, 5, format="%d min", label_visibility="collapsed",
                                  key=f"tps_{key_data}")
            else:
                temps = 10

        # Centrage
        lat_c, lon_c = 46.6, 1.8
        if not gdf.empty:
            lat_c, lon_c = gdf.geometry.y.mean(), gdf.geometry.x.mean()
        elif not geo_communes_df.empty:
            lo, la = detecter_colonnes_geo(geo_communes_df)
            if lo: lat_c, lon_c = geo_communes_df[la].mean(), geo_communes_df[lo].mean()

        # Sécurité Volumétrie
        if nb > 1500 and mode_aff == "Points":
            st.warning(f"⚠️ {nb} points : Bascule automatique en mode Cercles pour fluidité.")
            mode_aff = "Cercles"
            rayon = 500

        m, leg_ens, stats_socio, _ = creer_carte_concurrence(
            gdf_points=gdf, lat_centre=lat_c, lon_centre=lon_c,
            gdf_socio=socio, col_socio=col_socio, lbl_socio=lbl_socio,
            gdf_inond=inond, gdf_rga=rga,
            mode_affichage="Cercles" if nb > 1500 else mode_aff,
            rayon_cercles=rayon, temps_isochrones=temps,
            gdf_poi=gdf_poi
        )

        # AJOUT V16 : MARQUEUR CIBLE ROUGE (SIRET)
        if not is_osm and siret_info and 'latitude' in siret_info:
            folium.Marker(
                [float(siret_info['latitude']), float(siret_info['longitude'])],
                popup=f"<b>CIBLE:</b><br>{siret_info.get('denominationunitelegale')}",
                icon=folium.Icon(color='red', icon='star', prefix='fa'),
                tooltip="📍 Votre Etablissement"
            ).add_to(m)

        st_folium(m, height=550, use_container_width=True, returned_objects=[])

    with c_legend:
        st.markdown("#### Légende")
        with st.container(border=True):
            st.caption("📍 Enseignes")
            if leg_ens:
                for nom, color in list(leg_ens.items())[:8]:
                    st.markdown(f'<span style="color:{color};">●</span> {nom}', unsafe_allow_html=True)
                if len(leg_ens) > 8: st.caption("...")

            if show_risk:
                st.divider()
                if "Inondation" in types_risk_selected:
                    if not inond.empty:
                        st.caption("🌊 Inondation")
                        st.markdown(
                            """<div style="font-size:12px; line-height:1.2;"><span style="color:#08306b;">■</span> Fort <span style="color:#2171b5;">■</span> Moyen <span style="color:#6baed6;">■</span> Faible</div>""",
                            unsafe_allow_html=True)
                    else:
                        st.caption("🌊 Inondation (Vide sur zone)")

                if len(types_risk_selected) > 1: st.write("")

                if "Sécheresse (RGA)" in types_risk_selected:
                    if not rga.empty:
                        st.caption("☀️ Sécheresse")
                        st.markdown(
                            """<div style="font-size:12px; line-height:1.2;"><span style="color:#5D4037;">■</span> Fort <span style="color:#8D6E63;">■</span> Moyen <span style="color:#D7CCC8;">■</span> Faible</div>""",
                            unsafe_allow_html=True)
                    else:
                        st.caption("☀️ Sécheresse (Vide sur zone)")

    st.info("ℹ️ **Note :** Les données de revenus peuvent être masquées par l'INSEE dans les zones peu denses.")
    st.divider()

    # =========================================================
    # ONGLETS FONCTIONNELS
    # =========================================================

    # CAS 1 : OPENSTREETMAP (Analyse Zone / Radar)
    if source_name == "OpenStreetMap":
        t_rad, t_list = st.tabs(["🧬 Profil Zone (Radar)", "📋 Liste"])

        with t_rad:
            with st.container(border=True):
                st.markdown("#### ⚙️ Paramètres d'analyse")
                # Slider déjà géré au dessus, on garde les boutons profils ici
                st.markdown("**Profils Rapides :**")
                b1, b2, b3 = st.columns(3)

                if b1.button("💎 CSP+", key=f"btn_csp_{key_data}", use_container_width=True):
                    st.session_state[f"met_{key_data}"] = ["Cadres", "Seniors", "Revenus"]  # 3 metrics min
                    st.rerun()

                # FIX V16 : Retrait Monoparental, ajout Actifs pour avoir 3 metrics
                if b2.button("👨‍👩‍👧 Familles", key=f"btn_fam_{key_data}", use_container_width=True):
                    st.session_state[f"met_{key_data}"] = ["Familles", "Jeunes", "Actifs"]
                    st.rerun()

                if b3.button("🏭 Ouvriers", key=f"btn_pop_{key_data}", use_container_width=True):
                    st.session_state[f"met_{key_data}"] = ["Ouvriers", "Familles", "Jeunes"]
                    st.rerun()

                # Par défaut : 5 métriques (sans Revenus)
                if f"met_{key_data}" not in st.session_state:
                    st.session_state[f"met_{key_data}"] = ["Jeunes", "Cadres", "Ouvriers", "Familles", "Actifs"]

                metrics = st.multiselect(
                    "Indicateurs :",
                    ["Revenus", "Jeunes", "Actifs", "Seniors", "Cadres", "Ouvriers", "Familles", "Retraités"],
                    key=f"met_{key_data}"
                )

        if not gdf.empty:
            # Récupération rayon depuis slider carte (s'il existe) ou défaut
            rayon_local = rayon if 'rayon' in locals() and mode_aff == "Cercles" else 1000

            zone_proj = gdf.to_crs("EPSG:2154").buffer(rayon_local).unary_union

            if not zone_proj.is_empty:
                geom_finale = gpd.GeoSeries([zone_proj], crs="EPSG:2154").to_crs("EPSG:4326").iloc[0]
                stats, nom_ref = calculer_comparatif_radar(dict_geo['IRIS'], geom_finale, metrics, df_communes)

                if stats is not None:
                    st.divider()
                    c_radar, c_top3 = st.columns([2, 1])

                    # A. Radar
                    with c_radar:
                        st.markdown("#### Profil Clientèle (Base 100)")
                        fig = plot_radar_comparatif(stats, nom_ref)
                        st.plotly_chart(fig, use_container_width=True)

                    # B. Top 3 Écarts
                    with c_top3:
                        st.markdown("#### 💡 Top Écarts")
                        if 'Indice_100' in stats.columns:
                            stats['d'] = (stats['Indice_100'] - 100).abs()
                            for _, r in stats.sort_values('d', ascending=False).head(3).iterrows():
                                ic = "📈" if r['Indice_100'] > 100 else "📉"
                                unit = "€" if "Revenu" in r['Metrique'] else "%"
                                val_aff = f"{r['Zone']:,.0f}".replace(",", " ") + unit
                                val_delta = f"{r['Indice_100'] - 100:+.0f} pts"

                                st.metric(
                                    f"{ic} {r['Metrique']}",
                                    val_aff,
                                    val_delta,
                                    delta_color="normal"
                                )

        with t_list:
            # Sécurisation des colonnes : on ne demande que ce qui existe vraiment
            cols_souhaitees = ['nom_etablissement', 'adresse_simplifiee', 'ville', 'ville_recherche',
                               'datecreationetablissement']
            cols_reelles = [c for c in cols_souhaitees if c in gdf.columns]
            st.dataframe(gdf[cols_reelles], use_container_width=True)

    # CAS 2 : SIREN (Analyse Concurrentielle / Pression / Age)
    else:
        t_press, t_age, t_list = st.tabs(["🎯 Pression & Proximité", "⏳ Ancienneté", "📋 Liste"])

        with t_press:
            st.subheader("Analyse de Proximité")
            if siret_info and 'latitude' in siret_info:

                mode_calc = st.radio("Métrie :", ["Distance (km)", "Temps (min, estimé)"], horizontal=True,
                                     key=f"metrie_{key_data}")

                gdf_calc = gdf.copy().to_crs("EPSG:2154")

                # FIX V16 : Vérification ordre lat/lon dans points_from_xy (Longitude d'abord = X)
                lon_t = float(siret_info['longitude'])
                lat_t = float(siret_info['latitude'])
                ref_point = gpd.GeoSeries([gpd.points_from_xy([lon_t], [lat_t])[0]],
                                          crs="EPSG:4326").to_crs("EPSG:2154").iloc[0]
                gdf_calc['dist_m'] = gdf_calc.distance(ref_point)

                val_col, seuil_proche, seuil_loin, suffix = 'dist_m', 1000, 5000, "m"

                if "Temps" in mode_calc:
                    gdf_calc['temps_min'] = gdf_calc['dist_m'] * 0.002  # estim 30km/h
                    val_col, seuil_proche, seuil_loin, suffix = 'temps_min', 3, 10, " min"
                    gdf_calc['val_aff'] = gdf_calc['temps_min'].round(1)
                else:
                    gdf_calc['val_aff'] = (gdf_calc['dist_m'] / 1000).round(2)
                    suffix = " km"

                def segmenter(v):
                    if v < seuil_proche:
                        return "🔴 Frontale"
                    elif v < seuil_loin:
                        return "🟠 Zone Proche"
                    return "🟢 Eloignée"

                gdf_calc['Catégorie'] = gdf_calc[val_col].apply(segmenter)

                # Explications contextuelles
                st.info(
                    f"""
                    **Légende des zones :**
                    - **🔴 Frontale** (< {seuil_proche}{suffix}) : Menace immédiate, captation de flux piéton.
                    - **🟠 Zone Proche** ({seuil_proche}-{seuil_loin}{suffix}) : Concurrence standard voiture/transport.
                    - **🟢 Eloignée** (> {seuil_loin}{suffix}) : Faible impact quotidien.
                    """
                )

                c_g, c_k = st.columns([2, 1])
                with c_g:
                    # Fix V16 : Force l'affichage de toutes les catégories même si 0
                    counts = gdf_calc['Catégorie'].value_counts().reset_index()
                    all_cats = pd.DataFrame({'Catégorie': ["🔴 Frontale", "🟠 Zone Proche", "🟢 Eloignée"]})
                    counts = all_cats.merge(counts, on='Catégorie', how='left').fillna(0)

                    fig_bar = px.bar(
                        counts,
                        x='count', y='Catégorie',  # Orientation Horizontale pour lisibilité
                        orientation='h',
                        title="Répartition de la Menace",
                        color='Catégorie',
                        color_discrete_map={"🔴 Frontale": "#d62728", "🟠 Zone Proche": "#ff7f0e",
                                            "🟢 Eloignée": "#2ca02c"},
                        category_orders={"Catégorie": ["🟢 Eloignée", "🟠 Zone Proche", "🔴 Frontale"]}  # Force l'ordre
                    )
                    fig_bar.update_layout(yaxis_title=None, xaxis_title="Nombre d'établissements")
                    st.plotly_chart(fig_bar, use_container_width=True)

                with c_k:
                    closest = gdf_calc.loc[gdf_calc['dist_m'].idxmin()]
                    st.metric("Concurrent le + proche", f"{closest['val_aff']}{suffix}",
                              f"{closest['nom_etablissement']}")
                    st.caption(f"📍 {closest['adresse_simplifiee']}")

            else:
                st.info("⚠️ Analyse de proximité disponible uniquement avec un SIRET de référence.")

        with t_age:
            if source_name == "Base SIRENE (NAF)" and 'datecreationetablissement' in gdf.columns:
                st.subheader("Distribution des Âges")
                try:
                    df_age = gdf.copy()
                    df_age['date_creation'] = pd.to_datetime(df_age['datecreationetablissement'], errors='coerce')
                    # Calcul age en années
                    df_age['Ancienneté'] = ((pd.Timestamp.now() - df_age['date_creation']).dt.days / 365.25)
                    # On ne garde que les âges valides
                    df_age = df_age[df_age['Ancienneté'] >= 0].sort_values('Ancienneté', ascending=False)

                    # --- FIX V12 : Initialisation Variables avant utilisation ---
                    min_age, max_age, moy_age = 0, 0, 0
                    if not df_age.empty:
                        min_age = df_age['Ancienneté'].min()
                        max_age = df_age['Ancienneté'].max()
                        moy_age = df_age['Ancienneté'].mean()

                    age_ref = 0
                    if siret_info and siret_info.get('datecreationetablissement'):
                        d_ref = pd.to_datetime(siret_info['datecreationetablissement'])
                        age_ref = (pd.Timestamp.now() - d_ref).days / 365.25

                    # --- BLOC INSIGHT AMÉLIORÉ ---
                    if age_ref > 0 and not df_age.empty:
                        # Ranking : Combien sont plus vieux strictement ?
                        plus_vieux = df_age[df_age['Ancienneté'] > age_ref].shape[0]
                        total = len(df_age)
                        rang = plus_vieux + 1

                        # Choix de la couleur et du message
                        if rang == 1:
                            msg_titre = f"🏆 Vous êtes le doyen (1er/{total}) !"

                        elif rang <= total * 0.25:  # Top 25%
                            msg_titre = f"✅ Top Tier : {rang}ème plus ancien sur {total}."

                        elif rang > total * 0.75:  # Derniers 25%
                            msg_titre = f"👶 Nouvel entrant : {rang}ème sur {total}."

                        else:
                            msg_titre = f"📊 Position médiane : {rang}ème sur {total}."

                        # Affichage sous forme de "Carte d'identité"
                        st.markdown(f"""
                        <div style="padding: 15px; border-radius: 5px; background-color: #f0f2f6; border-left: 5px solid #ff4b4b;">
                            <h4 style="margin-top:0;">{msg_titre}</h4>
                            <p style="font-size:15px;">
                                Avec <b>{age_ref:.1f} années</b> d'existence, vous vous situez par rapport au marché :
                            </p>
                            <ul style="margin-bottom:0;">
                                <li>📉 <b>Le plus récent :</b> {min_age:.1f} ans</li>
                                <li>⚖️ <b>Moyenne zone :</b> {moy_age:.1f} ans</li>
                                <li>👴 <b>Le plus ancien :</b> {max_age:.1f} ans</li>
                            </ul>
                        </div>
                        <br>
                        """, unsafe_allow_html=True)

                    # Histogramme Plotly
                    if not df_age.empty:
                        fig_hist = px.histogram(
                            df_age, x="Ancienneté", nbins=20,
                            title="Pyramide des âges",
                            color_discrete_sequence=['#B8860B'],
                            labels={'Ancienneté': "Années d'existence", "count": "Nombre d'établissements"}
                        )
                        # Ligne Rouge (Etablissement)
                        if age_ref > 0:
                            fig_hist.add_vline(x=age_ref, line_width=3, line_dash="dash", line_color="red")
                            fig_hist.add_annotation(x=age_ref, y=0, text="Vous", showarrow=True, arrowhead=1,
                                                    yanchor="bottom")

                        # Ligne Verte (Moyenne) - V16
                        if moy_age > 0:
                            fig_hist.add_vline(x=moy_age, line_width=3, line_dash="dot", line_color="green")
                            fig_hist.add_annotation(x=moy_age, y=0, text="Moyenne", showarrow=True, arrowhead=1,
                                                    yanchor="top")

                        st.plotly_chart(fig_hist, use_container_width=True)
                    else:
                        st.warning("Données d'âge insuffisantes.")

                except Exception as e:
                    st.error(f"Erreur calcul ancienneté : {e}")
            else:
                st.info("Données d'ancienneté non disponibles pour cette source.")

        with t_list:
            # Sécurisation : On ne sélectionne que les colonnes qui existent vraiment
            cols_ideales = ['nom_etablissement', 'adresse_simplifiee', 'ville', 'ville_recherche',
                            'datecreationetablissement']
            cols_reelles = [c for c in cols_ideales if c in gdf.columns]

            st.dataframe(
                gdf[cols_reelles],
                use_container_width=True,
                column_config={
                    "datecreationetablissement": st.column_config.DateColumn("Date Création", format="DD/MM/YYYY"),
                    "ville": "Ville",
                    "ville_recherche": "Ville"
                }
            )


# =============================================================================
# 5. RECHERCHE (Mise à jour pour stocker geo_communes_df)
# =============================================================================
tab_osm, tab_siren = st.tabs(["🔍 Par Enseigne (OSM)", "🏢 Par Etablissement (SIRET)"])

with tab_osm:
    with st.container(border=True):
        c1, c2 = st.columns([1, 1.5])
        with c1:
            st.text_input("Enseignes :", "Lidl", key="txt_osm")
        with c2:
            geo = render_selection_territoire_compact(df_communes,
                                                      "osm")  # geo['data_communes'] contient les centres des communes
        if st.button("Lancer", key="btn_osm", type="primary"):
            if geo["data_communes"].empty:
                st.error("Sélectionnez une zone.")
            else:
                with st.spinner("Recherche..."):
                    res = executer_recherche_osm_masse([x.strip() for x in st.session_state.txt_osm.split(',')],
                                                       geo["data_communes"])
                    if not res.empty:
                        res[['adresse_simplifiee', '_']] = res.apply(extraction_adresse_OSM, axis=1)
                        # --- MODIFICATION CRITIQUE : AJOUT DE LA ZONE GÉOGRAPHIQUE ---
                        st.session_state['res_osm'] = {'gdf': transfo_geodataframe(res, 'longitude', 'latitude'),
                                                       'nums_deps': geo["nums_deps"],
                                                       'geo_communes_df': geo["data_communes"],
                                                       'age_stats': None}
                        if 'ref_etab_data' in st.session_state: del st.session_state['ref_etab_data']
                    else:
                        st.warning("Rien trouvé.")
    if 'res_osm' in st.session_state: afficher_resultats_persistants('res_osm', "OpenStreetMap")

with tab_siren:
    with st.container(border=True):
        st.info("Ciblage par SIRET de référence (Détection automatique NAF + Zone)")
        c1, c2 = st.columns([3, 1])
        with c1:
            siret = st.text_input("SIRET (14 chiffres) :", key="siret_in")
        with c2:
            st.write("");
            st.write("")
            load = st.button("Charger", key="btn_load")

        if load and len(siret) == 14:
            inf = get_etablissement_par_siret(engine, siret)
            if inf:
                st.session_state['ref_etab_data'] = inf
                st.success(f"Trouvé : {inf.get('denominationunitelegale')}")
            else:
                st.error("Inconnu.")

        if 'ref_etab_data' in st.session_state:
            inf = st.session_state['ref_etab_data']
            naf, dep = inf.get('activiteprincipaleetablissement'), inf.get('numero_dep')
            naf_label = inf.get('intitules_naf_vf', 'NAF')  # AJOUT V16
            ville = extraire_ville_depuis_adresse(inf.get('adresse'))

            reg_txt = ""
            # On cherche la région pour l'affichage
            df_deps_filtered = df_communes[df_communes['Num_Dep'] == str(dep)]
            if not df_deps_filtered.empty:
                reg_txt = f" - {df_deps_filtered.iloc[0]['Nom_Region']}"

            # Créer la liste des communes dans le département pour la recherche (si besoin)
            communes_du_dep = df_communes[df_communes['Num_Dep'] == str(dep)]

            st.markdown("---")
            c_i, c_s = st.columns([1, 1.5])
            with c_i:
                st.caption("Cible")
                # AJOUT V16
                st.markdown(f"**{naf} - {naf_label}**\n\n{ville} ({dep})")
            with c_s:
                st.caption("Périmètre")
                scope = st.radio("Zone :", [f"Ville ({ville})", f"Dépt ({dep})", f"Région ({reg_txt.strip(' - ')})"],
                                 key="scope_rad")

            # --- Feature V12 : Bouton Check Volume ---
            if st.button("⚡ Vérifier le volume", type="secondary"):
                if "Dépt" in scope:
                    count = compter_resultats_sql(engine, naf, dep, siret)
                    if count > 1500:
                        st.warning(f"⚠️ **{count} résultats** potentiels : La carte sera chargée en mode allégé.")
                    else:
                        st.info(f"✅ **{count} résultats** : Volume raisonnable.")
                else:
                    st.info("ℹ️ L'estimation précise pour une Ville nécessite le géocodage complet. Lancez l'analyse.")

            if st.button("🚀 Analyser", type="primary", use_container_width=True):
                z_type = "Ville" if "Ville" in scope else "Département" if "Dépt" in scope else "Région"
                with st.spinner("Analyse..."):
                    df = get_concurrents_sql(engine, naf, dep, siret)
                    stats = calculer_stats_anciennete(engine, naf, z_type, dep, ville)

                    if not df.empty:
                        if z_type == "Ville":
                            df['v'] = df['adresse'].apply(extraire_ville_depuis_adresse)
                            df = df[df['v'] == ville.upper()]

                        # Déterminer les communes pour la zone d'étude (si SIREN)
                        if z_type == "Ville":
                            # Ne garder que la ligne de commune de la ville cible
                            geo_df_cible = df_communes[(df_communes['Nom_Ville'].str.upper() == ville.upper()) & (
                                    df_communes['Num_Dep'] == str(dep))]
                        else:
                            # Garder toutes les communes du département
                            geo_df_cible = communes_du_dep

                        if not df.empty:
                            gdf = transfo_geodataframe(df, 'longitude', 'latitude')
                            gdf['nom_etablissement'] = gdf['denominationunitelegale']
                            gdf['adresse_simplifiee'] = gdf['adresse']
                            gdf['ville'] = df['adresse'].apply(extraire_ville_depuis_adresse)

                            # --- MODIFICATION CRITIQUE : AJOUT DE LA ZONE GÉOGRAPHIQUE ---
                            st.session_state['res_siren'] = {'gdf': gdf, 'nums_deps': [dep],
                                                             'geo_communes_df': geo_df_cible,
                                                             'age_stats': stats}
                        else:
                            st.warning("Aucun concurrent sur la ville.")
                    else:
                        st.warning("Aucun concurrent sur le département.")

    if 'res_siren' in st.session_state: afficher_resultats_persistants('res_siren', "Base SIRENE (NAF)")