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
    charger_zones_inondables, charger_donnees_rga, enrichir_donnees_risques_avec_num_dep,
    connect_to_db,  # <-- C'est correct
    find_etablissement_by_siret,  # <-- NOUVEL IMPORT (P1)
    find_etablissements_by_siren,  # <-- NOUVEL IMPORT (P1)
    enrichir_dataframe_siren,
    get_etab_details_for_concurrence,
    find_concurrents
)
from fonctions_cartographie import (
    transfo_geodataframe, creer_carte_enrichie, rechercher_poi_osm,
    geocoder_adresse_nominatim_ui,  # <-- C'est correct
    creer_carte_implantation, calculer_isochrone_et_cacher,
    rechercher_batiments_osm
)
from interface import (
    interface_recherche_osm, interface_selection_socio,
    interface_selection_poi, interface_point_interet, POI_CONFIG,
    interface_selection_batiments, interface_selection_risques,
    interface_enrichissement_fichier,
    interface_telechargement_fichier,
    interface_recherche_concurrence
)


# =============================================================================
# HELPER DE FILTRAGE POUR LA PAGE (INCHANGÉ)
# =============================================================================

def _preparer_et_filtrer_gdf_risque(gdf_source, nom_risque, risque_selectionne, regions_filtrees, departements_filtres):
    """
    Filtre un GeoDataFrame de risque en fonction de la sélection de l'utilisateur.
    """
    if risque_selectionne != nom_risque or gdf_source.empty:
        return gpd.GeoDataFrame()

    if 'NOM_DEP' in gdf_source.columns and 'Num_Dep' in gdf_source.columns:
        gdf_source['affichage_dep'] = gdf_source['Num_Dep'] + " - " + gdf_source['NOM_DEP'].str.upper()
    else:
        st.warning(f"Données de risque '{nom_risque}' incomplètes (colonnes NOM_DEP/Num_Dep manquantes).")
        departements_filtres = []

    if regions_filtrees:
        if 'NOM_REG' in gdf_source.columns:
            return gdf_source[gdf_source['NOM_REG'].isin(regions_filtrees)]
        else:
            st.warning(f"Filtrage par région impossible pour '{nom_risque}' (colonne NOM_REG manquante).")

    elif departements_filtres:
        if 'affichage_dep' in gdf_source.columns:
            return gdf_source[gdf_source['affichage_dep'].isin(departements_filtres)]
        else:
            pass

    return gdf_source


# =============================================================================
# LOGIQUE DE L'ONGLET N°1 : ANALYSE DE LA CONCURRENCE
# =============================================================================
def render_tab_concurrence(df_communes, df_coefficients, gdf_socio_filtre, indicateur, nom_indicateur, maille,
                           poi_selectionnes_sidebar, gdf_inondations, gdf_rga,
                           engine):
    """
    Gère l'affichage de l'onglet concurrence avec séparation stricte des modes.
    Récupère les coordonnées de l'établissement SIREN pour les afficher sur la carte.
    """
    st.header("Analyse de la Concurrence")

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
                gdf_inondations=gdf_inondations,
                gdf_rga=gdf_rga,
                # Pas de point de référence en mode OSM manuel
                ref_lat=None, ref_lon=None, ref_nom=None
            )

    # --- SOUS-ONGLET 2 : Base SIREN ---
    with subtab_siren:
        st.info("Trouver des concurrents ayant le même code NAF qu'un établissement de référence.")
        gdf_concurrents = interface_recherche_concurrence(engine)

        # --- Récupération des infos du point de référence ---
        ref_lat = None
        ref_lon = None
        ref_nom = "Votre Établissement"

        if st.session_state.get('etab_concurrence_details'):
            details = st.session_state.etab_concurrence_details
            # On récupère les coordonnées stockées (Assurez-vous que get_etab_details les retourne !)
            ref_lat = details.get('latitude')
            ref_lon = details.get('longitude')
            ref_nom = details.get('denominationunitelegale', "Votre Établissement")

        if not gdf_concurrents.empty:
            # Tableau des résultats
            if st.checkbox("Afficher le détail des concurrents SIREN (tableau)", value=True, key="details_table_siren"):
                cols_to_show = [
                    'denominationunitelegale',
                    'siret',
                    'siren',
                    'adresse',  # On garde l'adresse, on retire la ville qui n'existe plus
                    'activiteprincipaleetablissement',
                    'intitules_naf_vf'
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
                gdf_inondations=gdf_inondations,
                gdf_rga=gdf_rga,
                # On passe les coordonnées du point rouge
                ref_lat=ref_lat,
                ref_lon=ref_lon,
                ref_nom=ref_nom
            )


