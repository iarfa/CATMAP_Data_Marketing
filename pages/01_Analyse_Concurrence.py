# Fichier: pages/01_Analyse_Concurrence.py

import streamlit as st
import geopandas as gpd
import pandas as pd
from streamlit_folium import st_folium
import plotly.graph_objects as go
import time

# Imports des modules métiers
from fonctions_basiques import (
    charger_communes, extraction_adresse_OSM, choix_centre_OSM,
    charger_donnees_iris_socio, charger_coefficients_trafic, preparer_donnees_socio,
    charger_zones_inondables, charger_donnees_rga,
    connect_to_db,
    calculer_stats_anciennete,
    calculer_comparatif_radar
)
from fonctions_cartographie import (
    transfo_geodataframe, creer_carte_enrichie, rechercher_poi_osm
)
from interface import (
    interface_recherche_osm, interface_selection_socio,
    interface_selection_poi, POI_CONFIG,
    interface_selection_risques,
    interface_recherche_concurrence
)

# =============================================================================
# CONFIGURATION & CHEMINS
# =============================================================================

# Chemins relatifs
PATH_COMMUNES = "data/Communes_France_Metro.xlsx"
PATH_IRIS_SOCIO = "data/iris_socio_data_final.parquet"
PATH_COEFF_TRAFIC = "data/coefficient_temps_trajet.xlsx"
PATH_ZONES_INONDABLES = "data/zones_inondables_v2.parquet"
PATH_RGA_SECHERESSE = "data/rga_secheresse_v2.parquet"


# =============================================================================
# HELPERS LOCAUX
# =============================================================================

def _preparer_et_filtrer_gdf_risque(gdf_source, nom_risque, risque_selectionne, regions_filtrees, departements_filtres):
    """Filtre un GeoDataFrame de risque en fonction de la sélection de l'utilisateur."""
    if risque_selectionne != nom_risque or gdf_source.empty:
        return gpd.GeoDataFrame()

    if 'NOM_DEP' in gdf_source.columns and 'Num_Dep' in gdf_source.columns:
        gdf_source['affichage_dep'] = gdf_source['Num_Dep'] + " - " + gdf_source['NOM_DEP'].str.upper()
    else:
        pass

    if regions_filtrees:
        if 'NOM_REG' in gdf_source.columns:
            return gdf_source[gdf_source['NOM_REG'].isin(regions_filtrees)]
    elif departements_filtres:
        if 'affichage_dep' in gdf_source.columns:
            return gdf_source[gdf_source['affichage_dep'].isin(departements_filtres)]

    return gdf_source


