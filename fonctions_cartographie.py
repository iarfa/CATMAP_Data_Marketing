import folium
import geopandas as gpd
import pandas as pd
import requests
import time
import streamlit as st
import branca.colormap as cm
from streamlit_folium import st_folium
from config import POI_CONFIG
from shapely.geometry import shape, box
# On importe la fonction transfo_geodataframe depuis sa nouvelle maison
from fonctions_basiques import transfo_geodataframe


# ==============================================
# Fonction générale (SUPPRIMÉE)
# ==============================================
# 'transfo_geodataframe' est maintenant importée depuis 'fonctions_basiques.py'


# =================================================================
# Section des fonctions pour la page INSEE (SUPPRIMÉE)
# =================================================================
# La fonction creer_carte_insee a été supprimée (P3)

# =================================================================
# Section des fonctions pour la page OSM
# =================================================================

@st.cache_data
def recherche_etablissements_osm(noms_etablissements, villes, max_etablissements=50):
    """Recherche des établissements via Nominatim et met le résultat en cache."""
    url, headers, donnees = "https://nominatim.openstreetmap.org/search", {"User-Agent": "Streamlit_App_Geo"}, []
    if len(villes) > 200:
        st.warning(f"Recherche limitée aux 200 premières communes sur {len(villes)}.")
        villes = villes[:200]
    for nom in noms_etablissements:
        for ville in villes:
            params = {"q": f"{nom}, {ville}, France", "format": "json", "limit": max_etablissements,
                      "addressdetails": 1}
            try:
                response = requests.get(url, params=params, headers=headers, timeout=20)
                response.raise_for_status()
                for resultat in response.json():
                    donnees.append({"nom_etablissement": nom, "ville": resultat.get("address", {}).get("city", ville),
                                    "nom_OSM": resultat.get("name", "N/A"), "adresse": resultat.get("display_name", ""),
                                    "latitude": float(resultat.get("lat", 0)),
                                    "longitude": float(resultat.get("lon", 0))})
            except requests.exceptions.RequestException as e:
                st.error(f"Erreur Nominatim : {e}")
    df = pd.DataFrame(donnees)
    if not df.empty:
        st.success(f"{len(df)} établissement(s) trouvé(s).")
    else:
        st.info("Aucun établissement trouvé.")
    return df


@st.cache_data
def calculer_isochrone_et_cacher(longitude, latitude, temps_secondes):
    """Appelle l'API ORS et met le résultat en cache."""
    try:
        response = requests.post("http://localhost:8080/ors/v2/isochrones/driving-car",
                                 json={"locations": [[longitude, latitude]], "range": [temps_secondes]},
                                 headers={'Content-Type': 'application/json'}, timeout=30)
        response.raise_for_status()
        if response.json().get('features'): return response.json()['features'][0]
    except requests.exceptions.RequestException as e:
        st.error(f"Erreur de calcul isochrone : {e}")
    return None


# Dictionnaire pour associer une icône à chaque type de POI
POI_ICONS = {
    "Gares": {'icon': 'train', 'color': 'darkblue', 'prefix': 'fa'},
    "Écoles": {'icon': 'graduation-cap', 'color': 'green', 'prefix': 'fa'},
    "Universités": {'icon': 'university', 'color': 'darkgreen', 'prefix': 'fa'},
    "Hôpitaux": {'icon': 'hospital', 'color': 'red', 'prefix': 'fa'},
    "Pharmacies": {'icon': 'plus-square', 'color': 'pink', 'prefix': 'fa'},
    "Mairies": {'icon': 'landmark', 'color': 'orange', 'prefix': 'fa'},
    "Supermarchés": {'icon': 'shopping-cart', 'color': 'purple', 'prefix': 'fa'}
}


