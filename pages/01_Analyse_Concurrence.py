# Fichier: pages/01_Analyse_Concurrence.py

import streamlit as st
import geopandas as gpd
import pandas as pd
from streamlit_folium import st_folium
import time

# Imports des modules métiers
from fonctions_basiques import (
    charger_communes, extraction_adresse_OSM, choix_centre_OSM,
    charger_donnees_iris_socio, charger_coefficients_trafic, preparer_donnees_socio,
    charger_zones_inondables, charger_donnees_rga,
    connect_to_db
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
                                    ref_lon=None, ref_nom=None):
    """
    Affiche les KPIs, la carte et les légendes pour les résultats de concurrence.
    CORRIGÉ : Affichage propre des enseignes multiples et suppression de la flèche delta.
    """
    st.markdown("---")

    # --- BLOC KPIs (AMÉLIORÉ) ---
    nb_etablissements = len(gdf_resultats)
    zone_info = "Zone Large"

    # Tentative de trouver la zone principale
    if 'ville' in gdf_resultats.columns:
        top_ville = gdf_resultats['ville'].mode()
        if not top_ville.empty:
            zone_info = top_ville[0]
    elif 'nom_dep' in gdf_resultats.columns:
        zone_info = gdf_resultats['nom_dep'].iloc[0]

    # Calcul intelligent du critère affiché
    valeur_source = "N/A"
    full_list_tooltip = ""
    label_source = "Critère"

    if not gdf_resultats.empty:
        if source_name == "OSM":
            label_source = "Enseigne(s)"
            # Liste unique des enseignes
            enseignes_uniques = gdf_resultats['nom_etablissement'].unique()
            nb_enseignes = len(enseignes_uniques)
            full_list_tooltip = ", ".join(enseignes_uniques)

            # Affichage "Intelligent" pour éviter le texte coupé
            if nb_enseignes == 1:
                valeur_source = enseignes_uniques[0]
            else:
                # Ex: "Carrefour (+2 autres)"
                valeur_source = f"{enseignes_uniques[0]} (+{nb_enseignes - 1})"

        else:  # SIREN
            label_source = "Code NAF"
            valeur_source = gdf_resultats.iloc[0]['activiteprincipaleetablissement']
            full_list_tooltip = f"Code activité : {valeur_source}"

    # Affichage des métriques
    kpi1, kpi2, kpi3 = st.columns(3)

    with kpi1:
        st.metric(
            label="Établissements Trouvés",
            value=f"{nb_etablissements}",
            # SUPPRESSION DU DELTA (plus de flèche)
            help="Nombre total d'établissements trouvés correspondant à vos critères."
        )

    with kpi2:
        st.metric(
            label="Zone Principale",
            value=zone_info,
            delta_color="off",
            help="La commune ou le département où se concentrent les résultats."
        )

    with kpi3:
        st.metric(
            label=label_source,
            value=valeur_source,
            help=f"Détail : {full_list_tooltip}"  # La liste complète est ici au survol
        )

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
            for nom, color in legend_enseignes.items():
                if list(legend_enseignes.keys()).index(nom) < 10:
                    st.markdown(f'<span style="color:{color}; font-size:22px;">●</span> {nom}', unsafe_allow_html=True)
            if len(legend_enseignes) > 10:
                st.write("...")

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

dict_geodatas = preparer_donnees_socio(df_iris_base, df_communes)

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

    if st.session_state.get('etab_concurrence_details'):
        details = st.session_state.etab_concurrence_details
        ref_lat = details.get('latitude')
        ref_lon = details.get('longitude')
        ref_nom = details.get('denominationunitelegale', "Votre Établissement")

    if not gdf_concurrents.empty:
        if st.checkbox("Afficher le détail des concurrents SIREN (tableau)", value=True, key="details_table_siren"):
            cols_to_show = [
                'denominationunitelegale', 'siret', 'siren', 'adresse',
                'activiteprincipaleetablissement', 'intitules_naf_vf'
            ]
            cols_existantes = [col for col in cols_to_show if col in gdf_concurrents.columns]
            st.dataframe(gdf_concurrents[cols_existantes])

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
            ref_nom=ref_nom
        )