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
    charger_communes, charger_donnees_iris_socio, charger_coefficients_trafic,
    preparer_donnees_socio, charger_zones_inondables, charger_donnees_rga,
    charger_donnees_dvf, connect_to_db,
    calculer_comparatif_radar,
    calculer_cannibalisation,
    auditer_risque_batiments
)
from fonctions_cartographie import (
    creer_carte_implantation, calculer_isochrone_et_cacher,
    rechercher_poi_osm, rechercher_batiments_osm,
    geocoder_adresse_nominatim_ui,
    transfo_geodataframe,
    analyser_environnement_naturel
)
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
PATH_DVF_PARQUET = "data/Valeurs_foncieres_geoloc_2024_2025.parquet"


# =============================================================================
# HELPERS LOCAUX
# =============================================================================

def generer_avis_synthetique(note_globale, malus_inond):
    statut, couleur = "", ""
    if malus_inond >= 20:
        statut, couleur = "ZONE À RISQUE FORT", "red"
    elif note_globale >= 80:
        statut, couleur = "EXCELLENTE OPPORTUNITÉ", "green"
    elif note_globale >= 60:
        statut, couleur = "BON POTENTIEL", "green"
    elif note_globale >= 40:
        statut, couleur = "POTENTIEL MODÉRÉ", "orange"
    else:
        statut, couleur = "ZONE DÉLICATE", "red"
    return statut, couleur


def _calculer_score_attractivite(pop_zone, revenu_zone, nb_ventes_immo, niv_inond, niv_rga, taux_cannib, surface_km2):
    score = 0
    surface_km2 = max(surface_km2, 0.1)

    densite_pop = pop_zone / surface_km2
    densite_ventes = nb_ventes_immo / surface_km2

    # 1. POTENTIEL (40 pts)
    s_densite = min(densite_pop / 2000, 1) * 25
    s_revenu = min(revenu_zone / 30000, 1) * 15 if revenu_zone else 7.5
    score += (s_densite + s_revenu)

    # 2. DYNAMISME (30 pts)
    s_immo = min(densite_ventes / 15, 1) * 30
    score += s_immo

    # 3. SÉCURITÉ (30 pts)
    malus_i = 20 if niv_inond == 3 else 10 if niv_inond == 2 else 5 if niv_inond == 1 else 0
    malus_r = 10 if niv_rga == 3 else 5 if niv_rga == 2 else 2 if niv_rga == 1 else 0
    score += max(0, 30 - malus_i - malus_r)

    # Malus Saturation
    malus_c = min((taux_cannib - 10) * 2, 40) if taux_cannib > 10 else 0
    score = max(0, score - malus_c)

    note = int(score)

    explications = {
        "Densité Pop": f"{int(densite_pop)} hab/km²",
        "Revenu Médian": f"{int(revenu_zone)} €",
        "Densité Ventes": f"{densite_ventes:.1f} ventes/km²",
        "Malus Inondation": f"-{malus_i}",
        "Malus Sécheresse": f"-{malus_r}",
        "Malus Saturation": f"-{int(malus_c)}"
    }
    parts = {
        "Potentiel Zone": round(s_densite + s_revenu, 1),
        "Dynamisme Immo": round(s_immo, 1),
        "Sécurité Env.": max(0, 30 - malus_i - malus_r)
    }
    return note, parts, int(malus_c), malus_i, malus_r, explications


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

with st.spinner("Chargement des données territoriales..."):
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


    cb_bati = st.checkbox("Afficher Bâtiments", value=st.session_state.show_batiments, key="cb_bati_sidebar",
                          on_change=toggle_bati)
    st.session_state.show_batiments = cb_bati

    if st.session_state.show_batiments:
        c_min, c_max = st.columns(2)
        surface_min = c_min.number_input("Min m²", 0, 10000, 0, step=50)
        surface_max = c_max.number_input("Max m²", 0, 100000, 3000, step=100)
    else:
        surface_min, surface_max = 0, 3000

    show_inond = st.checkbox("Afficher Inondations", value=False)
    reg_inond, dep_inond = [], []
    if show_inond: reg_inond, dep_inond = interface_filtre_geo_risque(df_communes, "inond")

    show_rga = st.checkbox("Afficher Sécheresse", value=False)
    reg_rga, dep_rga = [], []
    if show_rga: reg_rga, dep_rga = interface_filtre_geo_risque(df_communes, "rga")

    # 3. Saturation (Ex-Cannib)
    st.divider()
    mode_cannibale = st.toggle("Analyse Saturation / Réseau", value=False,
                               help="Vérifier la présence d'autres points de vente du réseau.")

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
    afficher_dvf = st.checkbox("Afficher Transactions", value=False)
    dvf_type_map = "Tous"
    mode_visu_map = "Points"
    if afficher_dvf:
        dvf_type_map = st.selectbox("Type de bien", ["Tous", "Commerce", "Maison", "Appartement"])
        mode_visu_map = st.selectbox("Style carte", ["Points", "Heatmap"])