@st.cache_data
def rechercher_poi_osm(bounding_box, tags_a_chercher):
    """
    Interroge l'API Overpass pour trouver des POI dans une zone géographique donnée.
    """
    overpass_url = "http://overpass-api.de/api/interpreter"
    bbox_str = f"{bounding_box[1]},{bounding_box[0]},{bounding_box[3]},{bounding_box[2]}"

    query_parts = []
    for tag_key, tag_value in tags_a_chercher.items():
        query_parts.append(f'node["{tag_key}"="{tag_value}"]({bbox_str});way["{tag_key}"="{tag_value}"]({bbox_str});')

    full_query = f"""
    [out:json][timeout:25];
    (
      {''.join(query_parts)}
    );
    out center;
    """

    try:
        response = requests.get(overpass_url, params={'data': full_query})
        response.raise_for_status()
        data = response.json()

        pois = []
        for element in data.get('elements', []):
            lon = element.get('lon')
            lat = element.get('lat')
            if 'center' in element:
                lon = element['center'].get('lon')
                lat = element['center'].get('lat')

            if lon and lat:
                pois.append({
                    'name': element.get('tags', {}).get('name', 'N/A'),
                    'latitude': lat,
                    'longitude': lon
                })

        if not pois:
            return gpd.GeoDataFrame()

        df_pois = pd.DataFrame(pois)
        gdf = transfo_geodataframe(df_pois, 'longitude', 'latitude')
        return gdf

    except requests.exceptions.RequestException as e:
        st.error(f"Erreur de requête Overpass : {e}")
        return gpd.GeoDataFrame()


# =================================================================
# SECTION DES HELPERS DE CARTOGRAPHIE (INCHANGÉE)
# =================================================================

def _ajouter_couche_socio(m, gdf_socio, colonne_socio, nom_indicateur_socio):
    """Helper interne pour ajouter la couche socio-économique à une carte Folium."""
    colormap, single_value_info = None, None
    if gdf_socio is None or gdf_socio.empty or not colonne_socio:
        return colormap, single_value_info

    if colonne_socio not in gdf_socio.columns: gdf_socio[colonne_socio] = pd.NA
    gdf_socio_clean = gdf_socio.dropna(subset=['geometry']).copy()
    if gdf_socio_clean.empty:
        return colormap, single_value_info

    valeurs_non_nulles = gdf_socio_clean[colonne_socio].dropna()
    if valeurs_non_nulles.nunique() > 1:
        min_val, max_val = valeurs_non_nulles.min(), valeurs_non_nulles.max()
        colormap = cm.LinearColormap(colors=['#ffffcc', '#fd8d3c', '#800026'], vmin=min_val, vmax=max_val);
        colormap.caption = nom_indicateur_socio or colonne_socio
    elif valeurs_non_nulles.nunique() == 1:
        single_value_info = {"label": nom_indicateur_socio, "value": valeurs_non_nulles.iloc[0]}

    tooltip_col_name = f"{colonne_socio}_display";
    gdf_socio_clean[tooltip_col_name] = gdf_socio_clean[colonne_socio].apply(
        lambda x: "ND" if pd.isna(x) else f"{x:,.0f}".replace(",", " "))

    def style_function_socio(feature):
        value = feature['properties'].get(colonne_socio)
        style = {'fillOpacity': 0.7, 'weight': 0.5, 'color': '#555555'}
        if pd.isna(value):
            style['fillColor'] = '#cccccc'
            style['fillOpacity'] = 0.5
        elif colormap:
            style['fillColor'] = colormap(value)
        elif single_value_info:
            style['fillColor'] = '#800026'
        else:
            style['fillOpacity'] = 0
        return style

    highlight_function = lambda x: {'weight': 1, 'color': '#555555', 'fillOpacity': 0.8}

    cle_nom = 'NOM_COM' if 'NOM_COM' in gdf_socio_clean.columns else 'NOM_DEP'
    tooltip = folium.features.GeoJsonTooltip(fields=[cle_nom, tooltip_col_name],
                                             aliases=['Zone:', f'{nom_indicateur_socio or colonne_socio}:'],
                                             labels=True, style=(
            "background-color: white; color: black; font-family: arial; font-size: 14px; padding: 10px;"))

    folium.GeoJson(
        gdf_socio_clean,
        name="Données Socio-Éco",
        style_function=style_function_socio,
        highlight_function=highlight_function,
        tooltip=tooltip
    ).add_to(m)

    return colormap, single_value_info


