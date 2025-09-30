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


# ==============================================
# Fonction générale
# ==============================================
def transfo_geodataframe(df, longitude_col, latitude_col, crs="EPSG:4326"):
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df[longitude_col], df[latitude_col]), crs=crs)


# =================================================================
# Section des fonctions pour la page INSEE
# =================================================================

def creer_carte_insee(data, lat_centre, lon_centre, mode_affichage='Points', rayon_m=None, temps_min=None):
    """
    Crée et retourne une carte Folium pour les données INSEE.

    Args:
        data (pd.DataFrame): Le DataFrame des établissements à afficher.
        lat_centre (float): Latitude du centre de la carte.
        lon_centre (float): Longitude du centre de la carte.
        mode_affichage (str): 'Points', 'Cercles' ou 'Isochrones'.
        rayon_m (int, optional): Rayon en mètres pour le mode 'Cercles'.
        temps_min (int, optional): Temps en minutes pour le mode 'Isochrones'.

    Returns:
        folium.Map: L'objet carte Folium prêt à être affiché.
    """
    # Vérification des prérequis pour créer la carte
    if lat_centre is None or lon_centre is None:
        # Pas de st.warning ici car ce fichier ne doit pas dépendre de streamlit
        print("Avertissement : Coordonnées du centre de la carte non définies.")
        return None

    carte = folium.Map(location=[lat_centre, lon_centre], zoom_start=11)

    if data.empty:
        # Affiche une carte vide centrée si pas de données
        return carte

    # Itération sur les données pour ajouter les marqueurs
    for _, ligne in data.iterrows():
        # S'assurer que les coordonnées existent pour la ligne actuelle
        if pd.notna(ligne.get('latitude')) and pd.notna(ligne.get('longitude')):
            lat, lon = ligne['latitude'], ligne['longitude']

            if mode_affichage == 'Points':
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=5,
                    color='blue',
                    fill=True,
                    fill_color='blue'
                ).add_to(carte)

            elif mode_affichage == 'Cercles' and rayon_m is not None:
                folium.Circle(
                    location=[lat, lon],
                    radius=rayon_m,
                    color='red',
                    fill=True,
                    fill_color='red',
                    fill_opacity=0.3
                ).add_to(carte)
                # Ajoute aussi le point central pour une meilleure visibilité
                folium.CircleMarker(location=[lat, lon], radius=2, color='darkred').add_to(carte)

            elif mode_affichage == 'Isochrones' and temps_min is not None:
                # La logique de calcul d'isochrone n'est pas encore connectée ici.
                # On met un placeholder pour le moment.
                folium.Marker(
                    location=[lat, lon],
                    tooltip=f"Isochrone de {temps_min} min à calculer",
                    icon=folium.Icon(icon='clock-o', prefix='fa', color='purple')
                ).add_to(carte)

    return carte

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

    :param bounding_box: Tuple (min_lon, min_lat, max_lon, max_lat)
    :param tags_a_chercher: Dictionnaire de tags, ex: {"amenity": "school"}
    :return: Un GeoDataFrame avec les POI trouvés.
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
            # Pour les 'ways' (routes, bâtiments), Overpass peut retourner le centre
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
        gdf = gpd.GeoDataFrame(
            df_pois,
            geometry=gpd.points_from_xy(df_pois['longitude'], df_pois['latitude']),
            crs="EPSG:4326"
        )
        return gdf

    except requests.exceptions.RequestException as e:
        st.error(f"Erreur de requête Overpass : {e}")
        return gpd.GeoDataFrame()


