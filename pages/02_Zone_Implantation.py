# Fichier: pages/02_Zone_Implantation.py

import streamlit as st
import geopandas as gpd
import pandas as pd
from streamlit_folium import st_folium
from shapely.geometry import Point, shape

# Imports Métiers
from fonctions_basiques import (
    charger_communes, charger_donnees_iris_socio, charger_coefficients_trafic,
    preparer_donnees_socio, charger_zones_inondables, charger_donnees_rga,
    connect_to_db
)
from fonctions_cartographie import (
    creer_carte_implantation, calculer_isochrone_et_cacher,
    rechercher_poi_osm, rechercher_batiments_osm,
    geocoder_adresse_nominatim_ui
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
PATH_COEFF_TRAFIC = "data/coefficient_temps_trajet.xlsx"
PATH_ZONES_INONDABLES = "data/zones_inondables_v2.parquet"
PATH_RGA_SECHERESSE = "data/rga_secheresse_v2.parquet"


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

dict_geodatas = preparer_donnees_socio(df_iris_base, df_communes)

# --- SIDEBAR ---
gdf_socio_filtre, indicateur, nom_indicateur, maille = interface_selection_socio(dict_geodatas)
risque_selectionne, regions_filtrees, departements_filtres = interface_selection_risques(df_communes)
poi_selectionnes_sidebar = interface_selection_poi()

gdf_inondations_a_afficher = _preparer_et_filtrer_gdf_risque(gdf_inondations, "Inondations", risque_selectionne, regions_filtrees, departements_filtres)
gdf_rga_a_afficher = _preparer_et_filtrer_gdf_risque(gdf_rga, "Sécheresse (RGA)", risque_selectionne, regions_filtrees, departements_filtres)

# --- Interface Principale ---

gdf_batiments_final = gpd.GeoDataFrame()
afficher_batiments, surface_min, surface_max = interface_selection_batiments()

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

# --- Calculs et Affichage ---

if final_lat and final_lon:
    temps_isochrones = 5
    if mode == 'Isochrones':
        temps_isochrones = st.slider(
            "Temps de trajet (min) :",
            min_value=2, max_value=20, value=5, step=1,
            key="temps_implantation"
        )

    zone_analyse_geom = None
    if mode == 'Isochrones':
        temps_secondes_ajuste = temps_isochrones * 60 * 0.9
        feature = calculer_isochrone_et_cacher(final_lon, final_lat, temps_secondes_ajuste)
        if feature:
            zone_analyse_geom = shape(feature['geometry'])

    elif mode == "Cercle d'influence":
        poi_point_gdf = gpd.GeoDataFrame(geometry=[Point(final_lon, final_lat)], crs="EPSG:4326")
        zone_analyse_geom_reproj = poi_point_gdf.to_crs("EPSG:3857").buffer(radius).iloc[0]
        zone_analyse_geom = gpd.GeoDataFrame(geometry=[zone_analyse_geom_reproj], crs="EPSG:3857").to_crs("EPSG:4326").geometry.iloc[0]

    # Recherche POI
    gdf_poi_trouves = gpd.GeoDataFrame()
    if zone_analyse_geom and poi_selectionnes_sidebar:
        bbox = zone_analyse_geom.bounds
        with st.spinner("Recherche des points d'intérêt..."):
            liste_gdf_poi = [rechercher_poi_osm(bbox, POI_CONFIG[cat]['tags']).assign(categorie=cat) for cat in poi_selectionnes_sidebar]
            liste_gdf_poi_non_vides = [gdf for gdf in liste_gdf_poi if not gdf.empty]
            if liste_gdf_poi_non_vides:
                gdf_poi_brut = pd.concat(liste_gdf_poi_non_vides, ignore_index=True)
                if not gdf_poi_brut.empty:
                    gdf_poi_trouves = gdf_poi_brut[gdf_poi_brut.within(zone_analyse_geom)]
                    st.info(f"{len(gdf_poi_trouves)} point(s) d'intérêt trouvé(s).")

    # Recherche Bâtiments
    if afficher_batiments:
        if zone_analyse_geom is None:
            st.warning("⚠️ Impossible d'afficher les bâtiments en mode 'Point seul'. Veuillez choisir 'Cercle d'influence' ou 'Isochrones'.")
        else:
            bbox_batiments = zone_analyse_geom.bounds
            with st.spinner("Recherche des bâtiments (OSM)..."):
                gdf_batiments_brut = rechercher_batiments_osm(bbox_batiments)

            if not gdf_batiments_brut.empty:
                gdf_batiments_filtres_surface = gdf_batiments_brut[
                    (gdf_batiments_brut['surface_m2'] >= surface_min) &
                    (gdf_batiments_brut['surface_m2'] <= surface_max)
                    ]
                if not gdf_batiments_filtres_surface.empty:
                    gdf_batiments_final = gdf_batiments_filtres_surface[
                        gdf_batiments_filtres_surface.within(zone_analyse_geom)
                    ]
                    if not gdf_batiments_final.empty:
                        st.success(f"✅ {len(gdf_batiments_final)} bâtiment(s) affiché(s).")
                    else:
                        st.warning(f"🛑 Bâtiments trouvés dans le secteur, mais aucun DANS la zone exacte.")
                else:
                    st.warning(f"🛑 Bâtiments trouvés, mais aucun entre {surface_min} et {surface_max} m².")

    # Affichage Carte
    st.markdown("---")
    st.subheader("Carte Interactive de la Zone")

    map_object, legend_socio_color, legend_socio_single = creer_carte_implantation(
        lat_centre=final_lat, lon_centre=final_lon,
        zone_analyse_geom=zone_analyse_geom,
        gdf_poi_trouves=gdf_poi_trouves,
        gdf_socio=gdf_socio_filtre,
        colonne_socio=indicateur, nom_indicateur_socio=nom_indicateur,
        gdf_batiments=gdf_batiments_final,
        gdf_inondations=gdf_inondations_a_afficher, gdf_rga=gdf_rga_a_afficher,
        nom_point_central=final_nom,
        adresse_point_central=final_adresse_str,
        analysis_mode=mode
    )

    col_carte, col_legende = st.columns([3, 1])
    with col_carte:
        st_folium(map_object, width=800, height=600, returned_objects=[])
    with col_legende:
        st.write("**Légendes**")
        if not gdf_inondations_a_afficher.empty:
            st.write("**Risque Inondation**")
            for label, color in [("Faible", "#fdbb84"), ("Moyen", "#e34a33"), ("Fort", "#b30000")]:
                st.markdown(f'<span style="color:{color}; font-size:22px;">●</span> Aléa {label}', unsafe_allow_html=True)
        elif not gdf_rga_a_afficher.empty:
            st.write("**Risque Sécheresse**")
            for label, color in [("Faible", "#fee6ce"), ("Moyen", "#fd8d3c"), ("Fort", "#d95f02")]:
                st.markdown(f'<span style="color:{color}; font-size:22px;">●</span> Aléa {label}', unsafe_allow_html=True)

        if legend_socio_color or legend_socio_single:
            st.markdown("---")
            if legend_socio_color:
                st.write(f"**{legend_socio_color.caption}**")
                gradient_hex = [legend_socio_color(x) for x in legend_socio_color.index]
                st.markdown(f'<div style="height: 25px; border: 1px solid #ccc; border-radius: 5px; background: linear-gradient(to right, {", ".join(gradient_hex)});"/>', unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                c1.caption(f"{legend_socio_color.vmin:,.0f}".replace(",", " "))
                c2.caption(f"{legend_socio_color.vmax:,.0f}".replace(",", " "), help="Max")
            elif legend_socio_single:
                st.write(f"**{legend_socio_single['label']}**")
                st.markdown(f"Val: **{legend_socio_single['value']:,.0f}**")

elif not result_point_central['valeur']:
    st.info("Veuillez saisir une adresse, des coordonnées ou un SIREN/SIRET pour lancer l'analyse.")