def _ajouter_couche_risques_inondation(m, gdf_inondations):
    """Helper interne pour ajouter la couche de risque d'inondation."""
    if gdf_inondations is None or gdf_inondations.empty:
        return

    fg_inondations = folium.FeatureGroup(name=f"Risque Inondation ({len(gdf_inondations)} zones)",
                                         show=True).add_to(m)
    color_map = {'Aléa fort': '#b30000', 'Aléa moyen': '#e34a33', 'Aléa faible': '#fdbb84',
                 'Non spécifié': '#808080'}

    def style_function_inondation(feature):
        aléa = feature['properties'].get('NIVEAU_ALEA', 'Non spécifié')
        return {'fillColor': color_map.get(aléa, '#808080'), 'color': 'black', 'weight': 0.5, 'fillOpacity': 0.5}

    tooltip_inondation = folium.features.GeoJsonTooltip(fields=['NIVEAU_ALEA'], aliases=['Niveau de risque:'])
    folium.GeoJson(gdf_inondations, style_function=style_function_inondation, tooltip=tooltip_inondation).add_to(
        fg_inondations)


def _ajouter_couche_risques_rga(m, gdf_rga):
    """Helper interne pour ajouter la couche de risque de sécheresse (RGA)."""
    if gdf_rga is None or gdf_rga.empty:
        return

    fg_rga = folium.FeatureGroup(name=f"Risque Sécheresse ({len(gdf_rga)} zones)", show=True).add_to(m)
    color_map_rga = {'aléa fort': '#d95f02', 'aléa moyen': '#fd8d3c', 'aléa faible': '#fee6ce',
                     'non spécifié': '#bdbdbd'}

    def style_function_rga(feature):
        aléa = feature['properties'].get('NIVEAU_ALEA', 'non spécifié').lower()
        return {'fillColor': color_map_rga.get(aléa, '#bdbdbd'), 'color': 'black', 'weight': 0.5,
                'fillOpacity': 0.5}

    tooltip_rga = folium.features.GeoJsonTooltip(fields=['NIVEAU_ALEA'], aliases=['Niveau de risque:'])
    folium.GeoJson(gdf_rga, style_function=style_function_rga, tooltip=tooltip_rga).add_to(fg_rga)


# =================================================================
# SECTION DES FONCTIONS DE CARTE PRINCIPALES (MODIFIÉES)
# =================================================================