def creer_carte_enrichie(gdf_etablissements, lat_centre, lon_centre,
                         gdf_socio=None, colonne_socio=None, nom_indicateur_socio=None,
                         gdf_poi=None, gdf_batiments=None, gdf_inondations=None, gdf_rga=None,
                         mode_affichage_etablissements='Points', rayon_cercles=1000, temps_isochrones=10,
                         df_coefficients=None,
                         poi_lat=None, poi_lon=None,
                         poi_analysis_mode='Isochrones', poi_radius_meters=1000):
    """
    Crée une carte complète. VERSION FINALE avec correction du style de survol.
    """
    m = folium.Map(location=[lat_centre, lon_centre], zoom_start=11, tiles="OpenStreetMap")
    legend_enseignes, colormap, single_value_info = {}, None, None

    # --- Couche Socio-économique ---
    if gdf_socio is not None and not gdf_socio.empty and colonne_socio:
        if colonne_socio not in gdf_socio.columns: gdf_socio[colonne_socio] = pd.NA
        gdf_socio_clean = gdf_socio.dropna(subset=['geometry']).copy()
        if not gdf_socio_clean.empty:
            valeurs_non_nulles = gdf_socio_clean[colonne_socio].dropna()
            if valeurs_non_nulles.nunique() > 1:
                min_val, max_val = valeurs_non_nulles.min(), valeurs_non_nulles.max()
                colormap = cm.LinearColormap(colors=['#ffffcc', '#fd8d3c', '#800026'], vmin=min_val, vmax=max_val);
                colormap.caption = nom_indicateur_socio or colonne_socio
            elif valeurs_non_nulles.nunique() == 1:
                single_value_info = {"label": nom_indicateur_socio, "value": valeurs_non_nulles.iloc[0]}

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

            ### CORRECTION : Définition du style au survol de la souris ###
            highlight_function = lambda x: {'weight': 1, 'color': '#555555', 'fillOpacity': 0.8}

            cle_nom = 'NOM_COM' if 'NOM_COM' in gdf_socio_clean.columns else 'NOM_DEP'
            tooltip = folium.features.GeoJsonTooltip(fields=[cle_nom, colonne_socio],
                                                     aliases=['Zone:', f'{nom_indicateur_socio or colonne_socio}:'],
                                                     labels=True, style=(
                    "background-color: white; color: black; font-family: arial; font-size: 14px; padding: 10px;"))

            folium.GeoJson(
                gdf_socio_clean,
                name="Données Socio-Éco",
                style_function=style_function_socio,
                highlight_function=highlight_function,  # AJOUT DE CETTE LIGNE
                tooltip=tooltip
            ).add_to(m)

    # --- Couche Risque Inondation ---
    if gdf_inondations is not None and not gdf_inondations.empty:
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

    # --- Couche Risque Sécheresse (RGA) ---
    if gdf_rga is not None and not gdf_rga.empty:
        fg_rga = folium.FeatureGroup(name=f"Risque Sécheresse ({len(gdf_rga)} zones)", show=True).add_to(m)
        color_map_rga = {'aléa fort': '#d95f02', 'aléa moyen': '#fd8d3c', 'aléa faible': '#fee6ce',
                         'non spécifié': '#bdbdbd'}

        def style_function_rga(feature):
            aléa = feature['properties'].get('NIVEAU_ALEA', 'non spécifié').lower()
            return {'fillColor': color_map_rga.get(aléa, '#bdbdbd'), 'color': 'black', 'weight': 0.5,
                    'fillOpacity': 0.5}

        tooltip_rga = folium.features.GeoJsonTooltip(fields=['NIVEAU_ALEA'], aliases=['Niveau de risque:'])
        folium.GeoJson(gdf_rga, style_function=style_function_rga, tooltip=tooltip_rga).add_to(fg_rga)

    # --- Couche des Établissements (reprise de la version fonctionnelle) ---
    if gdf_etablissements is not None and not gdf_etablissements.empty:
        fg_etablissements = folium.FeatureGroup(name="Établissements", show=True).add_to(m)
        couleurs = ['#e41a1c', '#377eb8', '#4daf4a', '#984ea3', '#ff7f00', '#ffff33', '#a65628', '#f781bf']
        legend_enseignes = {nom: couleurs[i % len(couleurs)] for i, nom in
                            enumerate(gdf_etablissements['nom_etablissement'].unique())}
        for _, row in gdf_etablissements.iterrows():
            color = legend_enseignes.get(row['nom_etablissement'], 'gray')
            popup_html = f"<b>Nom:</b> {row.get('nom_etablissement', 'N/A')}<br><b>Adresse:</b> {row.get('adresse', 'N/A')}"
            popup = folium.Popup(popup_html, max_width=300)
            tooltip_text = row['nom_etablissement']
            if mode_affichage_etablissements == 'Cercles d\'influence':
                folium.Circle(location=[row.geometry.y, row.geometry.x], radius=rayon_cercles, color=color, fill=True,
                              fill_color=color, fill_opacity=0.2).add_to(fg_etablissements)
            elif mode_affichage_etablissements == 'Isochrones':
                temps_secondes = temps_isochrones * 60
                coeff = 0.9
                if df_coefficients is not None and not df_coefficients.empty:
                    ville_etab = row.get('ville', '').lower()
                    coeff_row = df_coefficients[df_coefficients['ville'].str.lower() == ville_etab]
                    if not coeff_row.empty:
                        coeff = coeff_row['coefficient'].iloc[0]
                feature = calculer_isochrone_et_cacher(row.geometry.x, row.geometry.y, temps_secondes * coeff)
                if feature:
                    folium.GeoJson(feature, style_function=lambda x, c=color: {'fillColor': c, 'color': c, 'weight': 2,
                                                                               'fillOpacity': 0.25}).add_to(
                        fg_etablissements)
            folium.CircleMarker(location=[row.geometry.y, row.geometry.x], radius=5, color='black', weight=1.5,
                                fill=True, fill_color=color, fill_opacity=1, popup=popup, tooltip=tooltip_text).add_to(
                fg_etablissements)

    # --- Couche des Points d'Intérêt (POI) Standards ---
    if gdf_poi is not None and not gdf_poi.empty:
        fg_poi = folium.FeatureGroup(name="Points d'Intérêt", show=True).add_to(m)
        for categorie, gdf_categorie in gdf_poi.groupby('categorie'):
            config = POI_CONFIG.get(categorie, {})
            icon_config = config.get('icon', {'icon': 'info-sign', 'color': 'gray', 'prefix': 'glyphicon'})
            singular_name = config.get('singular', categorie)
            for _, poi in gdf_categorie.iterrows():
                folium.Marker(location=[poi.geometry.y, poi.geometry.x], tooltip=f"{singular_name}: {poi['name']}",
                              icon=folium.Icon(icon=icon_config['icon'], color=icon_config['color'],
                                               prefix=icon_config.get('prefix', 'glyphicon'))).add_to(fg_poi)

    folium.LayerControl().add_to(m)
    return m, legend_enseignes, colormap, single_value_info

