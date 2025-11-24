# Fichier: fonctions_cartographie.py

import folium
import geopandas as gpd
import pandas as pd
import requests
import time
import streamlit as st
import branca.colormap as cm
from streamlit_folium import st_folium
from shapely.geometry import shape, box
from folium.plugins import Fullscreen  # <--- NOUVEL IMPORT IMPORTANT

from config import POI_CONFIG
from fonctions_basiques import transfo_geodataframe


# =================================================================
# FONCTIONS API & UTILITAIRES
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


@st.cache_data
def rechercher_poi_osm(bounding_box, tags_a_chercher):
    """Interroge l'API Overpass pour trouver des POI."""
    overpass_url = "http://overpass-api.de/api/interpreter"
    bbox_str = f"{bounding_box[1]},{bounding_box[0]},{bounding_box[3]},{bounding_box[2]}"

    query_parts = []
    for tag_key, tag_value in tags_a_chercher.items():
        query_parts.append(f'node["{tag_key}"="{tag_value}"]({bbox_str});way["{tag_key}"="{tag_value}"]({bbox_str});')

    full_query = f"[out:json][timeout:25];({''.join(query_parts)});out center;"

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

        if not pois: return gpd.GeoDataFrame()
        df_pois = pd.DataFrame(pois)
        return transfo_geodataframe(df_pois, 'longitude', 'latitude')

    except requests.exceptions.RequestException as e:
        st.error(f"Erreur de requête Overpass : {e}")
        return gpd.GeoDataFrame()


@st.cache_data(show_spinner=False)
def _geocoder_adresse_nominatim_api(adresse):
    """Logique pure : Géocode une adresse via Nominatim."""
    if not adresse or not isinstance(adresse, str): return None, None, None
    url, params = "https://nominatim.openstreetmap.org/search", {'q': adresse, 'format': 'json', 'limit': 1,
                                                                 'countrycodes': 'fr'}
    headers = {'User-Agent': 'Streamlit_App_Geo_Analysis'}
    try:
        time.sleep(1.1)
        response = requests.get(url, params=params, headers=headers, timeout=20)
        response.raise_for_status()
        results = response.json()
        if results:
            return float(results[0]['lat']), float(results[0]['lon']), results[0].get('display_name',
                                                                                      'Adresse non disponible')
        return None, None, None
    except requests.exceptions.RequestException as e:
        print(f"Erreur API : {e}")
        return None, None, None


@st.cache_data(show_spinner="Géocodage de l'adresse en cours...")
def geocoder_adresse_nominatim_ui(adresse):
    """Géocode une adresse et retourne un dict."""
    lat, lon, display_name = _geocoder_adresse_nominatim_api(adresse)
    if lat and lon:
        st.success(f"Adresse trouvée : {display_name}")
        return {"latitude": lat, "longitude": lon, "denominationunitelegale": adresse, "adresse": display_name}
    else:
        st.warning(f"L'adresse '{adresse}' n'a pas pu être trouvée.")
        return None


@st.cache_data(show_spinner="Recherche des bâtiments (Overpass API)...")
def rechercher_batiments_osm(bbox):
    """Interroge l'API Overpass pour trouver les bâtiments (Version Robuste)."""
    if not bbox or len(bbox) != 4:
        st.error("❌ Erreur Interne : La zone de recherche est invalide.")
        return gpd.GeoDataFrame()

    try:
        bbox_poly = box(*bbox)
        gdf_bbox = gpd.GeoDataFrame([1], geometry=[bbox_poly], crs="EPSG:4326")
        area_km2 = gdf_bbox.to_crs("EPSG:2154").area[0] / 1_000_000
        if area_km2 > 50:
            st.warning(f"⚠️ Zone trop grande ({area_km2:.1f} km²). Recherche annulée.")
            return gpd.GeoDataFrame()
    except Exception:
        pass

    bbox_str = f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}"
    overpass_url = "http://overpass-api.de/api/interpreter"
    overpass_query = f"[out:json][timeout:25];(way['building']({bbox_str});relation['building']({bbox_str}););out geom;"

    try:
        response = requests.get(overpass_url, params={'data': overpass_query}, timeout=30)
        if response.status_code != 200:
            st.error(f"❌ Erreur API Overpass (Code {response.status_code}).")
            return gpd.GeoDataFrame()
        data = response.json()
    except Exception as e:
        st.error(f"❌ Erreur technique lors de la requête : {e}")
        return gpd.GeoDataFrame()

    geometries = []
    for element in data.get('elements', []):
        if 'geometry' in element:
            coords = [(node['lon'], node['lat']) for node in element['geometry']]
            if len(coords) >= 3:
                try:
                    geometries.append(shape({'type': 'Polygon', 'coordinates': [coords]}))
                except:
                    pass

    if not geometries: return gpd.GeoDataFrame()
    gdf = gpd.GeoDataFrame(geometry=geometries, crs="EPSG:4326")

    try:
        gdf_metric = gdf.to_crs("EPSG:2154")
        gdf['surface_m2'] = gdf_metric.area.round(0)
    except Exception as e:
        st.error(f"Erreur calcul surface : {e}")
        return gpd.GeoDataFrame()

    return gdf