def creer_carte_enrichie(gdf_etablissements, lat_centre, lon_centre,
                         gdf_socio=None, colonne_socio=None, nom_indicateur_socio=None,
                         gdf_poi=None, gdf_batiments=None, gdf_inondations=None, gdf_rga=None,
                         mode_affichage_etablissements='Points', rayon_cercles=1000, temps_isochrones=10,
                         df_coefficients=None,
                         poi_lat=None, poi_lon=None,
                         poi_analysis_mode='Isochrones', poi_radius_meters=1000,
                         # NOUVEAUX ARGUMENTS pour le point de référence
                         ref_lat=None, ref_lon=None, ref_nom="Votre Établissement"):
    """
    Crée une carte complète en incluant toutes les couches optionnelles.
    Affiche un marqueur distinct pour l'établissement de référence (SIREN) si fourni.
    """
    m = folium.Map(location=[lat_centre, lon_centre], zoom_start=11, tiles="OpenStreetMap")
    legend_enseignes = {}

    # 1. Couches Contextuelles (Socio, Risques, etc.)
    # Note: J'utilise vos helpers internes _ajouter_couche_... s'ils sont définis dans ce fichier
    # Sinon, assurez-vous qu'ils sont accessibles ou intégrés ici.
    # Pour simplifier l'exemple, je suppose que ces fonctions existent (comme dans votre code d'origine).
    colormap, single_value_info = _ajouter_couche_socio(m, gdf_socio, colonne_socio, nom_indicateur_socio)
    _ajouter_couche_risques_inondation(m, gdf_inondations)
    _ajouter_couche_risques_rga(m, gdf_rga)

    # 2. Point de Référence (Votre Établissement) - NOUVEAU
    if ref_lat is not None and ref_lon is not None:
        fg_ref = folium.FeatureGroup(name="📍 Votre Établissement", show=True).add_to(m)

        popup_html = f"<b>{ref_nom}</b><br>(Point de référence)"

        folium.Marker(
            location=[ref_lat, ref_lon],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"Votre Établissement : {ref_nom}",
            # Icône Rouge distincte avec une étoile
            icon=folium.Icon(color='red', icon='star', prefix='fa')
        ).add_to(fg_ref)

    # 3. Zone d'analyse utilisateur (POI manuel)
    zone_analyse_geom = None
    if poi_lat is not None and poi_lon is not None:
        fg_poi_user = folium.FeatureGroup(name="Zone d'Analyse (Cible)", show=True).add_to(m)
        folium.Marker([poi_lat, poi_lon], tooltip="Point cible",
                      icon=folium.Icon(icon='crosshairs', prefix='fa', color='black')).add_to(fg_poi_user)

        if poi_analysis_mode == 'Isochrones':
            temps_secondes = (temps_isochrones * 0.9) * 60
            feature = calculer_isochrone_et_cacher(poi_lon, poi_lat, temps_secondes)
            if feature and 'geometry' in feature:
                zone_analyse_geom = shape(feature['geometry'])
                folium.GeoJson(feature, style_function=lambda x: {'fillColor': 'black', 'color': 'black', 'weight': 2,
                                                                  'fillOpacity': 0.1},
                               tooltip=f"Zone cible {temps_isochrones} min").add_to(fg_poi_user)
        elif poi_analysis_mode == "Cercle d'influence":
            poi_point_gdf = gpd.GeoDataFrame(geometry=[gpd.points_from_xy([poi_lon], [poi_lat])[0]], crs="EPSG:4326")
            zone_geom = poi_point_gdf.to_crs("EPSG:3857").buffer(poi_radius_meters).to_crs("EPSG:4326").geometry.iloc[0]
            zone_analyse_geom = zone_geom
            folium.GeoJson(gpd.GeoDataFrame(geometry=[zone_geom], crs="EPSG:4326"),
                           style_function=lambda x: {'fillColor': 'black', 'color': 'black', 'weight': 2,
                                                     'fillOpacity': 0.1}).add_to(fg_poi_user)

    # 4. Bâtiments (si présents)
    if gdf_batiments is not None and not gdf_batiments.empty:
        fg_batiments = folium.FeatureGroup(name="Bâtiments", show=True).add_to(m)

        def style_bat(feature):
            return {'fillColor': '#3498db', 'color': '#2980b9', 'weight': 1, 'fillOpacity': 0.6}

        folium.GeoJson(gdf_batiments, style_function=style_bat,
                       tooltip=folium.features.GeoJsonTooltip(fields=['surface_m2'])).add_to(fg_batiments)

    # 5. Établissements (Concurrents)
    if gdf_etablissements is not None and not gdf_etablissements.empty:
        fg_etablissements = folium.FeatureGroup(name="Concurrents", show=True).add_to(m)

        # Palette de couleurs SANS le rouge (réservé au user)
        couleurs = ['#377eb8', '#4daf4a', '#984ea3', '#ff7f00', '#ffff33', '#a65628', '#f781bf']
        noms_uniques = gdf_etablissements['nom_etablissement'].dropna().unique()
        legend_enseignes = {nom: couleurs[i % len(couleurs)] for i, nom in enumerate(noms_uniques)}

        # Mode Isochrones pour les concurrents
        if mode_affichage_etablissements == 'Isochrones':
            for _, row in gdf_etablissements.iterrows():
                color = legend_enseignes.get(row['nom_etablissement'], 'gray')
                # Calcul simple coeff
                coeff = 0.9  # Valeur par défaut
                if df_coefficients is not None:
                    match = df_coefficients[df_coefficients['ville'].str.lower() == row.get('ville', '').lower()]
                    if not match.empty: coeff = match['coefficient'].iloc[0]

                feature = calculer_isochrone_et_cacher(row.geometry.x, row.geometry.y, (temps_isochrones * coeff) * 60)
                if feature:
                    folium.GeoJson(feature, style_function=lambda x, c=color: {'fillColor': c, 'color': c, 'weight': 2,
                                                                               'fillOpacity': 0.25}).add_to(
                        fg_etablissements)

        # Affichage des marqueurs
        for _, row in gdf_etablissements.iterrows():
            color = legend_enseignes.get(row['nom_etablissement'], 'gray')

            popup_html = f"""
            <b>{row.get('nom_etablissement', 'N/A')}</b><br>
            {row.get('adresse_simplifiee', 'N/A')}
            """
            popup = folium.Popup(popup_html, max_width=300)

            tooltip_text = row['nom_etablissement']
            border_color = color
            radius = 6
            weight = 2

            # Si le concurrent est dans la zone cible
            if zone_analyse_geom and row.geometry.within(zone_analyse_geom):
                tooltip_text = f"DANS LA ZONE - {row['nom_etablissement']}"
                border_color = 'black'
                weight = 3
                radius = 8

            if mode_affichage_etablissements in ['Points', 'Isochrones']:
                folium.CircleMarker([row.geometry.y, row.geometry.x], radius=radius, color=border_color,
                                    weight=weight, fill=True, fill_color=color, fill_opacity=0.9,
                                    popup=popup, tooltip=tooltip_text).add_to(fg_etablissements)

            elif mode_affichage_etablissements == 'Cercles d\'influence':
                # Cercle de zone
                folium.Circle([row.geometry.y, row.geometry.x], radius=rayon_cercles, color=color, fill=True,
                              fill_color=color, fill_opacity=0.2).add_to(fg_etablissements)
                # Point central
                folium.CircleMarker([row.geometry.y, row.geometry.x], radius=4, color='white', weight=1,
                                    fill=True, fill_color=color, fill_opacity=1, popup=popup,
                                    tooltip=tooltip_text).add_to(fg_etablissements)

    # 6. POI Contextuels
    if gdf_poi is not None and not gdf_poi.empty:
        fg_poi = folium.FeatureGroup(name="Points d'Intérêt", show=True).add_to(m)
        for _, poi in gdf_poi.iterrows():
            cat = poi.get('categorie', 'Divers')
            conf = POI_CONFIG.get(cat, {'icon': {'icon': 'info', 'color': 'gray', 'prefix': 'fa'}})
            folium.Marker([poi.geometry.y, poi.geometry.x], tooltip=f"{cat}: {poi['name']}",
                          icon=folium.Icon(icon=conf['icon']['icon'], color=conf['icon']['color'],
                                           prefix=conf['icon']['prefix'])).add_to(fg_poi)

    folium.LayerControl().add_to(m)
    return m, legend_enseignes, colormap, single_value_info