@st.cache_data(show_spinner="Géocodage de l'adresse en cours...")
def geocoder_adresse_nominatim(adresse):
    """
    Géocode une adresse en utilisant l'API Nominatim d'OpenStreetMap.

    Args:
        adresse (str): L'adresse à géocoder.

    Returns:
        tuple: Un tuple (latitude, longitude) ou (None, None) si le géocodage échoue.
    """
    if not adresse or not isinstance(adresse, str):
        return None, None

    url = "https://nominatim.openstreetmap.org/search"
    params = {'q': adresse, 'format': 'json', 'limit': 1, 'countrycodes': 'fr'}
    headers = {'User-Agent': 'Streamlit_App_Geo_Analysis'}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=20)
        response.raise_for_status()
        results = response.json()

        if results:
            lat = float(results[0]['lat'])
            lon = float(results[0]['lon'])
            st.success(f"Adresse trouvée : {results[0]['display_name']}")
            return lat, lon
        else:
            st.warning(f"L'adresse '{adresse}' n'a pas pu être trouvée. Essayez d'être plus précis.")
            return None, None

    except requests.exceptions.RequestException as e:
        st.error(f"Erreur de communication avec l'API de géocodage : {e}")
        return None, None


def creer_carte_implantation(lat_centre, lon_centre, zone_analyse_geom, gdf_poi_trouves,
                             gdf_socio=None, colonne_socio=None, nom_indicateur_socio=None,
                             gdf_batiments=None, gdf_inondations=None, gdf_rga=None):
    """
    Crée une carte pour l'onglet "Analyse d'implantation". VERSION FINALE avec correction du style de survol.
    """
    m = folium.Map(location=[lat_centre, lon_centre], zoom_start=14, tiles="OpenStreetMap")
    colormap, single_value_info = None, None

    # --- Couche Socio-économique ---
    if gdf_socio is not None and not gdf_socio.empty and colonne_socio:
        if colonne_socio not in gdf_socio.columns: gdf_socio[colonne_socio] = pd.NA
        gdf_socio_clean = gdf_socio.dropna(subset=['geometry']).copy()
        if not gdf_socio_clean.empty:
            valeurs_non_nulles = gdf_socio_clean[colonne_socio].dropna()
            if valeurs_non_nulles.nunique() > 1:
                min_val, max_val = valeurs_non_nulles.min(), valeurs_non_nulles.max()
                colormap = cm.LinearColormap(colors=['#ffffcc', '#fd8d3c', '#800026'], vmin=min_val, vmax=max_val);
                colormap.caption = nom_indicateur_socio or colonne_socio
            elif valeurs_non_nulles.nunique() == 1:
                single_value_info = {"label": nom_indicateur_socio, "value": valeurs_non_nulles.iloc[0]}

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

            ### CORRECTION : Définition du style au survol de la souris ###
            highlight_function = lambda x: {'weight': 1, 'color': '#555555', 'fillOpacity': 0.8}

            cle_nom = 'NOM_COM' if 'NOM_COM' in gdf_socio_clean.columns else 'NOM_DEP'
            tooltip = folium.features.GeoJsonTooltip(fields=[cle_nom, colonne_socio],
                                                     aliases=['Zone:', f'{nom_indicateur_socio or colonne_socio}:'],
                                                     labels=True, style=(
                    "background-color: white; color: black; font-family: arial; font-size: 14px; padding: 10px;"))

            folium.GeoJson(
                gdf_socio_clean,
                name="Données Socio-Éco",
                style_function=style_function_socio,
                highlight_function=highlight_function,  # AJOUT DE CETTE LIGNE
                tooltip=tooltip
            ).add_to(m)

    # --- Couche Risque Inondation ---
    if gdf_inondations is not None and not gdf_inondations.empty:
        fg_inondations = folium.FeatureGroup(name="Risque Inondation", show=True).add_to(m)
        color_map = {'Aléa fort': '#b30000', 'Aléa moyen': '#e34a33', 'Aléa faible': '#fdbb84',
                     'Non spécifié': '#808080'}

        def style_function_inondation(feature):
            aléa = feature['properties'].get('NIVEAU_ALEA', 'Non spécifié')
            return {'fillColor': color_map.get(aléa, '#808080'), 'color': 'transparent', 'weight': 0,
                    'fillOpacity': 0.5}

        folium.GeoJson(gdf_inondations, style_function=style_function_inondation,
                       tooltip=folium.features.GeoJsonTooltip(fields=['NIVEAU_ALEA'],
                                                              aliases=['Niveau de risque :'])).add_to(fg_inondations)

    # --- Couche Risque Sécheresse (RGA) ---
    if gdf_rga is not None and not gdf_rga.empty:
        fg_rga = folium.FeatureGroup(name=f"Risque Sécheresse ({len(gdf_rga)} zones)", show=True).add_to(m)
        color_map_rga = {'aléa fort': '#d95f02', 'aléa moyen': '#fd8d3c', 'aléa faible': '#fee6ce',
                         'non spécifié': '#bdbdbd'}

        def style_function_rga(feature):
            aléa = feature['properties'].get('NIVEAU_ALEA', 'non spécifié').lower()
            return {'fillColor': color_map_rga.get(aléa, '#bdbdbd'), 'color': 'black', 'weight': 0.5,
                    'fillOpacity': 0.5}

        tooltip_rga = folium.features.GeoJsonTooltip(fields=['NIVEAU_ALEA'], aliases=['Niveau de risque:'])
        folium.GeoJson(gdf_rga, style_function=style_function_rga, tooltip=tooltip_rga).add_to(fg_rga)

    # --- Couche de la Zone d'Analyse ---
    if zone_analyse_geom:
        fg_zone_analyse = folium.FeatureGroup(name="Zone d'Analyse", show=True).add_to(m)
        folium.Marker([lat_centre, lon_centre], tooltip="Point analysé",
                      icon=folium.Icon(icon='crosshairs', prefix='fa', color='red')).add_to(fg_zone_analyse)
        zone_gdf = gpd.GeoDataFrame(geometry=[zone_analyse_geom], crs="EPSG:4326")
        folium.GeoJson(zone_gdf, style_function=lambda x: {'fillColor': 'red', 'color': 'red', 'weight': 2,
                                                           'fillOpacity': 0.15}).add_to(fg_zone_analyse)

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