# =================================================================
# HELPERS CARTOGRAPHIE
# =================================================================

def _ajouter_couche_socio(m, gdf_socio, colonne_socio, nom_indicateur_socio):
    colormap, single_value_info = None, None
    if gdf_socio is None or gdf_socio.empty or not colonne_socio: return colormap, single_value_info
    if colonne_socio not in gdf_socio.columns: gdf_socio[colonne_socio] = pd.NA

    gdf_clean = gdf_socio.dropna(subset=['geometry']).copy()
    if gdf_clean.empty: return colormap, single_value_info

    valeurs = gdf_clean[colonne_socio].dropna()
    if valeurs.nunique() > 1:
        colormap = cm.LinearColormap(colors=['#ffffcc', '#fd8d3c', '#800026'], vmin=valeurs.min(), vmax=valeurs.max())
        colormap.caption = nom_indicateur_socio or colonne_socio
    elif valeurs.nunique() == 1:
        single_value_info = {"label": nom_indicateur_socio, "value": valeurs.iloc[0]}

    tooltip_col = f"{colonne_socio}_display"
    gdf_clean[tooltip_col] = gdf_clean[colonne_socio].apply(
        lambda x: "ND" if pd.isna(x) else f"{x:,.0f}".replace(",", " "))

    def style_fn(feature):
        val = feature['properties'].get(colonne_socio)
        style = {'fillOpacity': 0.7, 'weight': 0.5, 'color': '#555555'}
        if pd.isna(val):
            style.update({'fillColor': '#cccccc', 'fillOpacity': 0.5})
        elif colormap:
            style['fillColor'] = colormap(val)
        elif single_value_info:
            style['fillColor'] = '#800026'
        else:
            style['fillOpacity'] = 0
        return style

    cle_nom = 'NOM_COM' if 'NOM_COM' in gdf_clean.columns else 'NOM_DEP'
    folium.GeoJson(
        gdf_clean, name="Données Socio-Éco", style_function=style_fn,
        highlight_function=lambda x: {'weight': 1, 'color': '#555555', 'fillOpacity': 0.8},
        tooltip=folium.features.GeoJsonTooltip(fields=[cle_nom, tooltip_col],
                                               aliases=['Zone:', f'{nom_indicateur_socio}:'])
    ).add_to(m)
    return colormap, single_value_info


def _ajouter_couche_risques_inondation(m, gdf):
    if gdf is None or gdf.empty: return
    fg = folium.FeatureGroup(name=f"Risque Inondation", show=True).add_to(m)
    cmap = {'Aléa fort': '#b30000', 'Aléa moyen': '#e34a33', 'Aléa faible': '#fdbb84'}
    folium.GeoJson(
        gdf,
        style_function=lambda x: {'fillColor': cmap.get(x['properties'].get('NIVEAU_ALEA'), '#808080'),
                                  'color': 'black', 'weight': 0.5, 'fillOpacity': 0.5},
        tooltip=folium.features.GeoJsonTooltip(fields=['NIVEAU_ALEA'], aliases=['Risque:'])
    ).add_to(fg)


