import streamlit as st
import geopandas as gpd
import pandas as pd
from streamlit_folium import st_folium
import time
from shapely.geometry import Point, shape

# Imports depuis vos modules personnalisés
from fonctions_basiques import (
    charger_communes, extraction_adresse_OSM, choix_centre_OSM,
    charger_donnees_iris_socio, charger_coefficients_trafic, preparer_donnees_socio
)
from fonctions_cartographie import (
    transfo_geodataframe, creer_carte_enrichie, rechercher_poi_osm,
    geocoder_adresse_nominatim, creer_carte_implantation, calculer_isochrone_et_cacher,
    rechercher_batiments_osm
)
from interface import (
    interface_recherche_osm, interface_selection_socio,
    interface_selection_poi, interface_point_interet, POI_CONFIG,
    interface_selection_batiments
)


# =============================================================================
# LOGIQUE DE L'ONGLET N°1 : ANALYSE DE LA CONCURRENCE
# =============================================================================
def render_tab_concurrence(df_communes, df_coefficients, gdf_socio_filtre, indicateur, nom_indicateur, maille,
                           poi_selectionnes_sidebar):
    st.subheader("Recherche d'établissements")
    df_etablissements_osm = interface_recherche_osm(df_communes, key_prefix="concurrence")

    if not df_etablissements_osm.empty:
        st.header("✔️ Résultats de l'analyse de concurrence")

        df_etablissements_osm[["adresse_simplifiee", "precision_geocodage"]] = df_etablissements_osm.apply(
            extraction_adresse_OSM, axis=1)
        lat_centre_OSM, lon_centre_OSM = choix_centre_OSM(df_etablissements_osm)
        gdf_etablissements_osm = transfo_geodataframe(df_etablissements_osm, "longitude", "latitude")

        if st.checkbox("Afficher le détail des établissements (tableau)", key="details_concurrence"):
            st.dataframe(gdf_etablissements_osm.drop(columns=['geometry']))

        gdf_poi_final = gpd.GeoDataFrame()
        if poi_selectionnes_sidebar:
            bounds = gdf_etablissements_osm.total_bounds
            marge = 0.05
            bbox_poi = (bounds[0] - marge, bounds[1] - marge, bounds[2] + marge, bounds[3] + marge)
            with st.spinner("Recherche des points d'intérêt..."):
                liste_gdf_poi = [rechercher_poi_osm(bbox_poi, POI_CONFIG[cat]['tags']).assign(categorie=cat) for cat in
                                 poi_selectionnes_sidebar]
                liste_gdf_poi_non_vides = [gdf for gdf in liste_gdf_poi if not gdf.empty]
                if liste_gdf_poi_non_vides:
                    gdf_poi_final = pd.concat(liste_gdf_poi_non_vides, ignore_index=True)
                    st.info(f"{len(gdf_poi_final)} point(s) d'intérêt trouvé(s).")

        st.markdown("---")
        st.subheader("Carte Interactive")
        mode_affichage = st.radio("Mode d'affichage des concurrents :",
                                  ('Points', 'Cercles d\'influence', 'Isochrones'), horizontal=True,
                                  label_visibility="collapsed", key="mode_concurrence")
        rayon_cercles, temps_isochrones = None, 10
        if mode_affichage == 'Cercles d\'influence':
            rayon_cercles = st.slider("Rayon (m) :", 100, 5000, 1000, 100, key="rayon_concurrence")
        elif mode_affichage == 'Isochrones':
            temps_isochrones = st.slider("Temps de trajet (min) :", 2, 20, 10, 1, key="temps_concurrence")

        map_object, legend_enseignes, _, _ = creer_carte_enrichie(
            gdf_etablissements=gdf_etablissements_osm, lat_centre=lat_centre_OSM, lon_centre=lon_centre_OSM,
            gdf_socio=gdf_socio_filtre, colonne_socio=indicateur, nom_indicateur_socio=nom_indicateur,
            gdf_poi=gdf_poi_final, mode_affichage_etablissements=mode_affichage, rayon_cercles=rayon_cercles,
            temps_isochrones=temps_isochrones, df_coefficients=df_coefficients
        )

        st_folium(map_object, width=800, height=600, returned_objects=[])