# ==================================================================
# MODIFIÉ : Géocodage (Renommage et Logique UI)
# ==================================================================

@st.cache_data(show_spinner=False)
def _geocoder_adresse_nominatim_api(adresse):
    """
    Fonction de logique pure : Géocode une adresse via Nominatim.
    """
    if not adresse or not isinstance(adresse, str):
        return None, None, None

    url = "https://nominatim.openstreetmap.org/search"
    params = {'q': adresse, 'format': 'json', 'limit': 1, 'countrycodes': 'fr'}
    headers = {'User-Agent': 'Streamlit_App_Geo_Analysis'}

    try:
        time.sleep(1.1)  # Respect de la policy (1 req/sec)
        response = requests.get(url, params=params, headers=headers, timeout=20)
        response.raise_for_status()
        results = response.json()

        if results:
            lat = float(results[0]['lat'])
            lon = float(results[0]['lon'])
            display_name = results[0].get('display_name', 'Adresse non disponible')
            return lat, lon, display_name
        else:
            return None, None, None

    except requests.exceptions.RequestException as e:
        print(f"Erreur de communication avec l'API de géocodage : {e}")
        return None, None, None


# MODIFIÉ : Renommée en '..._ui' et retourne un dict (P2)
@st.cache_data(show_spinner="Géocodage de l'adresse en cours...")
def geocoder_adresse_nominatim_ui(adresse):
    """
    Géocode une adresse en utilisant l'API Nominatim
    et AFFICHE le résultat dans l'interface Streamlit.
    Retourne un dictionnaire de résultats (pour P2)
    """
    lat, lon, display_name = _geocoder_adresse_nominatim_api(adresse)

    if lat and lon:
        st.success(f"Adresse trouvée : {display_name}")
        # MODIFIÉ (P2) : On retourne un dict
        return {
            "latitude": lat,
            "longitude": lon,
            "denominationunitelegale": adresse,  # Le "nom" est l'adresse saisie
            "adresse": display_name  # L'adresse formatée
        }
    else:
        st.warning(f"L'adresse '{adresse}' n'a pas pu être trouvée. Essayez d'être plus précis.")
        return None