def _afficher_resultats_concurrence(gdf_resultats, source_name, df_coefficients, gdf_socio_filtre, indicateur,
                                    nom_indicateur, poi_selectionnes_sidebar, gdf_inondations, gdf_rga, ref_lat=None,
                                    ref_lon=None, ref_nom=None,
                                    engine=None, code_naf=None, scope=None, scope_value=None, ville_ref=None):
    """
    Affiche les KPIs, la carte et les légendes pour les résultats de concurrence.
    CORRIGÉ : N'affiche l'ancienneté QUE si on est en mode SIREN.
    """
    st.markdown("---")

    # --- BLOC KPIs ---
    nb_etablissements = len(gdf_resultats)
    zone_info = "Zone Large"

    # --- CORRECTION : Détection intelligente du nom de la zone ---
    if 'ville' in gdf_resultats.columns:
        top_ville = gdf_resultats['ville'].mode()
        if not top_ville.empty:
            zone_info = top_ville[0]
    elif 'nom_dep' in gdf_resultats.columns:
        top_dep = gdf_resultats['nom_dep'].mode()
        if not top_dep.empty:
            zone_info = top_dep[0]
    # Fallback si pas de colonne standard (ex: données brutes)
    elif 'adresse' in gdf_resultats.columns:
        try:
            # On tente d'extraire la ville de la première adresse
            adresse_sample = gdf_resultats['adresse'].iloc[0]
            import re
            match = re.search(r'\b[0-9]{5}\b\s+(.*)', str(adresse_sample))
            if match:
                zone_info = match.group(1).strip().upper()
        except:
            pass

    # Calcul intelligent du critère affiché
    valeur_source = "N/A"
    full_list_tooltip = ""
    label_source = "Critère"

    if not gdf_resultats.empty:
        if source_name == "OSM":
            label_source = "Enseigne(s)"
            enseignes_uniques = gdf_resultats['nom_etablissement'].unique()
            nb_enseignes = len(enseignes_uniques)
            full_list_tooltip = ", ".join(enseignes_uniques)

            if nb_enseignes == 1:
                valeur_source = enseignes_uniques[0]
            else:
                valeur_source = f"{enseignes_uniques[0]} (+{nb_enseignes - 1})"

        else:  # SIREN
            label_source = "Code NAF"
            valeur_source = gdf_resultats.iloc[0]['activiteprincipaleetablissement']
            full_list_tooltip = f"Code activité : {valeur_source}"

    # Calcul de l'ancienneté (Uniquement si SIREN et paramètres dispo)
    age_moyen_display = None
    age_help = ""

    if source_name == "SIREN" and engine and code_naf:
        stats_age = calculer_stats_anciennete(engine, code_naf, scope, scope_value, ville_ref)
        if stats_age:
            age_moyen_display = f"{stats_age['age_moyen']} ans"
            age_help = (f"Moyenne : {stats_age['age_moyen']} ans\n"
                        f"Médiane : {stats_age['age_median']} ans\n"
                        f"Plus vieux : {stats_age['plus_vieux']} ans")

    # --- Affichage DYNAMIQUE des métriques (3 ou 4 colonnes) ---

    if age_moyen_display:
        # Mode SIREN (4 colonnes)
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    else:
        # Mode OSM (3 colonnes, on centre un peu mieux)
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi4 = None  # Pas de 4ème colonne

    with kpi1:
        st.metric(label="Établissements Trouvés", value=f"{nb_etablissements}",
                  help="Nombre total d'établissements trouvés correspondant à vos critères.")

    with kpi2:
        st.metric(label="Zone Principale", value=zone_info,
                  help="La commune ou le département où se concentrent les résultats.")

    with kpi3:
        st.metric(label=label_source, value=valeur_source, help=f"Détail : {full_list_tooltip}")

    # Affichage conditionnel de la 4ème colonne
    if kpi4 and age_moyen_display:
        with kpi4:
            st.metric(label="Ancienneté Moy.", value=age_moyen_display, help=age_help)

    st.markdown("---")
    st.subheader(f"Carte Interactive ({source_name})")

    # Centrage
    if ref_lat and ref_lon:
        lat_centre, lon_centre = ref_lat, ref_lon
    else:
        lat_centre, lon_centre = choix_centre_OSM(gdf_resultats)

    # POI
    gdf_poi_final = gpd.GeoDataFrame()
    if poi_selectionnes_sidebar:
        bounds = gdf_resultats.total_bounds
        if len(gdf_resultats) < 2 and ref_lat:
            bounds = [ref_lon - 0.05, ref_lat - 0.05, ref_lon + 0.05, ref_lat + 0.05]

        marge = 0.05
        bbox_poi = (bounds[0] - marge, bounds[1] - marge, bounds[2] + marge, bounds[3] + marge)
        with st.spinner(f"Recherche des points d'intérêt..."):
            liste_gdf_poi = [rechercher_poi_osm(bbox_poi, POI_CONFIG[cat]['tags']).assign(categorie=cat) for cat in
                             poi_selectionnes_sidebar]
            liste_gdf_poi_non_vides = [gdf for gdf in liste_gdf_poi if not gdf.empty]
            if liste_gdf_poi_non_vides:
                gdf_poi_final = pd.concat(liste_gdf_poi_non_vides, ignore_index=True)

    # Contrôles Carte
    col_ctrl1, col_ctrl2 = st.columns(2)
    with col_ctrl1:
        mode_affichage = st.radio(
            "Mode d'affichage :",
            ('Points', 'Cercles d\'influence', 'Isochrones'),
            horizontal=True,
            key=f"mode_aff_{source_name}"
        )

    rayon_cercles, temps_isochrones = 1000, 10
    with col_ctrl2:
        if mode_affichage == 'Cercles d\'influence':
            rayon_cercles = st.slider("Rayon (m) :", 100, 5000, 1000, 100, key=f"ray_{source_name}")
        elif mode_affichage == 'Isochrones':
            temps_isochrones = st.slider("Temps (min) :", 2, 20, 10, 1, key=f"tps_{source_name}")

    # Création Carte
    map_object, legend_enseignes, legend_socio_color, legend_socio_single = creer_carte_enrichie(
        gdf_etablissements=gdf_resultats,
        lat_centre=lat_centre,
        lon_centre=lon_centre,
        gdf_socio=gdf_socio_filtre,
        colonne_socio=indicateur,
        nom_indicateur_socio=nom_indicateur,
        gdf_poi=gdf_poi_final,
        gdf_inondations=gdf_inondations,
        gdf_rga=gdf_rga,
        mode_affichage_etablissements=mode_affichage,
        rayon_cercles=rayon_cercles,
        temps_isochrones=temps_isochrones,
        df_coefficients=df_coefficients,
        ref_lat=ref_lat,
        ref_lon=ref_lon,
        ref_nom=ref_nom
    )

    col_carte, col_legende = st.columns([3, 1])
    with col_carte:
        st_folium(map_object, width=800, height=600, returned_objects=[], key=f"map_{source_name}")

    with col_legende:
        st.write("**Légendes**")
        if ref_lat:
            st.markdown(f'<span style="color:red; font-size:22px;">★</span> <b>Votre Établissement</b>',
                        unsafe_allow_html=True)
            st.markdown("---")

        if legend_enseignes:
            st.write("**Enseignes / Concurrents**")
            # MODIFICATION LÉGENDE COMPACTE
            nb_items = len(legend_enseignes)
            if nb_items <= 10:
                for nom, color in legend_enseignes.items():
                    st.markdown(f'<span style="color:{color}; font-size:22px;">●</span> {nom}', unsafe_allow_html=True)
            else:
                st.info(f"{nb_items} acteurs")
                for i, (nom, color) in enumerate(legend_enseignes.items()):
                    if i < 5:
                        st.markdown(f'<span style="color:{color}; font-size:22px;">●</span> {nom}',
                                    unsafe_allow_html=True)
                with st.expander("Voir tout"):
                    for i, (nom, color) in enumerate(legend_enseignes.items()):
                        if i >= 5:
                            st.markdown(f'<span style="color:{color}; font-size:18px;">●</span> {nom}',
                                        unsafe_allow_html=True)

        if not gdf_inondations.empty:
            st.markdown("---")
            st.write("**Risque Inondation**")
            for label, color in [("Faible", "#fdbb84"), ("Moyen", "#e34a33"), ("Fort", "#b30000")]:
                st.markdown(f'<span style="color:{color}; font-size:22px;">●</span> Aléa {label}',
                            unsafe_allow_html=True)
        elif not gdf_rga.empty:
            st.markdown("---")
            st.write("**Risque Sécheresse**")
            for label, color in [("Faible", "#fee6ce"), ("Moyen", "#fd8d3c"), ("Fort", "#d95f02")]:
                st.markdown(f'<span style="color:{color}; font-size:22px;">●</span> Aléa {label}',
                            unsafe_allow_html=True)

        if legend_socio_color or legend_socio_single:
            st.markdown("---")
            if legend_socio_color:
                st.write(f"**{legend_socio_color.caption}**")
                gradient_hex = [legend_socio_color(x) for x in legend_socio_color.index]
                st.markdown(
                    f'<div style="height: 25px; border: 1px solid #ccc; border-radius: 5px; background: linear-gradient(to right, {", ".join(gradient_hex)});"/>',
                    unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                c1.caption(f"{legend_socio_color.vmin:,.0f}".replace(",", " "))
                c2.caption(f"{legend_socio_color.vmax:,.0f}".replace(",", " "), help="Max")
            elif legend_socio_single:
                st.write(f"**{legend_socio_single['label']}**")
                st.markdown(f"Val: **{legend_socio_single['value']:,.0f}**")

    # =========================================================
    # NOUVEAU : ANALYSE DU PROFIL TYPE (RADAR)
    # =========================================================
    if not gdf_resultats.empty and 'dict_geodatas' in st.session_state and 'IRIS' in st.session_state['dict_geodatas']:

        st.markdown("---")
        st.subheader("🧬 Profil Type de la Clientèle Ciblée")

        with st.container(border=True):
            col_info, col_slider = st.columns([2, 1])
            with col_info:
                st.info("Ce radar analyse le profil sociologique moyen autour des concurrents affichés.")

            # CORRECTION : Gestion du slider sans rechargement total (pas de st.form nécessaire ici car tout est recalculé vite)
            # On met une clé unique pour éviter les conflits
            with col_slider:
                rayon_km = st.slider(
                    "Rayon d'analyse (km) :",
                    min_value=1, max_value=20, value=3,
                    key=f"slider_radar_{source_name}"
                )

            try:
                # 1. Création de la "Zone des Concurrents" (Union des buffers)
                gdf_buffers = gdf_resultats.to_crs("EPSG:2154").buffer(rayon_km * 1000)
                zone_globale_concurrents = gdf_buffers.unary_union  # Fusion

                # Conversion en GeoDataFrame GPS
                zone_analyse_geom = gpd.GeoDataFrame(geometry=[zone_globale_concurrents], crs="EPSG:2154").to_crs(
                    "EPSG:4326").geometry.iloc[0]

                # 2. Calcul du Radar
                dict_geo = st.session_state['dict_geodatas']
                metriques_concurrence = ["Revenus", "Jeunes", "Actifs", "Seniors", "Cadres", "Ouvriers"]

                # Appel de la fonction
                df_radar, nom_dept_ref = calculer_comparatif_radar(
                    dict_geo['IRIS'],
                    zone_analyse_geom,
                    metriques_demandees=metriques_concurrence
                )

                if df_radar is not None and not df_radar.empty:
                    col_g, col_k = st.columns([1.5, 1])
                    with col_g:
                        fig = go.Figure()
                        # Ref
                        fig.add_trace(go.Scatterpolar(
                            r=[100] * len(df_radar),
                            theta=df_radar['Metrique'],
                            fill=None,
                            name=f"Moyenne Locale",
                            line_color='gray',
                            line_dash='dot',
                            hoverinfo='skip'
                        ))
                        # Zone
                        fig.add_trace(go.Scatterpolar(
                            r=df_radar['Indice_100'],
                            theta=df_radar['Metrique'],
                            fill='toself',
                            name=f'Cible ({rayon_km}km)',
                            line_color='#E63946'
                        ))

                        fig.update_layout(
                            polar=dict(
                                radialaxis=dict(visible=True, range=[0, max(140, df_radar['Indice_100'].max() + 10)])),
                            showlegend=True,
                            height=350,
                            margin=dict(t=10, b=10, l=40, r=40),
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)"
                        )
                        st.plotly_chart(fig, use_container_width=True)

                    with col_k:
                        st.markdown(f"#### Comparaison vs {nom_dept_ref}")
                        st.caption("Sur-représentation significative")
                        for _, row in df_radar.iterrows():
                            delta = row['Indice_100'] - 100
                            if delta > 10:
                                st.metric(f"🎯 {row['Metrique']}", f"+{delta:.0f}%", "Forte")
                            elif delta < -10:
                                st.metric(f"🚫 {row['Metrique']}", f"{delta:.0f}%", "Faible")
                else:
                    st.warning(f"Pas assez de données IRIS dans un rayon de {rayon_km}km.")

            except Exception as e:
                st.error(f"Erreur lors du profilage : {e}")


