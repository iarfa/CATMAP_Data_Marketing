# Fichier: pages/02_Zone_Implantation.py

import streamlit as st
import geopandas as gpd
import pandas as pd
import plotly.graph_objects as go
from streamlit_folium import st_folium
from shapely.geometry import Point, shape

# Imports Métiers
from fonctions_basiques import (
    charger_communes, charger_donnees_iris_socio, charger_coefficients_trafic,
    preparer_donnees_socio, charger_zones_inondables, charger_donnees_rga,
    charger_donnees_dvf, connect_to_db,
    calculer_comparatif_radar,
    calculer_cannibalisation  # Assurez-vous que cette fonction est bien dans fonctions_basiques.py
)
from fonctions_cartographie import (
    creer_carte_implantation, calculer_isochrone_et_cacher,
    rechercher_poi_osm, rechercher_batiments_osm,
    geocoder_adresse_nominatim_ui,
    transfo_geodataframe
)
from interface import (
    interface_selection_socio, interface_selection_poi, POI_CONFIG,
    interface_selection_batiments, interface_selection_risques,
    interface_point_interet
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
# HELPERS LOCAUX (SCORING)
# =============================================================================

def _calculer_score_zone(pop_zone, revenu_zone, nb_ventes_immo, has_risk_inond, has_risk_rga, taux_cannibalisation):
    """
    Génère un score synthétique sur 100 incluant le Malus Cannibalisation.
    """
    score = 0
    details = {}

    # 1. POTENTIEL (40 pts max)
    s_pop = min(pop_zone / 10000, 1) * 25
    s_rev = min(revenu_zone / 30000, 1) * 15 if revenu_zone else 7.5
    details['Potentiel'] = round(s_pop + s_rev, 1)
    score += details['Potentiel']

    # 2. DYNAMISME (30 pts max)
    s_immo = min(nb_ventes_immo / 50, 1) * 30
    details['Dynamisme'] = round(s_immo, 1)
    score += s_immo

    # 3. SÛRETÉ (30 pts max)
    s_risk = 30
    if has_risk_inond: s_risk -= 15
    if has_risk_rga: s_risk -= 5
    details['Sûreté'] = max(0, s_risk)
    score += details['Sûreté']

    # 4. MALUS CANNIBALISATION (Hors Barème, retire des points)
    malus = 0
    if taux_cannibalisation > 10:  # On tolère 10% de recouvrement
        # 2 points de malus par % de recouvrement au dessus de 10%
        malus = (taux_cannibalisation - 10) * 2
        malus = min(malus, 40)  # Max 40 pts de pénalité

    score = max(0, score - malus)

    # Note Finale
    note = int(score)
    if note >= 80:
        label = "A (Excellent)"
    elif note >= 60:
        label = "B (Bon)"
    elif note >= 40:
        label = "C (Moyen)"
    else:
        label = "D (Risqué)"

    return note, label, details, int(malus)


def _preparer_et_filtrer_gdf_risque(gdf_source, nom_risque, risque_selectionne, regions_filtrees, departements_filtres):
    if risque_selectionne != nom_risque or gdf_source.empty:
        return gpd.GeoDataFrame()
    if 'NOM_DEP' in gdf_source.columns and 'Num_Dep' in gdf_source.columns:
        gdf_source['affichage_dep'] = gdf_source['Num_Dep'] + " - " + gdf_source['NOM_DEP'].str.upper()
    if regions_filtrees and 'NOM_REG' in gdf_source.columns:
        return gdf_source[gdf_source['NOM_REG'].isin(regions_filtrees)]
    elif departements_filtres and 'affichage_dep' in gdf_source.columns:
        return gdf_source[gdf_source['affichage_dep'].isin(departements_filtres)]
    return gdf_source


# =============================================================================
# MAIN EXECUTION
# =============================================================================

st.title("📍 Analyse de Zone d'Implantation")

engine = connect_to_db()

with st.spinner("Chargement des données contextuelles..."):
    df_communes = charger_communes(PATH_COMMUNES)
    gdf_inondations = charger_zones_inondables(PATH_ZONES_INONDABLES)
    gdf_rga = charger_donnees_rga(PATH_RGA_SECHERESSE)
    df_iris_base = charger_donnees_iris_socio(PATH_IRIS_SOCIO)
    df_dvf_total = charger_donnees_dvf(PATH_DVF_PARQUET)

# Préparation Socio
if 'dict_geodatas' not in st.session_state:
    st.session_state['dict_geodatas'] = preparer_donnees_socio(df_iris_base, df_communes)
dict_geodatas = st.session_state['dict_geodatas']

# --- SIDEBAR ---
gdf_socio_filtre, indicateur, nom_indicateur, maille = interface_selection_socio(dict_geodatas)
risque_selectionne, regions_filtrees, departements_filtres = interface_selection_risques(df_communes)
poi_selectionnes_sidebar = interface_selection_poi()

with st.sidebar:
    afficher_batiments, surface_min, surface_max = interface_selection_batiments()

    # --- NOUVEAU : UPLOAD RÉSEAU POUR CANNIBALISATION ---
    with st.expander("🏪 Mon Réseau (Cannibalisation)"):
        uploaded_reseau = st.file_uploader("Charger fichier boutiques (CSV/Excel)", type=["csv", "xlsx"],
                                           help="Colonnes requises : latitude, longitude")
        gdf_reseau_client = gpd.GeoDataFrame()
        if uploaded_reseau:
            try:
                if uploaded_reseau.name.endswith('.csv'):
                    df_res = pd.read_csv(uploaded_reseau)
                else:
                    df_res = pd.read_excel(uploaded_reseau)

                # Nettoyage colonnes lat/lon
                lat_col = next((c for c in df_res.columns if 'lat' in c.lower()), None)
                lon_col = next((c for c in df_res.columns if 'lon' in c.lower()), None)

                if lat_col and lon_col:
                    gdf_reseau_client = transfo_geodataframe(df_res, lon_col, lat_col)
                    st.success(f"{len(gdf_reseau_client)} points chargés")
                else:
                    st.error("Colonnes latitude/longitude introuvables.")
            except Exception as e:
                st.error(f"Erreur lecture : {e}")

gdf_inondations_a_afficher = _preparer_et_filtrer_gdf_risque(gdf_inondations, "Inondations", risque_selectionne,
                                                             regions_filtrees, departements_filtres)
gdf_rga_a_afficher = _preparer_et_filtrer_gdf_risque(gdf_rga, "Sécheresse (RGA)", risque_selectionne, regions_filtrees,
                                                     departements_filtres)

# --- CONFIGURATION PRINCIPALE ---

result_point_central = interface_point_interet(engine=engine)

final_lat, final_lon = None, None
final_nom, final_adresse_str = None, None
mode, radius = result_point_central['mode'], result_point_central['radius']

if result_point_central['source'] == "Adresse":
    res_geo = geocoder_adresse_nominatim_ui(result_point_central['valeur'])
    if res_geo:
        final_lat = res_geo.get('latitude')
        final_lon = res_geo.get('longitude')
        final_nom = res_geo.get('denominationunitelegale')
        final_adresse_str = res_geo.get('adresse')
elif result_point_central['source'] == "Coordonnées":
    if result_point_central['valeur']:
        final_lat = result_point_central['valeur']['latitude']
        final_lon = result_point_central['valeur']['longitude']
        final_nom = f"Point ({final_lat:.4f}, {final_lon:.4f})"
        final_adresse_str = "Coordonnées manuelles"
elif result_point_central['source'] == "SIRET/SIREN":
    if result_point_central['valeur']:
        res_siret = result_point_central['valeur']
        final_lat = res_siret.get('latitude')
        final_lon = res_siret.get('longitude')
        final_nom = res_siret.get('denominationunitelegale')
        final_adresse_str = res_siret.get('adresse')
        if final_nom and "non indique" in str(final_nom).lower():
            st.warning("Le nom de cet établissement est 'Non indique' dans la base de données.", icon="ℹ️")

# --- CALCULS & AFFICHAGE ---

if final_lat and final_lon:

    # 1. Calcul Géométrie Zone
    temps_isochrones = 5
    if mode == 'Isochrones':
        temps_isochrones = st.slider("Temps de trajet (min) :", 2, 20, 5, 1, key="temps_implantation")

    zone_analyse_geom = None
    if mode == 'Isochrones':
        temps_secondes_ajuste = temps_isochrones * 60 * 0.9
        feature = calculer_isochrone_et_cacher(final_lon, final_lat, temps_secondes_ajuste)
        if feature:
            zone_analyse_geom = shape(feature['geometry'])
    elif mode == "Cercle d'influence":
        poi_point_gdf = gpd.GeoDataFrame(geometry=[Point(final_lon, final_lat)], crs="EPSG:4326")
        zone_analyse_geom_reproj = poi_point_gdf.to_crs("EPSG:3857").buffer(radius).iloc[0]
        zone_analyse_geom = \
        gpd.GeoDataFrame(geometry=[zone_analyse_geom_reproj], crs="EPSG:3857").to_crs("EPSG:4326").geometry.iloc[0]

    # 2. Préparation DVF (Carte + Stats)
    df_dvf_visuel = None
    dvf_type_choix = "Tous"
    mode_visu_dvf = "Points"
    afficher_dvf = False

    with st.expander("🛠️ Paramètres DVF (Immobilier)", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            afficher_dvf = st.toggle("Activer la couche DVF", value=True)
        with c2:
            if afficher_dvf:
                dvf_type_choix = st.radio("Type de bien :", ["Tous", "Commerce", "Maison", "Appartement"],
                                          horizontal=True)
                mode_visu_dvf = st.selectbox("Style :", ["Points (Précis)", "Heatmap (Densité)"])

    if afficher_dvf and not df_dvf_total.empty:
        marge = 0.02
        df_dvf_filtre = df_dvf_total[
            (df_dvf_total['latitude'] > final_lat - marge) & (df_dvf_total['latitude'] < final_lat + marge) &
            (df_dvf_total['longitude'] > final_lon - marge) & (df_dvf_total['longitude'] < final_lon + marge)
            ]
        if dvf_type_choix != "Tous":
            df_dvf_visuel = df_dvf_filtre[df_dvf_filtre['type_local'] == dvf_type_choix]
        else:
            df_dvf_visuel = df_dvf_filtre

    # 3. POI & Bâtiments
    gdf_poi_trouves = gpd.GeoDataFrame()
    if zone_analyse_geom and poi_selectionnes_sidebar:
        bbox = zone_analyse_geom.bounds
        with st.spinner("Recherche POI..."):
            liste_gdf_poi = [rechercher_poi_osm(bbox, POI_CONFIG[cat]['tags']).assign(categorie=cat) for cat in
                             poi_selectionnes_sidebar]
            liste_gdf_poi_non_vides = [gdf for gdf in liste_gdf_poi if not gdf.empty]
            if liste_gdf_poi_non_vides:
                gdf_poi_brut = pd.concat(liste_gdf_poi_non_vides, ignore_index=True)
                if not gdf_poi_brut.empty:
                    gdf_poi_trouves = gdf_poi_brut[gdf_poi_brut.within(zone_analyse_geom)]

    gdf_batiments_final = gpd.GeoDataFrame()
    if afficher_batiments and zone_analyse_geom:
        with st.spinner("Recherche Bâtiments..."):
            bbox_batiments = zone_analyse_geom.bounds
            gdf_batiments_brut = rechercher_batiments_osm(bbox_batiments)
            if not gdf_batiments_brut.empty:
                gdf_batiments_filtres_surface = gdf_batiments_brut[
                    (gdf_batiments_brut['surface_m2'] >= surface_min) & (
                                gdf_batiments_brut['surface_m2'] <= surface_max)
                    ]
                if not gdf_batiments_filtres_surface.empty:
                    gdf_batiments_final = gdf_batiments_filtres_surface[
                        gdf_batiments_filtres_surface.within(zone_analyse_geom)]

    # =========================================================
    #  🏆 INDICE D'ATTRACTIVITÉ (SCORING AVANCÉ)
    # =========================================================
    if zone_analyse_geom is not None:
        st.markdown("---")

        # A. Socio
        pop_score = 0
        rev_score = 0
        if 'IRIS' in dict_geodatas and not dict_geodatas['IRIS'].empty:
            # Intersection rapide pour le score
            gdf_iris_score = gpd.sjoin(dict_geodatas['IRIS'],
                                       gpd.GeoDataFrame({'geometry': [zone_analyse_geom]}, crs="EPSG:4326"),
                                       how="inner", predicate="intersects")
            if not gdf_iris_score.empty:
                pop_score = gdf_iris_score[
                    'Population_totale'].sum() if 'Population_totale' in gdf_iris_score.columns else 0
                rev_score = gdf_iris_score['Revenu_median'].mean() if 'Revenu_median' in gdf_iris_score.columns else 0

        # B. Risques
        risk_inond = not gdf_inondations_a_afficher.empty
        risk_rga = not gdf_rga_a_afficher.empty

        # C. Immo
        nb_ventes = len(df_dvf_visuel) if df_dvf_visuel is not None else 0

        # D. CANNIBALISATION (Nouveau)
        taux_cannib = 0
        if not gdf_reseau_client.empty:
            # On calcule le recouvrement avec le réseau chargé (Buffer 2km par défaut pour zone chalandise magasin)
            taux_cannib = calculer_cannibalisation(zone_analyse_geom, gdf_reseau_client, buffer_existant_m=2000)

        # Calcul Final
        score_final, label_final, details_score, malus = _calculer_score_zone(pop_score, rev_score, nb_ventes,
                                                                              risk_inond, risk_rga, taux_cannib)

        # --- AFFICHAGE DU SCORE ---
        c_left, c_right = st.columns([1, 2])

        with c_left:
            st.metric("Indice d'Attractivité", f"{score_final}/100", label_final)
            if malus > 0:
                st.error(f"⚠️ Malus Cannibalisation : -{malus} pts")

        with c_right:
            # Barres de progression
            c1, c2, c3 = st.columns(3)
            c1.caption("📈 Potentiel (40%)")
            c1.progress(details_score['Potentiel'] / 40, text=f"{details_score['Potentiel']} pts")

            c2.caption("🛍️ Dynamisme (30%)")
            c2.progress(details_score['Dynamisme'] / 30, text=f"{details_score['Dynamisme']} pts")

            c3.caption("🛡️ Sûreté (30%)")
            c3.progress(details_score['Sûreté'] / 30, text=f"{details_score['Sûreté']} pts")

            # Barre Cannibalisation (Si active)
            if not gdf_reseau_client.empty:
                st.caption(f"🥩 Taux de Cannibalisation ({taux_cannib:.1f}%)")
                color_bar = "red" if taux_cannib > 20 else "orange" if taux_cannib > 5 else "green"
                st.progress(min(taux_cannib / 100, 1.0), text="Recouvrement zone")

        # Note Explicative
        with st.expander("ℹ️ Comprendre ce score"):
            st.markdown("""
            **Construction de l'indice :**
            1.  **Potentiel (40 pts)** : Masse de population et Revenu Médian.
            2.  **Dynamisme (30 pts)** : Volume de transactions immobilières (Attractivité zone).
            3.  **Sûreté (30 pts)** : Absence de risques majeurs (Inondation/Argiles).
            4.  **Malus Cannibalisation** : Pénalité si la zone mord sur celle d'un magasin existant (chargé en Sidebar).
            """)

    # --- CARTE ---
    st.markdown("---")
    map_object, legend_socio_color, legend_socio_single, legend_dvf = creer_carte_implantation(
        lat_centre=final_lat, lon_centre=final_lon,
        zone_analyse_geom=zone_analyse_geom,
        gdf_poi_trouves=gdf_poi_trouves,
        gdf_socio=gdf_socio_filtre,
        colonne_socio=indicateur, nom_indicateur_socio=nom_indicateur,
        gdf_batiments=gdf_batiments_final,
        gdf_inondations=gdf_inondations_a_afficher, gdf_rga=gdf_rga_a_afficher,
        nom_point_central=final_nom,
        adresse_point_central=final_adresse_str,
        analysis_mode=mode,
        df_dvf=df_dvf_visuel if afficher_dvf else None,
        dvf_type_filtre=dvf_type_choix,
        mode_affichage_dvf=mode_visu_dvf.split(" ")[0]
    )

    col_carte, col_legende = st.columns([3, 1])
    with col_carte:
        st_folium(map_object, width=800, height=500, returned_objects=[])

    with col_legende:
        st.subheader("Légendes")
        if legend_dvf:
            st.caption(f"Prix Immo ({dvf_type_choix})")
            gradient_hex = [legend_dvf(x) for x in legend_dvf.index]
            st.markdown(
                f'<div style="height: 10px; border-radius: 2px; background: linear-gradient(to right, {", ".join(gradient_hex)});"/>',
                unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            c1.caption(f"{legend_dvf.vmin:,.0f}€")
            c2.caption(f"{legend_dvf.vmax:,.0f}€")

        if legend_socio_color:
            st.caption(f"Socio: {legend_socio_color.caption}")
            gradient_hex = [legend_socio_color(x) for x in legend_socio_color.index]
            st.markdown(
                f'<div style="height: 10px; border-radius: 2px; background: linear-gradient(to right, {", ".join(gradient_hex)});"/>',
                unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            c1.caption(f"{legend_socio_color.vmin:,.0f}")
            c2.caption(f"{legend_socio_color.vmax:,.0f}")

    # =========================================================
    # ONGLETS DÉTAILLÉS
    # =========================================================
    st.markdown("---")
    tab_pop, tab_immo, tab_tech = st.tabs(["🧬 Profil Population", "💰 Immobilier (DVF)", "🏗️ Technique & Risques"])

    # --- ONGLET 1 : RADAR ---
    with tab_pop:
        st.header("Analyse Socio-Démographique")

        if 'IRIS' in dict_geodatas and dict_geodatas['IRIS'] is not None and zone_analyse_geom:
            col_presets, col_custom = st.columns([1, 2])

            if "selected_metrics" not in st.session_state or not st.session_state.selected_metrics:
                st.session_state.selected_metrics = ["Revenus", "Jeunes", "Actifs", "Seniors", "Cadres"]

            with col_presets:
                st.markdown("**Profils Types :**")
                if st.button("💎 Haut de Gamme", use_container_width=True):
                    st.session_state.selected_metrics = ["Revenus", "Cadres", "Seniors", "Retraités"]
                if st.button("👨‍👩‍👧 Familial", use_container_width=True):
                    st.session_state.selected_metrics = ["Revenus", "Familles", "Jeunes", "Actifs"]
                if st.button("🏭 Populaire", use_container_width=True):
                    st.session_state.selected_metrics = ["Revenus", "Ouvriers", "Monoparental", "Actifs"]

            with col_custom:
                st.markdown("**Critères :**")
                choix_final = st.multiselect(
                    "Indicateurs :",
                    options=["Revenus", "Jeunes", "Actifs", "Seniors", "Cadres", "Ouvriers", "Familles", "Monoparental",
                             "Retraités"],
                    default=st.session_state.selected_metrics,
                    key="multi_metrics_tab",
                    label_visibility="collapsed"
                )

            if choix_final:
                df_radar, nom_dept_ref = calculer_comparatif_radar(
                    dict_geodatas['IRIS'], zone_analyse_geom,
                    metriques_demandees=choix_final, df_communes_ref=df_communes
                )

                if df_radar is not None and not df_radar.empty:
                    st.markdown(f"### 🆚 Comparaison : Zone vs {nom_dept_ref}")
                    col_g, col_k = st.columns([1.5, 1])
                    with col_g:
                        fig = go.Figure()
                        fig.add_trace(go.Scatterpolar(r=[100] * len(df_radar), theta=df_radar['Metrique'], fill=None,
                                                      name=f"Moyenne", line_color='gray', line_dash='dot'))
                        fig.add_trace(
                            go.Scatterpolar(r=df_radar['Indice_100'], theta=df_radar['Metrique'], fill='toself',
                                            name='Zone', line_color='#B8860B'))
                        fig.update_layout(polar=dict(
                            radialaxis=dict(visible=True, range=[0, max(140, df_radar['Indice_100'].max() + 10)])),
                                          showlegend=True, height=380, margin=dict(t=20, b=20, l=40, r=40),
                                          paper_bgcolor="rgba(0,0,0,0)")
                        st.plotly_chart(fig, use_container_width=True)
                    with col_k:
                        st.markdown("#### Points Clés")
                        for _, row in df_radar.iterrows():
                            delta = row['Indice_100'] - 100
                            if abs(delta) > 5:
                                icon = "🟢" if delta > 0 else "🔴"
                                txt_val = f"{row['Zone']:,.0f} €" if "Revenu" in row[
                                    'Metrique'] else f"{row['Zone']:.1f}%"
                                st.metric(label=f"{icon} {row['Metrique']}", value=txt_val, delta=f"{delta:+.0f} pts")
                else:
                    st.warning("Pas de données croisées.")
            else:
                st.info("Sélectionnez des critères.")

    # --- ONGLET 2 : IMMOBILIER ---
    with tab_immo:
        st.header(f"Transactions : {dvf_type_choix}")
        if df_dvf_visuel is not None and not df_dvf_visuel.empty:
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Volume", f"{len(df_dvf_visuel)}")
            k2.metric("Prix/m² Médian", f"{df_dvf_visuel['prix_m2'].median():,.0f} €".replace(',', ' '))
            k3.metric("Surface Moy.", f"{df_dvf_visuel['surface_reelle_bati'].mean():.0f} m²")
            k4.metric("Prix Total Moy.", f"{df_dvf_visuel['valeur_fonciere'].median():,.0f} €".replace(',', ' '))

            st.subheader("Liste des ventes")
            cols_safe = ['date_mutation', 'valeur_fonciere', 'prix_m2', 'surface_reelle_bati', 'type_local']
            st.dataframe(df_dvf_visuel[cols_safe].sort_values('date_mutation', ascending=False).head(50),
                         use_container_width=True)
        else:
            st.info("Activez DVF ou changez de zone.")

    # --- ONGLET 3 : TECHNIQUE ---
    with tab_tech:
        st.header("Risques & Bâti")
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("🏢 Bâtiments")
            if not gdf_batiments_final.empty:
                st.success(f"{len(gdf_batiments_final)} bâtiments détectés.")
                st.metric("Emprise Sol Totale", f"{gdf_batiments_final['surface_m2'].sum():,.0f} m²")
            else:
                st.info("Activez 'Bâtiments' dans la Sidebar et choisissez un mode Zone.")
        with c2:
            st.subheader("⚠️ Risques")
            if not gdf_inondations_a_afficher.empty:
                st.error(f"INONDATION : {', '.join(gdf_inondations_a_afficher['NIVEAU_ALEA'].unique())}")
            else:
                st.success("Pas de risque inondation (TRI).")

            if not gdf_rga_a_afficher.empty:
                st.warning(f"SÉCHERESSE : {', '.join(gdf_rga_a_afficher['NIVEAU_ALEA'].unique())}")
            else:
                st.success("Pas de risque Argiles.")