def _afficher_resultats_concurrence(gdf_resultats, source_name, df_coefficients, gdf_socio_filtre, indicateur,
                                    nom_indicateur, poi_selectionnes_sidebar, gdf_inondations, gdf_rga, ref_lat=None,
                                    ref_lon=None, ref_nom=None):
    """
    Fonction helper pour afficher la carte de concurrence.
    Accepte désormais ref_lat/ref_lon pour afficher l'établissement de référence.
    """
    st.markdown("---")
    st.subheader(f"Carte Interactive ({source_name})")

    # Centrage : Si on a un point de référence, on peut centrer dessus, sinon sur la moyenne des concurrents
    if ref_lat and ref_lon:
        lat_centre, lon_centre = ref_lat, ref_lon
    else:
        lat_centre, lon_centre = choix_centre_OSM(gdf_resultats)

    # Recherche POI
    gdf_poi_final = gpd.GeoDataFrame()
    if poi_selectionnes_sidebar:
        bounds = gdf_resultats.total_bounds
        # Si un seul point (ref), bounds peut être minuscule, on élargit
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
        # Arguments pour le point de référence
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
            st.write("**Concurrents**")
            for nom, color in legend_enseignes.items():
                if list(legend_enseignes.keys()).index(nom) < 10:
                    st.markdown(f'<span style="color:{color}; font-size:22px;">●</span> {nom}', unsafe_allow_html=True)
            if len(legend_enseignes) > 10:
                st.write("...")

        # (Affichage des légendes risques/socio inchangé...)
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
# LOGIQUE DE L'ONGLET N°2 : ANALYSE D'UNE ZONE D'IMPLANTATION (MODIFIÉ - Tâche 5)
# =============================================================================
def render_tab_implantation(gdf_socio_filtre, indicateur, nom_indicateur, maille,
                            poi_selectionnes_sidebar, gdf_inondations, gdf_rga,
                            engine):
    gdf_batiments_final = gpd.GeoDataFrame()
    afficher_batiments, surface_min, surface_max = interface_selection_batiments()

    # MODIFIÉ : On récupère un dict de résultats
    result_point_central = interface_point_interet(engine=engine)

    # On initialise les variables finales
    final_lat, final_lon = None, None
    final_nom, final_adresse_str = None, None
    mode, radius = result_point_central['mode'], result_point_central['radius']

    # On peuple les variables finales en fonction de la source
    if result_point_central['source'] == "Adresse":
        res_geo = geocoder_adresse_nominatim_ui(result_point_central['valeur'])
        if res_geo:
            final_lat = res_geo.get('latitude')
            final_lon = res_geo.get('longitude')
            final_nom = res_geo.get('denominationunitelegale')  # Le nom est l'adresse
            final_adresse_str = res_geo.get('adresse')  # L'adresse formatée

    elif result_point_central['source'] == "Coordonnées":
        if result_point_central['valeur']:
            final_lat = result_point_central['valeur']['latitude']
            final_lon = result_point_central['valeur']['longitude']
            final_nom = f"Point ({final_lat:.4f}, {final_lon:.4f})"
            final_adresse_str = "Coordonnées manuelles"

    elif result_point_central['source'] == "SIRET/SIREN":
        if result_point_central['valeur']:  # Si 'valeur' contient le dict de l'étab
            res_siret = result_point_central['valeur']
            final_lat = res_siret.get('latitude')
            final_lon = res_siret.get('longitude')
            final_nom = res_siret.get('denominationunitelegale')
            final_adresse_str = res_siret.get('adresse')

            # (Goal 4)
            if final_nom and "non indique" in str(final_nom).lower():
                st.warning("Le nom de cet établissement est 'Non indique' dans la base de données.", icon="ℹ️")

    if final_lat and final_lon:
        # --- Tâche 5 : Suppression du st.header ---
        # La ligne st.header(f"Analyse de zone : {final_nom}") a été supprimée.
        # Le nom est affiché sur le marqueur de la carte.

        temps_isochrones = 5
        if mode == 'Isochrones':
            temps_isochrones = st.slider(
                "Temps de trajet (min) :",
                min_value=2, max_value=20, value=5, step=1,
                key="temps_implantation"
            )

        zone_analyse_geom = None
        # MODIFIÉ (P5) : On ne calcule la zone que si ce n'est pas 'Point seul'
        if mode == 'Isochrones':
            temps_secondes_ajuste = temps_isochrones * 60 * 0.9
            feature = calculer_isochrone_et_cacher(final_lon, final_lat, temps_secondes_ajuste)
            if feature:
                zone_analyse_geom = shape(feature['geometry'])
        elif mode == "Cercle d'influence":
            poi_point_gdf = gpd.GeoDataFrame(geometry=[Point(final_lon, final_lat)], crs="EPSG:4326")
            poi_reproj = poi_point_gdf.to_crs("EPSG:3857")
            zone_analyse_geom_reproj = poi_reproj.buffer(radius).iloc[0]
            zone_analyse_geom = \
                gpd.GeoDataFrame(geometry=[zone_analyse_geom_reproj], crs="EPSG:3857").to_crs(
                    "EPSG:4326").geometry.iloc[0]
        # Si mode == 'Point seul', zone_analyse_geom reste None

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

        gdf_batiments_final = gpd.GeoDataFrame()
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
            gdf_batiments=gdf_batiments_final, gdf_inondations=gdf_inondations, gdf_rga=gdf_rga,
            nom_point_central=final_nom,
            adresse_point_central=final_adresse_str,
            analysis_mode=mode
        )

        col_carte, col_legende = st.columns([3, 1])
        with col_carte:
            st_folium(map_object, width=800, height=600, returned_objects=[])
        with col_legende:
            st.write("**Légendes**")
            if not gdf_inondations.empty:
                st.write("**Risque Inondation**")
                st.markdown(f'<span style="color:#fdbb84; font-size:22px;">●</span> Aléa Faible',
                            unsafe_allow_html=True)
                st.markdown(f'<span style="color:#e34a33; font-size:22px;">●</span> Aléa Moyen', unsafe_allow_html=True)
                st.markdown(f'<span style="color:#b30000; font-size:22px;">●</span> Aléa Fort', unsafe_allow_html=True)
            elif not gdf_rga.empty:
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

    elif not result_point_central['valeur']:
        st.info("Veuillez saisir une adresse, des coordonnées ou un SIREN/SIRET pour lancer l'analyse.")