# =============================================================================
# MAIN EXECUTION
# =============================================================================

st.title("📊 Analyse de la Concurrence")

engine = connect_to_db()

with st.spinner("Chargement des référentiels..."):
    df_communes = charger_communes(PATH_COMMUNES)
    gdf_inondations = charger_zones_inondables(PATH_ZONES_INONDABLES)
    gdf_rga = charger_donnees_rga(PATH_RGA_SECHERESSE)
    df_iris_base = charger_donnees_iris_socio(PATH_IRIS_SOCIO)
    df_coefficients = charger_coefficients_trafic(PATH_COEFF_TRAFIC)

# Stockage Session (Pour éviter de recharger les IRIS à chaque interaction)
if 'dict_geodatas' not in st.session_state:
    st.session_state['dict_geodatas'] = preparer_donnees_socio(df_iris_base, df_communes)
dict_geodatas = st.session_state['dict_geodatas']

gdf_socio_filtre, indicateur, nom_indicateur, maille = interface_selection_socio(dict_geodatas)
risque_selectionne, regions_filtrees, departements_filtres = interface_selection_risques(df_communes)
poi_selectionnes_sidebar = interface_selection_poi()

gdf_inondations_a_afficher = _preparer_et_filtrer_gdf_risque(
    gdf_inondations, "Inondations", risque_selectionne, regions_filtrees, departements_filtres
)
gdf_rga_a_afficher = _preparer_et_filtrer_gdf_risque(
    gdf_rga, "Sécheresse (RGA)", risque_selectionne, regions_filtrees, departements_filtres
)