# ==================================================================
# MODIFIÉ : 'creer_carte_implantation' (Goals P1, P2, P5)
# ==================================================================
def creer_carte_implantation(lat_centre, lon_centre,
                             zone_analyse_geom, gdf_poi_trouves,
                             gdf_socio=None, colonne_socio=None, nom_indicateur_socio=None,
                             gdf_batiments=None, gdf_inondations=None, gdf_rga=None,
                             # NOUVEAU : Ajout de ces paramètres
                             nom_point_central=None, adresse_point_central=None,
                             analysis_mode='Isochrones'):  # Pour le Goal P5
    """
    Crée une carte pour l'onglet "Analyse d'implantation".
    """
    m = folium.Map(location=[lat_centre, lon_centre], zoom_start=14, tiles="OpenStreetMap")
    colormap, single_value_info = None, None

    colormap, single_value_info = _ajouter_couche_socio(m, gdf_socio, colonne_socio, nom_indicateur_socio)
    _ajouter_couche_risques_inondation(m, gdf_inondations)
    _ajouter_couche_risques_rga(m, gdf_rga)

    # --- Couche de la Zone d'Analyse ---
    # MODIFIÉ (P1) : On crée le groupe et le marqueur EN PREMIER
    fg_zone_analyse = folium.FeatureGroup(name="Zone d'Analyse", show=True).add_to(m)

    # Gestion des noms et adresses par défaut
    if not nom_point_central:
        nom_point_central = "Point d'intérêt"
    if not adresse_point_central or pd.isna(adresse_point_central):
        adresse_point_central = f"Lat: {lat_centre:.4f}, Lon: {lon_centre:.4f}"

    popup_html = f"<b>{nom_point_central}</b><br>{adresse_point_central}"
    popup = folium.Popup(popup_html, max_width=300)

    # Ajout du Marqueur central (s'affiche toujours)
    folium.Marker(
        [lat_centre, lon_centre],
        tooltip=nom_point_central,
        popup=popup,
        icon=folium.Icon(icon='crosshairs', prefix='fa', color='red')
    ).add_to(fg_zone_analyse)

    # MODIFIÉ (P5) : On dessine la zone (si elle existe et n'est pas 'Point seul')
    if zone_analyse_geom and analysis_mode != 'Point seul':
        if analysis_mode == 'Isochrones':
            zone_gdf = gpd.GeoDataFrame(geometry=[zone_analyse_geom], crs="EPSG:4326")
            folium.GeoJson(zone_gdf, style_function=lambda x: {'fillColor': 'red', 'color': 'red', 'weight': 2,
                                                               'fillOpacity': 0.15}).add_to(fg_zone_analyse)
        elif analysis_mode == "Cercle d'influence":
            zone_gdf = gpd.GeoDataFrame(geometry=[zone_analyse_geom], crs="EPSG:4326")
            folium.GeoJson(zone_gdf, style_function=lambda x: {'fillColor': 'red', 'color': 'red', 'weight': 2,
                                                               'fillOpacity': 0.15}).add_to(fg_zone_analyse)
        # Si 'Point seul', on ne dessine pas de zone.

    # --- Couche Bâtiments ---
    if gdf_batiments is not None and not gdf_batiments.empty:
        fg_batiments = folium.FeatureGroup(name="Bâtiments", show=True).add_to(m)
        style_function_batiments = {'fillColor': '#3498db', 'color': '#2980b9', 'weight': 1.5, 'fillOpacity': 0.6}
        tooltip_batiments = folium.features.GeoJsonTooltip(fields=['surface_m2'], aliases=['Surface (m²):'],
                                                           labels=True, localize=True,
                                                           style="background-color: white; color: black; font-family: arial; font-size: 12px; padding: 5px;")
        popup_batiments = folium.features.GeoJsonPopup(fields=['surface_m2'], aliases=['Surface (m²):'], labels=True,
                                                       localize=True,
                                                       style="background-color: white; color: black; font-family: arial; font-size: 12px; padding: 5px;")
        folium.GeoJson(gdf_batiments, name="Bâtiments", style_function=lambda x: style_function_batiments,
                       tooltip=tooltip_batiments, popup=popup_batiments).add_to(fg_batiments)

    # --- Couche des POI trouvés dans la zone ---
    if gdf_poi_trouves is not None and not gdf_poi_trouves.empty:
        fg_poi = folium.FeatureGroup(name="Points d'Intérêt trouvés", show=True).add_to(m)
        for _, poi in gdf_poi_trouves.iterrows():
            categorie = poi.get('categorie', 'Inconnue')
            config = POI_CONFIG.get(categorie, {})
            icon_config = config.get('icon', {'icon': 'info-sign', 'color': 'gray', 'prefix': 'glyphicon'})
            folium.Marker(location=[poi.geometry.y, poi.geometry.x], tooltip=f"{categorie}: {poi.get('name', 'N/A')}",
                          icon=folium.Icon(icon=icon_config['icon'], color=icon_config['color'],
                                           prefix=icon_config.get('prefix', 'glyphicon'))).add_to(fg_poi)

    folium.LayerControl().add_to(m)
    return m, colormap, single_value_info