# =============================================================================
# LOGIQUE DE L'ONGLET N°3 : ENRICHISSEMENT (MODIFIÉ - Final)
# =============================================================================
def render_tab_enrichissement(engine):
    if not engine:
        st.error("Connexion à la base de données SIREN échouée.")
        return

    # 1. Récupération des paramètres (inclus only_siege)
    df_original, colonne_id, type_identifiant, only_siege = interface_enrichissement_fichier()

    if df_original is not None and colonne_id is not None:

        start_time = time.time()

        # 2. Appel de la fonction d'enrichissement
        df_succes, df_not_found, df_bad_format = enrichir_dataframe_siren(
            engine,
            df_original,
            colonne_id,
            type_identifiant,
            only_siege  # <-- Nouveau paramètre passé ici
        )

        end_time = time.time()
        duree = end_time - start_time

        # --- TABLEAU 1 : SUCCÈS ---
        if not df_succes.empty:
            nb_trouves = len(df_succes)
            vitesse = nb_trouves / duree if duree > 0 else 0

            # MODIFIÉ : Format vitesse sans virgule "{vitesse:.0f}"
            message_succes = (
                f"✅ **{nb_trouves}** établissements trouvés et enrichis !\n\n"
                f"⏱️ Temps : **{duree:.2f}s** (~{vitesse:.0f} req/s)."
            )

            st.markdown("---")
            interface_telechargement_fichier(
                df=df_succes,
                titre_section="📂 Données Enrichies (Succès)",
                nom_fichier_csv="resultats_enrichis.csv",
                message_info=message_succes,
                couleur_info="success"
            )
        else:
            if df_not_found.empty and df_bad_format.empty:
                pass  # Rien du tout n'a marché (fichier vide ?)
            else:
                st.warning("Aucun résultat trouvé dans la base pour les identifiants valides fournis.")

        # --- TABLEAU 2 : FORMAT INVALIDE (Rejets) ---
        if not df_bad_format.empty:
            nb_bad = len(df_bad_format)
            target_len = 14 if type_identifiant == "siret" else 9

            message_bad = (
                f"⚠️ **Attention : {nb_bad} lignes ont un format {type_identifiant.upper()} incorrect.**\n\n"
                f"Critères : Doit contenir uniquement des chiffres et faire strictement **{target_len} caractères**.\n"
                "Cause probable : Perte des zéros au début (ex: Excel convertit '0123' en '123')."
            )

            st.markdown("---")
            interface_telechargement_fichier(
                df=df_bad_format,
                titre_section=f"🚫 Rejets : Format {type_identifiant.upper()} Invalide",
                nom_fichier_csv="lignes_format_incorrect.csv",
                message_info=message_bad,
                couleur_info="error"
            )

        # --- TABLEAU 3 : INTROUVABLES (Format OK, mais pas en base) ---
        if not df_not_found.empty:
            nb_not_found = len(df_not_found)

            # Message adaptatif selon le filtre siège
            contexte_filtre = ""
            if type_identifiant == "siren" and only_siege:
                contexte_filtre = " (Note : Vous avez filtré uniquement sur les Sièges Sociaux. Ces SIREN existent peut-être pour des établissements secondaires)."

            message_not_found = (
                f"🤷‍♂️ **{nb_not_found}** identifiants ont un format correct mais n'ont pas été trouvés.{contexte_filtre}"
            )

            st.markdown("---")
            interface_telechargement_fichier(
                df=df_not_found,
                titre_section="🔍 Rejets : Identifiants Inconnus en Base",
                nom_fichier_csv="lignes_introuvables.csv",
                message_info=message_not_found,
                couleur_info="warning"
            )