subtab_osm, subtab_siren = st.tabs(["🔍 Par Enseigne (OSM)", "🏢 Par Activité (SIREN)"])

# --- SOUS-ONGLET 1 : OpenStreetMap ---
with subtab_osm:
    st.info(
        "Rechercher des enseignes par leur nom (ex: 'Lidl', 'Carrefour') dans une zone géographique via OpenStreetMap.")
    df_etablissements_osm = interface_recherche_osm(df_communes, key_prefix="concurrence_osm")

    gdf_osm_final = gpd.GeoDataFrame()
    if not df_etablissements_osm.empty:
        df_etablissements_osm[["adresse_simplifiee", "precision_geocodage"]] = df_etablissements_osm.apply(
            extraction_adresse_OSM, axis=1)
        gdf_osm_final = transfo_geodataframe(df_etablissements_osm, "longitude", "latitude")

        _afficher_resultats_concurrence(
            gdf_resultats=gdf_osm_final,
            source_name="OSM",
            df_coefficients=df_coefficients,
            gdf_socio_filtre=gdf_socio_filtre,
            indicateur=indicateur,
            nom_indicateur=nom_indicateur,
            poi_selectionnes_sidebar=poi_selectionnes_sidebar,
            gdf_inondations=gdf_inondations_a_afficher,
            gdf_rga=gdf_rga_a_afficher,
            ref_lat=None, ref_lon=None, ref_nom=None
        )

