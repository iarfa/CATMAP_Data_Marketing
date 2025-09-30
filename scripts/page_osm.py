import streamlit as st
import geopandas as gpd
import pandas as pd
from streamlit_folium import st_folium
import time
from shapely.geometry import Point, shape

# Imports depuis les modules
from fonctions_basiques import (
    charger_communes, extraction_adresse_OSM, choix_centre_OSM,
    charger_donnees_iris_socio, charger_coefficients_trafic, preparer_donnees_socio,
    charger_zones_inondables, charger_donnees_rga, enrichir_donnees_risques_avec_num_dep
)
from fonctions_cartographie import (
    transfo_geodataframe, creer_carte_enrichie, rechercher_poi_osm,
    geocoder_adresse_nominatim, creer_carte_implantation, calculer_isochrone_et_cacher,
    rechercher_batiments_osm
)
from interface import (
    interface_recherche_osm, interface_selection_socio,
    interface_selection_poi, interface_point_interet, POI_CONFIG,
    interface_selection_batiments, interface_selection_risques
)


# =============================================================================
# LOGIQUE DE L'ONGLET N°1 : ANALYSE DE LA CONCURRENCE
# =============================================================================
def render_tab_concurrence(df_communes, df_coefficients, gdf_socio_filtre, indicateur, nom_indicateur, maille,
                           poi_selectionnes_sidebar, gdf_inondations, gdf_rga):
    st.subheader("Recherche d'établissements")
    df_etablissements_osm = interface_recherche_osm(df_communes, key_prefix="concurrence")

    if not df_etablissements_osm.empty:
        st.header("Résultats de l'analyse de concurrence")
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

        rayon_cercles, temps_isochrones = 1000, 10
        if mode_affichage == 'Cercles d\'influence':
            rayon_cercles = st.slider("Rayon (m) :", 100, 5000, 1000, 100, key="rayon_concurrence")
        elif mode_affichage == 'Isochrones':
            temps_isochrones = st.slider("Temps de trajet (min) :", 2, 20, 10, 1, key="temps_concurrence")

        ### CORRECTION : Ajout des paramètres manquants dans l'appel de la fonction ###
        map_object, legend_enseignes, legend_socio_color, legend_socio_single = creer_carte_enrichie(
            gdf_etablissements=gdf_etablissements_osm,
            lat_centre=lat_centre_OSM,
            lon_centre=lon_centre_OSM,
            gdf_socio=gdf_socio_filtre,
            colonne_socio=indicateur,
            nom_indicateur_socio=nom_indicateur,
            gdf_poi=gdf_poi_final,
            gdf_inondations=gdf_inondations,
            gdf_rga=gdf_rga,
            # Les paramètres ci-dessous avaient été oubliés :
            mode_affichage_etablissements=mode_affichage,
            rayon_cercles=rayon_cercles,
            temps_isochrones=temps_isochrones,
            df_coefficients=df_coefficients
        )

        col_carte, col_legende = st.columns([3, 1])
        with col_carte:
            st_folium(map_object, width=800, height=600, returned_objects=[])
        with col_legende:
            st.write("**Légendes**")
            if legend_enseignes:
                st.write("**Enseignes**")
                for nom, color in legend_enseignes.items():
                    st.markdown(f'<span style="color:{color}; font-size:22px;">●</span> {nom}', unsafe_allow_html=True)

            if not gdf_inondations.empty:
                st.markdown("<hr style='margin:0.5em 0;'>", unsafe_allow_html=True)
                st.write("**Risque Inondation**")
                st.markdown(f'<span style="color:#fdbb84; font-size:22px;">●</span> Aléa Faible',
                            unsafe_allow_html=True)
                st.markdown(f'<span style="color:#e34a33; font-size:22px;">●</span> Aléa Moyen', unsafe_allow_html=True)
                st.markdown(f'<span style="color:#b30000; font-size:22px;">●</span> Aléa Fort', unsafe_allow_html=True)
            elif not gdf_rga.empty:
                st.markdown("<hr style='margin:0.5em 0;'>", unsafe_allow_html=True)
                st.write("**Risque Sécheresse (RGA)**")
                st.markdown(f'<span style="color:#fee6ce; font-size:22px;">●</span> Aléa Faible',
                            unsafe_allow_html=True)
                st.markdown(f'<span style="color:#fd8d3c; font-size:22px;">●</span> Aléa Moyen', unsafe_allow_html=True)
                st.markdown(f'<span style="color:#d95f02; font-size:22px;">●</span> Aléa Fort', unsafe_allow_html=True)

            if legend_socio_color or legend_socio_single:
                st.markdown("<hr style='margin:0.5em 0;'>", unsafe_allow_html=True)
            if legend_socio_color:
                st.write(f"**{legend_socio_color.caption}**")
                gradient_hex = [legend_socio_color(x) for x in legend_socio_color.index]
                st.markdown(
                    f'<div style="height: 25px; border: 1px solid #ccc; border-radius: 5px; background: linear-gradient(to right, {", ".join(gradient_hex)});"/>',
                    unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                c1.markdown(f"<small>{legend_socio_color.vmin:,.0f}".replace(",", " ") + "</small>",
                            unsafe_allow_html=True)
                c2.markdown(
                    f'<div style="text-align: right;"><small>{"{:,}".format(round(legend_socio_color.vmax)).replace(",", " ")}</small></div>',
                    unsafe_allow_html=True)
            elif legend_socio_single:
                st.write(f"**{legend_socio_single['label']}**")
                st.markdown(f"Valeur unique : **{'{:,.0f}'.format(legend_socio_single['value']).replace(',', ' ')}**")


# =============================================================================
# LOGIQUE DE L'ONGLET N°2 : ANALYSE D'UNE ZONE D'IMPLANTATION
# =============================================================================
def render_tab_implantation(gdf_socio_filtre, indicateur, nom_indicateur, maille,
                            poi_selectionnes_sidebar, gdf_inondations, gdf_rga):
    gdf_batiments_final = gpd.GeoDataFrame()

    afficher_batiments, surface_min, surface_max = interface_selection_batiments()

    address, lat, lon, mode, radius = interface_point_interet()
    final_lat, final_lon = (lat, lon)
    if address:
        final_lat, final_lon = geocoder_adresse_nominatim(address)

    if final_lat and final_lon:
        st.header("Résultats de l'analyse de zone")

        # MODIFIÉ : La valeur par défaut (value) passe de 10 à 5
        temps_isochrones = st.slider(
            "Temps de trajet (min) :",
            min_value=2,
            max_value=20,
            value=5,  # La valeur par défaut est maintenant 5
            step=1,
            key="temps_implantation"
        ) if mode == 'Isochrones' else 5

        zone_analyse_geom = None
        if mode == 'Isochrones':
            temps_secondes_ajuste = temps_isochrones * 60 * 0.9
            feature = calculer_isochrone_et_cacher(final_lon, final_lat, temps_secondes_ajuste)
            if feature:
                zone_analyse_geom = shape(feature['geometry'])
        else:
            poi_point_gdf = gpd.GeoDataFrame(geometry=[Point(final_lon, final_lat)], crs="EPSG:4326")
            poi_reproj = poi_point_gdf.to_crs("EPSG:3857")
            zone_analyse_geom_reproj = poi_reproj.buffer(radius).iloc[0]
            zone_analyse_geom = \
            gpd.GeoDataFrame(geometry=[zone_analyse_geom_reproj], crs="EPSG:3857").to_crs("EPSG:4326").geometry.iloc[0]

        gdf_poi_trouves = gpd.GeoDataFrame()
        if zone_analyse_geom and poi_selectionnes_sidebar:
            bbox = zone_analyse_geom.bounds
            with st.spinner("Recherche des points d'intérêt..."):
                liste_gdf_poi = [rechercher_poi_osm(bbox, POI_CONFIG[cat]['tags']).assign(categorie=cat) for cat in
                                 poi_selectionnes_sidebar]
                liste_gdf_poi_non_vides = [gdf for gdf in liste_gdf_poi if not gdf.empty]
                if liste_gdf_poi_non_vides:
                    gdf_poi_brut = pd.concat(liste_gdf_poi_non_vides, ignore_index=True)
                    if not gdf_poi_brut.empty:
                        gdf_poi_trouves = gdf_poi_brut[gdf_poi_brut.within(zone_analyse_geom)]
                        st.info(f"{len(gdf_poi_trouves)} point(s) d'intérêt trouvé(s).")

        if afficher_batiments and zone_analyse_geom:
            bbox_batiments = zone_analyse_geom.bounds
            with st.spinner("Recherche des bâtiments..."):
                gdf_batiments_brut = rechercher_batiments_osm(bbox_batiments)
            if not gdf_batiments_brut.empty:
                gdf_batiments_filtres_surface = gdf_batiments_brut[
                    (gdf_batiments_brut['surface_m2'] >= surface_min) &
                    (gdf_batiments_brut['surface_m2'] <= surface_max)
                    ]
                gdf_batiments_final = gdf_batiments_filtres_surface[
                    gdf_batiments_filtres_surface.within(zone_analyse_geom)]
                st.info(f"{len(gdf_batiments_final)} bâtiment(s) correspondant à vos critères.")

        st.markdown("---")
        st.subheader("Carte Interactive de la Zone")
        map_object, legend_socio_color, legend_socio_single = creer_carte_implantation(
            lat_centre=final_lat, lon_centre=final_lon, zone_analyse_geom=zone_analyse_geom,
            gdf_poi_trouves=gdf_poi_trouves, gdf_socio=gdf_socio_filtre,
            colonne_socio=indicateur, nom_indicateur_socio=nom_indicateur,
            gdf_batiments=gdf_batiments_final, gdf_inondations=gdf_inondations, gdf_rga=gdf_rga
        )
        col_carte, col_legende = st.columns([3, 1])
        with col_carte:
            st_folium(map_object, width=800, height=600, returned_objects=[])
        with col_legende:
            st.write("**Légendes**")
            # Logique d'affichage des légendes (inchangée)
            if not gdf_inondations.empty:
                st.write("**Risque Inondation**")
                # ... etc
            elif not gdf_rga.empty:
                st.write("**Risque Sécheresse (RGA)**")
                # ... etc

            if legend_socio_color or legend_socio_single:
                st.markdown("<hr style='margin:0.5em 0;'>", unsafe_allow_html=True)
            if legend_socio_color:
                st.write(f"**{legend_socio_color.caption}**")
                gradient_hex = [legend_socio_color(x) for x in legend_socio_color.index]
                st.markdown(
                    f'<div style="height: 25px; border: 1px solid #ccc; border-radius: 5px; background: linear-gradient(to right, {", ".join(gradient_hex)});"/>',
                    unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                c1.markdown(f"<small>{legend_socio_color.vmin:,.0f}".replace(",", " ") + "</small>",
                            unsafe_allow_html=True)
                c2.markdown(
                    f'<div style="text-align: right;"><small>{"{:,}".format(round(legend_socio_color.vmax)).replace(",", " ")}</small></div>',
                    unsafe_allow_html=True)
            elif legend_socio_single:
                st.write(f"**{legend_socio_single['label']}**")
                st.markdown(f"Valeur unique : **{'{:,.0f}'.format(legend_socio_single['value']).replace(',', ' ')}**")


# =============================================================================
# FONCTION PRINCIPALE DE LA PAGE
# =============================================================================
def page_osm(path_communes, path_iris_socio, path_coeff_trafic, path_zones_inondables, path_rga_secheresse):
    st.title("🗺️ Analyse Concurrentielle via OpenStreetMap")

    # --- Chargement des données ---
    with st.spinner("Chargement des données initiales..."):
        df_communes = charger_communes(path_communes)
        gdf_inondations = charger_zones_inondables(path_zones_inondables)
        gdf_rga = charger_donnees_rga(path_rga_secheresse)
        df_iris_base = gpd.read_parquet(path_iris_socio)

    dict_geodatas = preparer_donnees_socio(df_iris_base, df_communes)

    # --- Interface utilisateur ---
    gdf_socio_filtre, indicateur, nom_indicateur, maille = interface_selection_socio(dict_geodatas)
    risque_selectionne, regions_filtrees, departements_filtres = interface_selection_risques(df_communes)
    poi_selectionnes_sidebar = interface_selection_poi()

    gdf_risques_a_afficher = gpd.GeoDataFrame()

    # =================================================
    ### LOGIQUE DE FILTRAGE ROBUSTE AVEC DÉCOUPAGE ###
    # =================================================

    gdf_risques_base = None
    if risque_selectionne == "Inondations":
        gdf_risques_base = gdf_inondations
    elif risque_selectionne == "Sécheresse (RGA)":
        gdf_risques_base = gdf_rga

    if gdf_risques_base is not None and not gdf_risques_base.empty:
        gdf_a_filtrer = gdf_risques_base.copy()

        if regions_filtrees:
            gdf_risques_a_afficher = gdf_a_filtrer[gdf_a_filtrer['NOM_REG'].isin(regions_filtrees)]

        elif departements_filtres:
            codes_deps_selectionnes = [d.split(' - ')[0] for d in departements_filtres]
            polygones_preselectionnes = gdf_a_filtrer[gdf_a_filtrer['Num_Dep'].isin(codes_deps_selectionnes)]

            if not polygones_preselectionnes.empty:
                gdf_departements_socio = dict_geodatas.get("Département")
                if gdf_departements_socio is not None and not gdf_departements_socio.empty:
                    masque_departements = gdf_departements_socio[
                        gdf_departements_socio['CODE_DEPT'].isin(codes_deps_selectionnes)]

                    if not masque_departements.empty:
                        with st.spinner("Découpage des zones de risque en cours..."):

                            ### CORRECTION : Réparation des géométries invalides ###
                            # On force la "réparation" des géométries des deux couches avant de les croiser.
                            polygones_preselectionnes.geometry = polygones_preselectionnes.geometry.buffer(0)
                            masque_departements.geometry = masque_departements.geometry.buffer(0)

                            # On harmonise les CRS par sécurité
                            masque_departements = masque_departements.to_crs(polygones_preselectionnes.crs)

                            # On effectue le découpage sur des géométries maintenant valides
                            gdf_risques_a_afficher = gpd.clip(polygones_preselectionnes, masque_departements)

                            if gdf_risques_a_afficher.empty:
                                st.warning("Le découpage des zones de risque n'a retourné aucune géométrie.")
                                gdf_risques_a_afficher = polygones_preselectionnes
                    else:
                        gdf_risques_a_afficher = polygones_preselectionnes
                else:
                    gdf_risques_a_afficher = polygones_preselectionnes
            else:
                gdf_risques_a_afficher = polygones_preselectionnes
        else:
            gdf_risques_a_afficher = gdf_a_filtrer

    # =================================================

    st.header("🚀 Choisissez votre mode d'analyse")
    tab_concurrence, tab_implantation = st.tabs(
        ["Analyser la concurrence dans une zone", "Analyser une nouvelle zone d'implantation"])

    gdf_inondations_final = gdf_risques_a_afficher if risque_selectionne == 'Inondations' else gpd.GeoDataFrame()
    gdf_rga_final = gdf_risques_a_afficher if risque_selectionne == 'Sécheresse (RGA)' else gpd.GeoDataFrame()

    # Assurez-vous que vos fonctions render_tab_* sont complètes dans votre fichier
    with tab_concurrence:
        render_tab_concurrence(df_communes, None, gdf_socio_filtre, indicateur, nom_indicateur, maille,
                               poi_selectionnes_sidebar, gdf_inondations_final, gdf_rga_final)
    with tab_implantation:
        render_tab_implantation(gdf_socio_filtre, indicateur, nom_indicateur, maille,
                                poi_selectionnes_sidebar, gdf_inondations_final, gdf_rga_final)