def _ajouter_couche_risques_rga(m, gdf):
    if gdf is None or gdf.empty: return
    fg = folium.FeatureGroup(name=f"Risque Sécheresse", show=True).add_to(m)
    cmap = {'aléa fort': '#d95f02', 'aléa moyen': '#fd8d3c', 'aléa faible': '#fee6ce'}
    folium.GeoJson(
        gdf,
        style_function=lambda x: {'fillColor': cmap.get(x['properties'].get('NIVEAU_ALEA', '').lower(), '#bdbdbd'),
                                  'color': 'black', 'weight': 0.5, 'fillOpacity': 0.5},
        tooltip=folium.features.GeoJsonTooltip(fields=['NIVEAU_ALEA'], aliases=['Risque:'])
    ).add_to(fg)


# =================================================================
# FONCTION CARTE ENRICHIE (PRINCIPALE)
# =================================================================

def creer_carte_enrichie(gdf_etablissements, lat_centre, lon_centre,
                         gdf_socio=None, colonne_socio=None, nom_indicateur_socio=None,
                         gdf_poi=None, gdf_batiments=None, gdf_inondations=None, gdf_rga=None,
                         mode_affichage_etablissements='Points', rayon_cercles=1000, temps_isochrones=10,
                         df_coefficients=None,
                         poi_lat=None, poi_lon=None,
                         poi_analysis_mode='Isochrones', poi_radius_meters=1000,
                         ref_lat=None, ref_lon=None, ref_nom="Votre Établissement"):
    """
    Crée une carte complète avec Fullscreen et point de référence.
    """
    m = folium.Map(location=[lat_centre, lon_centre], zoom_start=11, tiles="OpenStreetMap")
    legend_enseignes = {}

    # 1. Couches Contextuelles
    colormap, single_value_info = _ajouter_couche_socio(m, gdf_socio, colonne_socio, nom_indicateur_socio)
    _ajouter_couche_risques_inondation(m, gdf_inondations)
    _ajouter_couche_risques_rga(m, gdf_rga)

    # 2. Point de Référence
    if ref_lat is not None and ref_lon is not None:
        fg_ref = folium.FeatureGroup(name="📍 Votre Établissement", show=True).add_to(m)
        folium.Marker(
            location=[ref_lat, ref_lon],
            popup=folium.Popup(f"<b>{ref_nom}</b><br>(Point de référence)", max_width=300),
            tooltip=f"Votre Établissement : {ref_nom}",
            icon=folium.Icon(color='red', icon='star', prefix='fa')
        ).add_to(fg_ref)

    # 3. Zone Analyse Utilisateur
    zone_geom = None
    if poi_lat and poi_lon:
        fg_user = folium.FeatureGroup(name="Zone d'Analyse", show=True).add_to(m)
        folium.Marker([poi_lat, poi_lon], tooltip="Cible",
                      icon=folium.Icon(icon='crosshairs', prefix='fa', color='black')).add_to(fg_user)

        if poi_analysis_mode == 'Isochrones':
            feat = calculer_isochrone_et_cacher(poi_lon, poi_lat, temps_isochrones * 60 * 0.9)
            if feat:
                zone_geom = shape(feat['geometry'])
                folium.GeoJson(feat, style_function=lambda x: {'fillColor': 'black', 'color': 'black', 'weight': 2,
                                                               'fillOpacity': 0.1}).add_to(fg_user)
        elif poi_analysis_mode == "Cercle d'influence":
            zone_geom = \
            gpd.GeoDataFrame(geometry=[Point(poi_lon, poi_lat)], crs="EPSG:4326").to_crs("EPSG:3857").buffer(
                poi_radius_meters).to_crs("EPSG:4326").geometry.iloc[0]
            folium.GeoJson(gpd.GeoDataFrame(geometry=[zone_geom], crs="EPSG:4326"),
                           style_function=lambda x: {'fillColor': 'black', 'color': 'black', 'weight': 2,
                                                     'fillOpacity': 0.1}).add_to(fg_user)

    # 4. Bâtiments
    if gdf_batiments is not None and not gdf_batiments.empty:
        fg_bat = folium.FeatureGroup(name="Bâtiments", show=True).add_to(m)
        folium.GeoJson(gdf_batiments, style_function=lambda x: {'fillColor': '#3498db', 'color': '#2980b9', 'weight': 1,
                                                                'fillOpacity': 0.6},
                       tooltip=folium.features.GeoJsonTooltip(fields=['surface_m2'])).add_to(fg_bat)

    # 5. Établissements (Concurrents)
    if gdf_etablissements is not None and not gdf_etablissements.empty:
        fg_etab = folium.FeatureGroup(name="Concurrents", show=True).add_to(m)
        couleurs = ['#377eb8', '#4daf4a', '#984ea3', '#ff7f00', '#ffff33', '#a65628', '#f781bf']
        noms_uniques = gdf_etablissements['nom_etablissement'].dropna().unique()
        legend_enseignes = {nom: couleurs[i % len(couleurs)] for i, nom in enumerate(noms_uniques)}

        for _, row in gdf_etablissements.iterrows():
            color = legend_enseignes.get(row['nom_etablissement'], 'gray')
            popup = folium.Popup(f"<b>{row.get('nom_etablissement')}</b><br>{row.get('adresse_simplifiee')}",
                                 max_width=300)

            tooltip_txt = row['nom_etablissement']
            b_color, weight, radius = color, 2, 6
            if zone_geom and row.geometry.within(zone_geom):
                tooltip_txt = f"DANS LA ZONE - {tooltip_txt}"
                b_color, weight, radius = 'black', 3, 8

            if mode_affichage_etablissements in ['Points', 'Isochrones']:
                folium.CircleMarker([row.geometry.y, row.geometry.x], radius=radius, color=b_color, weight=weight,
                                    fill=True, fill_color=color, fill_opacity=0.9, popup=popup,
                                    tooltip=tooltip_txt).add_to(fg_etab)

                if mode_affichage_etablissements == 'Isochrones':
                    coeff = 0.9
                    if df_coefficients is not None:
                        match = df_coefficients[df_coefficients['ville'].str.lower() == row.get('ville', '').lower()]
                        if not match.empty: coeff = match['coefficient'].iloc[0]
                    feat = calculer_isochrone_et_cacher(row.geometry.x, row.geometry.y, temps_isochrones * coeff * 60)
                    if feat: folium.GeoJson(feat,
                                            style_function=lambda x, c=color: {'fillColor': c, 'color': c, 'weight': 2,
                                                                               'fillOpacity': 0.25}).add_to(fg_etab)

            elif mode_affichage_etablissements == 'Cercles d\'influence':
                folium.Circle([row.geometry.y, row.geometry.x], radius=rayon_cercles, color=color, fill=True,
                              fill_color=color, fill_opacity=0.2).add_to(fg_etab)
                folium.CircleMarker([row.geometry.y, row.geometry.x], radius=4, color='white', weight=1, fill=True,
                                    fill_color=color, fill_opacity=1, popup=popup, tooltip=tooltip_txt).add_to(fg_etab)

    # 6. POI
    if gdf_poi is not None and not gdf_poi.empty:
        fg_poi = folium.FeatureGroup(name="Points d'Intérêt", show=True).add_to(m)
        for _, poi in gdf_poi.iterrows():
            cat = poi.get('categorie', 'Divers')
            conf = POI_CONFIG.get(cat, {'icon': {'icon': 'info', 'color': 'gray', 'prefix': 'fa'}})
            folium.Marker([poi.geometry.y, poi.geometry.x], tooltip=f"{cat}: {poi['name']}",
                          icon=folium.Icon(icon=conf['icon']['icon'], color=conf['icon']['color'],
                                           prefix=conf['icon']['prefix'])).add_to(fg_poi)

    # 7. Fullscreen (Le Bouton Magique)
    Fullscreen(
        position='topright',
        title='Plein écran',
        title_cancel='Quitter plein écran',
        force_separate_button=True
    ).add_to(m)

    folium.LayerControl().add_to(m)
    return m, legend_enseignes, colormap, single_value_info