# --- SOUS-ONGLET 2 : Base SIREN ---
with subtab_siren:
    st.info("Trouver des concurrents ayant le même code NAF qu'un établissement de référence.")
    gdf_concurrents = interface_recherche_concurrence(engine)

    ref_lat = None
    ref_lon = None
    ref_nom = "Votre Établissement"

    # Variables pour le calcul de l'ancienneté
    code_naf = None
    scope = None
    scope_value = None
    ville_ref = None

    if st.session_state.get('etab_concurrence_details'):
        details = st.session_state.etab_concurrence_details
        ref_lat = details.get('latitude')
        ref_lon = details.get('longitude')
        ref_nom = details.get('denominationunitelegale', "Votre Établissement")

        # Récupération robuste des paramètres pour le calcul SQL
        code_naf = details.get('activiteprincipaleetablissement')
        scope_value = details.get('numero_dep')
        from fonctions_basiques import extraire_ville_depuis_adresse

        ville_ref = extraire_ville_depuis_adresse(details.get('adresse', ''))

        scope_widget = st.session_state.get('concurrence_scope', '')
        scope = "Ville" if "Ville" in scope_widget else "Département"

    if not gdf_concurrents.empty:
        if st.checkbox("Afficher le détail des concurrents SIREN (tableau)", value=True, key="details_table_siren"):
            cols_to_show = [
                'denominationunitelegale', 'siret', 'siren', 'adresse',
                'activiteprincipaleetablissement', 'intitules_naf_vf'
            ]
            cols_existantes = [col for col in cols_to_show if col in gdf_concurrents.columns]
            st.dataframe(gdf_concurrents[cols_existantes])

        # APPEL AVEC TOUS LES ARGUMENTS POUR LE CALCUL (Mode SIREN = 4 colonnes)
        _afficher_resultats_concurrence(
            gdf_resultats=gdf_concurrents,
            source_name="SIREN",
            df_coefficients=df_coefficients,
            gdf_socio_filtre=gdf_socio_filtre,
            indicateur=indicateur,
            nom_indicateur=nom_indicateur,
            poi_selectionnes_sidebar=poi_selectionnes_sidebar,
            gdf_inondations=gdf_inondations_a_afficher,
            gdf_rga=gdf_rga_a_afficher,
            ref_lat=ref_lat,
            ref_lon=ref_lon,
            ref_nom=ref_nom,
            # Nouveaux args pour SQL
            engine=engine,
            code_naf=code_naf,
            scope=scope,
            scope_value=scope_value,
            ville_ref=ville_ref
        )