@st.cache_data(show_spinner="Recherche des bâtiments (Overpass API)...")
def rechercher_batiments_osm(bbox):
    """
    Interroge l'API Overpass pour trouver les bâtiments.
    VERSION DIAGNOSTIC : Affiche des messages d'erreur détaillés dans l'interface.
    """
    # 1. Vérification de la bbox
    if not bbox or len(bbox) != 4:
        st.error("❌ Erreur Interne : La zone de recherche (bbox) est invalide ou vide.")
        return gpd.GeoDataFrame()

    # On affiche la bbox pour vérifier qu'on est bien en France (Lat ~40-50, Lon ~-5 à 10)
    # st.info(f"🔍 Zone de recherche envoyée à OSM : {bbox}")

    # 2. Vérification de la taille
    try:
        bbox_poly = box(*bbox)
        gdf_bbox = gpd.GeoDataFrame([1], geometry=[bbox_poly], crs="EPSG:4326")
        area_km2 = gdf_bbox.to_crs("EPSG:2154").area[0] / 1_000_000  # Utilisation de Lambert 93 pour la précision

        if area_km2 > 50:
            st.warning(f"⚠️ Zone trop grande ({area_km2:.1f} km²). Recherche annulée par sécurité.")
            return gpd.GeoDataFrame()
    except Exception as e:
        st.warning(f"⚠️ Impossible de calculer la surface de la zone : {e}")

    # 3. Requête Overpass
    bbox_str = f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}"
    overpass_url = "http://overpass-api.de/api/interpreter"

    # On cherche 'way' et 'relation' qui ont un tag 'building'
    overpass_query = f"""
    [out:json][timeout:25];
    (
      way["building"]({bbox_str});
      relation["building"]({bbox_str});
    );
    out geom;
    """

    try:
        response = requests.get(overpass_url, params={'data': overpass_query}, timeout=30)

        if response.status_code != 200:
            st.error(f"❌ Erreur API Overpass (Code {response.status_code}). Le serveur OSM refuse la connexion.")
            if response.status_code == 429:
                st.warning("Trop de requêtes envoyées (Erreur 429). Attendez une minute.")
            return gpd.GeoDataFrame()

        data = response.json()

    except requests.exceptions.Timeout:
        st.error("❌ Délai d'attente dépassé (Timeout). La zone est peut-être trop dense en bâtiments.")
        return gpd.GeoDataFrame()
    except requests.exceptions.ConnectionError:
        st.error("❌ Erreur de connexion. Vérifiez votre internet ou le pare-feu.")
        return gpd.GeoDataFrame()
    except Exception as e:
        st.error(f"❌ Erreur technique lors de la requête : {e}")
        return gpd.GeoDataFrame()

    # 4. Traitement des données
    geometries = []
    elements = data.get('elements', [])

    if not elements:
        st.info("ℹ️ La requête a fonctionné, mais OSM ne renvoie aucun bâtiment dans cette zone.")
        return gpd.GeoDataFrame()

    for element in elements:
        if 'geometry' in element:
            coords = [(node['lon'], node['lat']) for node in element['geometry']]
            if len(coords) >= 3:
                try:
                    geometries.append(shape({'type': 'Polygon', 'coordinates': [coords]}))
                except:
                    pass

    if not geometries:
        st.warning("⚠️ Des données ont été reçues mais aucune géométrie valide n'a pu être construite.")
        return gpd.GeoDataFrame()

    gdf = gpd.GeoDataFrame(geometry=geometries, crs="EPSG:4326")

    # 5. Calcul Surface
    try:
        gdf_metric = gdf.to_crs("EPSG:2154")
        gdf['surface_m2'] = gdf_metric.area.round(0)
    except Exception as e:
        st.error(f"Erreur lors du calcul des surfaces : {e}")
        return gpd.GeoDataFrame()

    # st.success(f"✅ {len(gdf)} bâtiments trouvés !") # (Décommentez pour débugger si besoin)
    return gdf