# --- PRÉPARATION COUCHES CARTE ---
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

# --- CALCULS AUTOMATIQUES ---
if final_lat and final_lon:

    # 1. Zone
    temps_isochrones = 5
    if mode == 'Isochrones': temps_isochrones = st.slider("Temps de trajet (min)", 2, 20, 5, 1)

    zone_analyse_geom = None
    surface_zone_km2 = 0
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

    # 2. DVF
    df_dvf_zone = pd.DataFrame()
    if not df_dvf_total.empty:
        m = 0.02
        df_dvf_zone = df_dvf_total[
            (df_dvf_total['latitude'] > final_lat - m) & (df_dvf_total['latitude'] < final_lat + m) &
            (df_dvf_total['longitude'] > final_lon - m) & (df_dvf_total['longitude'] < final_lon + m)
            ]

    # 3. Audit Bâtiments
    gdf_batiments_audit = gpd.GeoDataFrame()
    if zone_analyse_geom:
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
    #  🏆 SCORE & SYNTHÈSE
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

        # Risques
        score_inond, score_rga = 0, 0
        if not gdf_batiments_audit.empty:
            if gdf_batiments_audit['has_Inondation'].any():
                top = gdf_batiments_audit[gdf_batiments_audit['has_Inondation']]['niveau_Inondation'].unique()
                score_inond = 3 if any('fort' in str(s).lower() for s in top) else 2 if any(
                    'moyen' in str(s).lower() for s in top) else 1
            if gdf_batiments_audit['has_Argile'].any():
                top = gdf_batiments_audit[gdf_batiments_audit['has_Argile']]['niveau_Argile'].unique()
                score_rga = 3 if any('fort' in str(s).lower() for s in top) else 2 if any(
                    'moyen' in str(s).lower() for s in top) else 1

        taux_can = 0
        if mode_cannibale and not gdf_reseau_client.empty:
            taux_can = calculer_cannibalisation(zone_analyse_geom, gdf_reseau_client)

        score_final, parts, malus_c, malus_i, malus_r, ex = _calculer_score_attractivite(pop, rev, len(df_dvf_zone),
                                                                                         score_inond, score_rga,
                                                                                         taux_can, surface_zone_km2)

        statut_zone, couleur_statut = generer_avis_synthetique(score_final, malus_i)

        # AFFICHAGE DASHBOARD
        col_avis, col_score = st.columns([1.5, 2])

        with col_avis:
            st.metric("Indice d'Attractivité", f"{score_final}/100")
            if couleur_statut == "green":
                st.success(f"**{statut_zone}**")
            elif couleur_statut == "orange":
                st.warning(f"**{statut_zone}**")
            else:
                st.error(f"**{statut_zone}**")

        with col_score:
            st.caption("Performance par pilier :")
            c1, c2, c3 = st.columns(3)
            c1.progress(parts['Potentiel Zone'] / 40, f"Potentiel {parts['Potentiel Zone']} pts")
            c2.progress(parts['Dynamisme Immo'] / 30, f"Dynamisme {parts['Dynamisme Immo']} pts")
            c3.progress(parts['Sécurité Env.'] / 30, f"Sécurité {parts['Sécurité Env.']} pts")

            if mode_cannibale:
                st.progress(min(taux_can / 100, 1.0), f"Saturation {taux_can:.1f}%")

        with st.expander("ℹ️ Comprendre l'analyse"):
            c_ex1, c_ex2 = st.columns(2)
            with c_ex1:
                st.markdown("**Indicateurs de Performance**")
                st.write(f"- Densité Pop : **{ex['Densité Pop']}**")
                st.write(f"- Niveau de Vie : **{ex['Revenu Médian']}**")
                st.write(f"- Activité Immo : **{ex['Densité Ventes']}**")
            with c_ex2:
                st.markdown("**Facteurs de Risque**")
                st.write(f"- Inondation : **{ex['Malus Inondation']} pts**")
                st.write(f"- Sécheresse : **{ex['Malus Sécheresse']} pts**")
                if mode_cannibale:
                    st.write(f"- Saturation : **{ex['Malus Saturation']} pts**")

    # --- CARTE ---
    df_dvf_map = df_dvf_zone
    if afficher_dvf and dvf_type_map != "Tous":
        df_dvf_map = df_dvf_zone[df_dvf_zone['type_local'] == dvf_type_map]

    map_obj, legend_socio, legend_val, legend_dvf = creer_carte_implantation(
        lat_centre=final_lat, lon_centre=final_lon, zone_analyse_geom=zone_analyse_geom,
        gdf_poi_trouves=gdf_poi_trouves,
        gdf_socio=gdf_socio_filtre, colonne_socio=indicateur, nom_indicateur_socio=nom_indicateur,
        gdf_batiments=gdf_batiments_audit if st.session_state.show_batiments else None,
        gdf_inondations=gdf_inond_map, gdf_rga=gdf_rga_map,
        nom_point_central=final_nom, adresse_point_central=final_adresse_str,
        analysis_mode=mode, df_dvf=df_dvf_map if afficher_dvf else None, dvf_type_filtre=dvf_type_map,
        mode_affichage_dvf=mode_visu_map
    )
    st_folium(map_obj, width=800, height=500, returned_objects=[])

    # =========================================================
    # ONGLETS D'ANALYSE
    # =========================================================
    if zone_analyse_geom:
        tab_pop, tab_immo, tab_tech = st.tabs(["🧬 Environnement", "💰 Immobilier", "🏗️ Risques & Technique"])

        # --- 1. POPULATION ---
        with tab_pop:
            if 'IRIS' in dict_geodatas:
                col_presets, col_custom = st.columns([1, 2])
                if "selected_metrics" not in st.session_state: st.session_state.selected_metrics = ["Revenus", "Jeunes",
                                                                                                    "Actifs", "Seniors",
                                                                                                    "Cadres"]
                with col_presets:
                    st.markdown("**Profils Types**")
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
                                           ["Revenus", "Jeunes", "Actifs", "Seniors", "Cadres", "Ouvriers", "Familles"],
                                           default=st.session_state.selected_metrics, key="radar_sel")
                if choix:
                    df_rad, nom_dep = calculer_comparatif_radar(dict_geodatas['IRIS'], zone_analyse_geom,
                                                                metriques_demandees=choix, df_communes_ref=df_communes)
                    if df_rad is not None and not df_rad.empty:
                        c_radar, c_kpi = st.columns([1.5, 1])
                        with c_radar:
                            fig = go.Figure()
                            fig.add_trace(
                                go.Scatterpolar(r=[100] * len(df_rad), theta=df_rad['Metrique'], name="Moyenne",
                                                line_color='gray'))
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
                                    txt_val = f"{row['Zone']:,.0f} €" if "Revenu" in row[
                                        'Metrique'] else f"{row['Zone']:.1f}%"
                                    st.metric(label=f"{icon} {row['Metrique']}", value=txt_val,
                                              delta=f"{delta:+.0f} pts")

        # --- 2. IMMOBILIER ---
        with tab_immo:
            if not df_dvf_zone.empty:
                st.markdown("#### Marché Immobilier")
                c_g1, c_g2 = st.columns(2)
                fig_dist = px.histogram(df_dvf_zone, x="prix_m2", nbins=20, title="Distribution Prix m²",
                                        color_discrete_sequence=['#C5A065'])
                c_g1.plotly_chart(fig_dist, use_container_width=True)
                df_time = df_dvf_zone.sort_values('date_mutation')
                fig_line = px.line(df_time, x='date_mutation', y='prix_m2', title="Tendance Prix m²", markers=True,
                                   color_discrete_sequence=['#C5A065'])
                c_g2.plotly_chart(fig_line, use_container_width=True)

                st.divider()
                c_fil1, c_fil2 = st.columns(2)
                with c_fil1:
                    typ = st.multiselect("Filtrer Type", df_dvf_zone['type_local'].unique(),
                                         default=df_dvf_zone['type_local'].unique())
                with c_fil2:
                    ann = st.multiselect("Filtrer Année", sorted(df_dvf_zone['annee'].dropna().unique()),
                                         default=sorted(df_dvf_zone['annee'].dropna().unique()))
                df_show = df_dvf_zone[df_dvf_zone['type_local'].isin(typ) & df_dvf_zone['annee'].isin(ann)]

                k1, k2, k3 = st.columns(3)
                k1.metric("Volume Transigé", len(df_show))
                k2.metric("Prix m² Médian", f"{df_show['prix_m2'].median():.0f} €")
                k3.metric("Ticket Moyen", f"{df_show['valeur_fonciere'].median():.0f} €")
                st.dataframe(df_show[['date_mutation', 'valeur_fonciere', 'prix_m2', 'type_local']].head(50),
                             use_container_width=True)
            else:
                st.info("Pas de données DVF sur la zone.")

        # --- 3. TECHNIQUE (AVEC NOUVEAUX RISQUES) ---
        with tab_tech:
            if not st.session_state.show_batiments:
                st.info("💡 L'audit détaillé du bâti est masqué.")
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
                    fig_i = px.pie(df_final, values='Nombre', names='Niveau', hole=0.4, title="Exposition Bâti",
                                   color='Niveau', color_discrete_map={'Aléa fort': '#d62728', 'Aléa moyen': '#ff7f0e',
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
                    fig_r = px.bar(df_final, x='Niveau', y='Nombre', title="Répartition Argiles",
                                   color='Niveau', color_discrete_map={'Aléa fort': '#d62728', 'Aléa moyen': '#ff7f0e',
                                                                       'Aléa faible': '#fecb52', 'Aucun': '#2ca02c'})
                    st.plotly_chart(fig_r, use_container_width=True)
                else:
                    st.info("Pas de bâtiments.")

            # --- NOUVEAU BLOC : RISQUES ÉMERGENTS (PRIORITÉ 3) ---
            st.markdown("---")
            st.subheader("🔥 Risques Émergents (Climat 2050)")

            # Analyse Nature (Forêt/Chaleur)
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
                # CORRECTION : Gestion du 0 m
                if dist_foret < 1:
                    st.error(f"🚨 **RISQUE MAXIMAL** (Contact)")
                    st.write("Le site est **dans** ou **au contact** d'un massif.")
                elif dist_foret < 50:
                    st.error(f"🚨 **ÉLEVÉ** (< 50m)")
                    st.write(f"Distance lisière : **{dist_foret:.0f} m**")
                    st.caption("Débroussaillement obligatoire probable.")
                elif dist_foret < 200:
                    st.warning(f"🟠 **MODÉRÉ** (< 200m)")
                    st.write(f"Distance lisière : **{dist_foret:.0f} m**")
                elif dist_foret == 9999:
                    st.info("Données végétation non disponibles.")
                else:
                    st.success(f"✅ **FAIBLE**")
                    st.write("Pas de massif forestier immédiat.")

            with c_chau:
                st.caption("🌡️ Confort Thermique (Végétalisation)")
                st.metric("Taux de Végétalisation", f"{ratio_veg:.1f}%")

                if ratio_veg < 10:
                    st.progress(ratio_veg / 100, "Zone très minérale (Risque ICU fort)")
                elif ratio_veg < 40:
                    st.progress(ratio_veg / 100, "Zone mixte")
                else:
                    st.progress(ratio_veg / 100, "Ilot de fraîcheur potentiel")

            # --- NOTE METHODOLOGIQUE ---
            with st.expander("ℹ️ Note Méthodologique (Sources & Définitions)"):
                st.caption("""
                **1. Inondation & Sécheresse :** Basé sur les croisements géographiques (TRI/RGA).
                **2. Incendie :** Calculé sur la base OpenStreetMap (OSM). La "Distance lisière" représente l'éloignement au polygone de végétation le plus proche.
                **3. Chaleur :** Estimation du ratio de surfaces minérales vs végétales dans le rayon d'analyse.
                """)