# =============================================================================
# LOGIQUE DE L'ONGLET N°2 : ANALYSE D'UNE ZONE D'IMPLANTATION
# =============================================================================
def render_tab_implantation(gdf_socio_filtre, indicateur, nom_indicateur, maille, poi_selectionnes_sidebar):
    # Le contrôle des bâtiments est maintenant local à cet onglet
    afficher_batiments, surface_min, surface_max = interface_selection_batiments()

    address, lat, lon, mode, radius = interface_point_interet()

    final_lat, final_lon = (lat, lon)
    if address:
        final_lat, final_lon = geocoder_adresse_nominatim(address)

    if final_lat and final_lon:
        st.header("✔️ Résultats de l'analyse de zone")
        temps_isochrones = st.slider("Temps de trajet pour l'isochrone (min) :", 2, 20, 10, 1,
                                     key="temps_implantation") if mode == 'Isochrones' else 10

        zone_analyse_geom = None
        if mode == 'Isochrones':
            feature = calculer_isochrone_et_cacher(final_lon, final_lat, temps_isochrones * 60 * 0.9)
            if feature and 'geometry' in feature:
                zone_analyse_geom = shape(feature['geometry'])
        else:  # Mode Cercle
            poi_point_gdf = gpd.GeoDataFrame(geometry=[Point(final_lon, final_lat)], crs="EPSG:4326")
            poi_reproj = poi_point_gdf.to_crs("EPSG:3857")
            zone_analyse_geom = poi_reproj.buffer(radius).iloc[0]
            zone_analyse_geom = \
            gpd.GeoDataFrame(geometry=[zone_analyse_geom], crs="EPSG:3857").to_crs("EPSG:4326").geometry.iloc[0]

        gdf_poi_trouves = gpd.GeoDataFrame()
        if zone_analyse_geom and poi_selectionnes_sidebar:
            bbox = zone_analyse_geom.bounds
            with st.spinner("Recherche des points d'intérêt dans la zone..."):
                liste_gdf_poi = [rechercher_poi_osm(bbox, POI_CONFIG[cat]['tags']).assign(categorie=cat) for cat in
                                 poi_selectionnes_sidebar]
                if liste_gdf_poi:
                    liste_gdf_poi_non_vides = [gdf for gdf in liste_gdf_poi if not gdf.empty]
                    if liste_gdf_poi_non_vides:
                        gdf_poi_brut = pd.concat(liste_gdf_poi_non_vides, ignore_index=True)
                        if not gdf_poi_brut.empty:
                            gdf_poi_trouves = gdf_poi_brut[gdf_poi_brut.within(zone_analyse_geom)]
                            st.info(f"{len(gdf_poi_trouves)} point(s) d'intérêt trouvé(s) dans la zone.")

        gdf_batiments_final = gpd.GeoDataFrame()
        if afficher_batiments and zone_analyse_geom:
            bbox_batiments = zone_analyse_geom.bounds
            gdf_batiments_brut = rechercher_batiments_osm(bbox_batiments)
            if not gdf_batiments_brut.empty:
                gdf_batiments_final = gdf_batiments_brut[(gdf_batiments_brut['surface_m2'] >= surface_min) & (
                            gdf_batiments_brut['surface_m2'] <= surface_max)]
                gdf_batiments_final = gdf_batiments_final[gdf_batiments_final.within(zone_analyse_geom)]
                st.info(f"{len(gdf_batiments_final)} bâtiment(s) correspondant à vos critères de surface affiché(s).")

        st.markdown("---")
        st.subheader("Carte Interactive de la Zone")
        map_object = creer_carte_implantation(
            lat_centre=final_lat, lon_centre=final_lon, zone_analyse_geom=zone_analyse_geom,
            gdf_poi_trouves=gdf_poi_trouves, gdf_socio=gdf_socio_filtre,
            colonne_socio=indicateur, nom_indicateur_socio=nom_indicateur,
            gdf_batiments=gdf_batiments_final
        )
        st_folium(map_object, width=800, height=600, returned_objects=[])


# =============================================================================
# FONCTION PRINCIPALE DE LA PAGE
# =============================================================================
def page_osm(path_communes, path_iris_socio, path_coeff_trafic):
    st.title("🗺️ Analyse Concurrentielle via OpenStreetMap")

    with st.spinner("Chargement des données initiales..."):
        df_coefficients = charger_coefficients_trafic(path_coeff_trafic)
        df_communes = charger_communes(path_communes)
        df_iris_base = charger_donnees_iris_socio(path_iris_socio)

    dict_geodatas = preparer_donnees_socio(df_iris_base, df_communes)

    gdf_socio_filtre, indicateur, nom_indicateur, maille = interface_selection_socio(dict_geodatas)
    poi_selectionnes_sidebar = interface_selection_poi()

    st.header("🚀 Choisissez votre mode d'analyse")

    tab_concurrence, tab_implantation = st.tabs([
        "Analyser la concurrence dans une zone",
        "Analyser une nouvelle zone d'implantation"
    ])

    with tab_concurrence:
        render_tab_concurrence(df_communes, df_coefficients, gdf_socio_filtre, indicateur, nom_indicateur, maille,
                               poi_selectionnes_sidebar)

    with tab_implantation:
        render_tab_implantation(gdf_socio_filtre, indicateur, nom_indicateur, maille, poi_selectionnes_sidebar)