@st.cache_data(show_spinner="Recherche des bâtiments...")
def rechercher_batiments_osm(bbox):
    """
    Interroge l'API Overpass pour trouver les polygones des bâtiments dans une zone,
    et calcule leur surface en mètres carrés.
    Inclut un timeout plus long et une vérification de la taille de la zone.

    Args:
        bbox (tuple): Bounding box (min_lon, min_lat, max_lon, max_lat).

    Returns:
        gpd.GeoDataFrame: Un GeoDataFrame contenant les polygones des bâtiments
                          et une colonne 'surface_m2', ou un GeoDataFrame vide.
    """
    # Étape de prévention : Vérifier la taille de la Bbox
    # On crée un polygone à partir de la bbox pour calculer sa superficie approximative
    try:
        bbox_poly = box(*bbox)
        gdf_bbox = gpd.GeoDataFrame([1], geometry=[bbox_poly], crs="EPSG:4326")
        area_km2 = gdf_bbox.to_crs("EPSG:3857").area[0] / 1_000_000
        # Si la zone est très grande (ex: > 50 km²), on avertit l'utilisateur
        if area_km2 > 50:
            st.warning(
                f"⚠️ La zone d'analyse est très grande ({area_km2:.0f} km²). La recherche des bâtiments peut être longue ou échouer. Essayez de réduire le temps de trajet ou le rayon.")
    except Exception:
        # En cas d'erreur sur le calcul de la zone, on continue sans bloquer
        pass

    bbox_str = f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}"
    overpass_url = "http://overpass-api.de/api/interpreter"

    # On augmente le timeout de 30s à 90s pour les requêtes complexes
    overpass_query = f"""
    [out:json][timeout:90];
    (
      way["building"]({bbox_str});
    );
    out geom;
    """

    try:
        response = requests.get(overpass_url, params={'data': overpass_query})
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        # On affiche l'erreur de manière plus visible dans l'application
        st.warning(f"Impossible de récupérer les données des bâtiments : {e}")
        return gpd.GeoDataFrame()

    geometries = []
    elements = data.get('elements', [])

    for element in elements:
        if element['type'] == 'way' and 'geometry' in element:
            coords = [(node['lon'], node['lat']) for node in element['geometry']]
            if len(coords) >= 4:  # Un polygone valide a au moins 4 points
                geometries.append(shape({'type': 'Polygon', 'coordinates': [coords]}))

    if not geometries:
        return gpd.GeoDataFrame()

    gdf = gpd.GeoDataFrame(geometry=geometries, crs="EPSG:4326")

    try:
        # Reprojection en Lambert-93 pour un calcul de surface précis en France
        gdf_metric = gdf.to_crs("EPSG:2154")
        gdf['surface_m2'] = gdf_metric.area.round(1)
    except Exception as e:
        st.error(f"Erreur lors du calcul de la surface des bâtiments : {e}")
        return gpd.GeoDataFrame()

    return gdf