# =============================================================================
# FONCTION PRINCIPALE DE LA PAGE
# =============================================================================
def page_osm(path_communes, path_iris_socio, path_coeff_trafic, path_zones_inondables, path_rga_secheresse):
    st.title("🗺️ Analyse Géospatiale & SIREN")

    engine = connect_to_db()

    with st.spinner("Chargement des données initiales..."):
        df_communes = charger_communes(path_communes)
        gdf_inondations = charger_zones_inondables(path_zones_inondables)
        gdf_rga = charger_donnees_rga(path_rga_secheresse)
        df_iris_base = charger_donnees_iris_socio(path_iris_socio)

    if df_iris_base is None or df_iris_base.empty:
        st.error("Impossible de charger les données socio-économiques.")
        return

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

    st.header("🚀 Choisissez votre mode d'analyse")
    tab_concurrence, tab_implantation, tab_enrichissement = st.tabs(
        ["Analyse de Concurrence", "Analyse de Zone d'Implantation", "Enrichissement de Fichier"]
    )

    with tab_concurrence:
        render_tab_concurrence(df_communes, None, gdf_socio_filtre, indicateur, nom_indicateur, maille,
                               poi_selectionnes_sidebar, gdf_inondations_a_afficher, gdf_rga_a_afficher,
                               engine=engine)

    with tab_implantation:
        render_tab_implantation(gdf_socio_filtre, indicateur, nom_indicateur, maille,
                                poi_selectionnes_sidebar, gdf_inondations_a_afficher, gdf_rga_a_afficher,
                                engine=engine)

    with tab_enrichissement:
        render_tab_enrichissement(engine=engine)