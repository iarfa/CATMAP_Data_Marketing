# Fichier: fonctions_cartographie.py

import folium
import geopandas as gpd
import pandas as pd
import requests
import time
import streamlit as st
import branca.colormap as cm
from streamlit_folium import st_folium
from shapely.geometry import shape, box, Point
from folium.plugins import Fullscreen, HeatMap

# On importe la config locale (si besoin pour les icônes)
from config import POI_CONFIG
from fonctions_basiques import transfo_geodataframe


# =================================================================
# 1. FONCTIONS API & UTILITAIRES
# =================================================================

@st.cache_data
def recherche_etablissements_osm(noms_etablissements, villes, max_etablissements=50):
    """Recherche des établissements via Nominatim et met le résultat en cache."""
    url, headers, donnees = "https://nominatim.openstreetmap.org/search", {"User-Agent": "Streamlit_App_Geo"}, []
    if len(villes) > 200:
        villes = villes[:200]
    for nom in noms_etablissements:
        for ville in villes:
            params = {"q": f"{nom}, {ville}, France", "format": "json", "limit": max_etablissements,
                      "addressdetails": 1}
            try:
                response = requests.get(url, params=params, headers=headers, timeout=20)
                if response.status_code == 200:
                    for resultat in response.json():
                        donnees.append({
                            "nom_etablissement": nom,
                            "ville": resultat.get("address", {}).get("city", ville),
                            "nom_OSM": resultat.get("name", "N/A"),
                            "adresse": resultat.get("display_name", ""),
                            "latitude": float(resultat.get("lat", 0)),
                            "longitude": float(resultat.get("lon", 0))
                        })
            except Exception:
                pass
    return pd.DataFrame(donnees)


@st.cache_data
def calculer_isochrone_et_cacher(longitude, latitude, temps_secondes):
    """Appelle l'API ORS et met le résultat en cache."""
    try:
        response = requests.post("http://localhost:8080/ors/v2/isochrones/driving-car",
                                 json={"locations": [[longitude, latitude]], "range": [temps_secondes]},
                                 headers={'Content-Type': 'application/json'}, timeout=30)
        if response.status_code == 200 and response.json().get('features'):
            return response.json()['features'][0]
    except Exception:
        pass
    return None


@st.cache_data
def rechercher_poi_osm(bounding_box, tags_a_chercher):
    """Interroge l'API Overpass pour trouver des POI."""
    overpass_url = "http://overpass-api.de/api/interpreter"
    bbox_str = f"{bounding_box[1]},{bounding_box[0]},{bounding_box[3]},{bounding_box[2]}"
    query_parts = [f'node["{k}"="{v}"]({bbox_str});way["{k}"="{v}"]({bbox_str});' for k, v in tags_a_chercher.items()]
    full_query = f"[out:json][timeout:25];({''.join(query_parts)});out center;"

    try:
        response = requests.get(overpass_url, params={'data': full_query}, timeout=30)
        if response.status_code == 200:
            data = response.json()
            pois = []
            for element in data.get('elements', []):
                lon = element.get('lon') or element.get('center', {}).get('lon')
                lat = element.get('lat') or element.get('center', {}).get('lat')
                if lon and lat:
                    pois.append({'name': element.get('tags', {}).get('name', 'N/A'), 'latitude': lat, 'longitude': lon})

            if pois:
                return transfo_geodataframe(pd.DataFrame(pois), 'longitude', 'latitude')
    except Exception:
        pass
    return gpd.GeoDataFrame()


@st.cache_data(show_spinner=False)
def _geocoder_adresse_nominatim_api(adresse):
    if not adresse: return None, None, None
    try:
        time.sleep(1.1)
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params={'q': adresse, 'format': 'json', 'limit': 1, 'countrycodes': 'fr'},
                         headers={'User-Agent': 'Streamlit_App_Geo'}, timeout=10)
        if r.status_code == 200 and r.json():
            res = r.json()[0]
            return float(res['lat']), float(res['lon']), res.get('display_name', 'Adresse trouvée')
    except Exception:
        pass
    return None, None, None


@st.cache_data(show_spinner="Géocodage...")
def geocoder_adresse_nominatim_ui(adresse):
    lat, lon, name = _geocoder_adresse_nominatim_api(adresse)
    if lat:
        st.success(f"Adresse : {name}")
        return {"latitude": lat, "longitude": lon, "denominationunitelegale": adresse, "adresse": name}
    st.warning(f"Adresse introuvable : {adresse}")
    return None


@st.cache_data(show_spinner="Recherche bâtiments...")
def rechercher_batiments_osm(bbox):
    if not bbox: return gpd.GeoDataFrame()
    try:
        bbox_str = f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}"
        q = f"[out:json][timeout:25];(way['building']({bbox_str});relation['building']({bbox_str}););out geom;"
        r = requests.get("http://overpass-api.de/api/interpreter", params={'data': q}, timeout=45)
        if r.status_code != 200: return gpd.GeoDataFrame()

        geoms = []
        for el in r.json().get('elements', []):
            if 'geometry' in el:
                coords = [(pt['lon'], pt['lat']) for pt in el['geometry']]
                if len(coords) >= 3: geoms.append(shape({'type': 'Polygon', 'coordinates': [coords]}))

        if not geoms: return gpd.GeoDataFrame()
        gdf = gpd.GeoDataFrame(geometry=geoms, crs="EPSG:4326")
        gdf['surface_m2'] = gdf.to_crs("EPSG:2154").area.round(0)
        return gdf
    except Exception:
        return gpd.GeoDataFrame()


# =================================================================
# 2. HELPERS COUCHES (SOCIO, RISQUES, DVF)
# =================================================================

def _ajouter_couche_socio(m, gdf_socio, colonne_socio, nom_indicateur_socio):
    colormap, single_val = None, None
    if gdf_socio is None or gdf_socio.empty or not colonne_socio: return None, None

    gdf_clean = gdf_socio.dropna(subset=['geometry', colonne_socio]).copy()
    if gdf_clean.empty: return None, None

    vals = gdf_clean[colonne_socio]
    if vals.nunique() > 1:
        colormap = cm.LinearColormap(colors=['#ffffcc', '#fd8d3c', '#800026'], vmin=vals.min(), vmax=vals.max())
        colormap.caption = nom_indicateur_socio
    else:
        single_val = {"label": nom_indicateur_socio, "value": vals.iloc[0]}

    folium.GeoJson(
        gdf_clean, name="Socio-Démo",
        style_function=lambda x: {
            'fillColor': colormap(x['properties'][colonne_socio]) if colormap else '#800026',
            'color': '#555', 'weight': 0.5, 'fillOpacity': 0.7
        },
        tooltip=folium.features.GeoJsonTooltip(
            fields=[colonne_socio], aliases=[f'{nom_indicateur_socio}:']
        )
    ).add_to(m)
    return colormap, single_val


def _ajouter_couche_risques_inondation(m, gdf):
    if gdf is None or gdf.empty: return
    fg = folium.FeatureGroup(name=f"Risque Inondation", show=True).add_to(m)
    colors = {'Aléa fort': '#b30000', 'Aléa moyen': '#e34a33', 'Aléa faible': '#fdbb84'}
    folium.GeoJson(gdf, style_function=lambda x: {'fillColor': colors.get(x['properties'].get('NIVEAU_ALEA'), 'gray'),
                                                  'color': 'black', 'weight': 0.5, 'fillOpacity': 0.5},
                   tooltip=folium.features.GeoJsonTooltip(fields=['NIVEAU_ALEA'], aliases=['Risque:'])).add_to(fg)


def _ajouter_couche_risques_rga(m, gdf):
    if gdf is None or gdf.empty: return
    fg = folium.FeatureGroup(name=f"Risque Sécheresse", show=True).add_to(m)
    colors = {'aléa fort': '#d95f02', 'aléa moyen': '#fd8d3c', 'aléa faible': '#fee6ce'}
    folium.GeoJson(gdf, style_function=lambda x: {
        'fillColor': colors.get(x['properties'].get('NIVEAU_ALEA', '').lower(), 'gray'), 'color': 'black',
        'weight': 0.5, 'fillOpacity': 0.5},
                   tooltip=folium.features.GeoJsonTooltip(fields=['NIVEAU_ALEA'], aliases=['Risque:'])).add_to(fg)


def _ajouter_couche_dvf_heatmap(m, df_dvf, type_filtre="Tous"):
    """Ajoute une Heatmap DVF."""
    if df_dvf is None or df_dvf.empty: return

    # Limite outliers (95%)
    max_val = df_dvf['prix_m2'].quantile(0.95)
    data = df_dvf[['latitude', 'longitude', 'prix_m2']].copy()
    data['prix_m2'] = data['prix_m2'].clip(upper=max_val)
    heat_data = data.values.tolist()

    if "Commerce" in type_filtre:
        gradient = {0.2: '#807dba', 0.5: '#e08214', 1.0: '#b30000'}
        name_layer = "🔥 Heatmap: Coût Commercial"
    else:
        gradient = {0.2: '#4575b4', 0.4: '#91bfdb', 0.6: '#fee090', 0.8: '#fc8d59', 1.0: '#d73027'}
        name_layer = "🔥 Heatmap: Prix Résidentiel"

    HeatMap(
        heat_data,
        name=name_layer,
        min_opacity=0.3, radius=13, blur=15, max_zoom=15,
        gradient=gradient
    ).add_to(m)


def _ajouter_couche_dvf_points(m, df_dvf, type_filtre="Tous"):
    """
    Ajoute les transactions DVF sous forme de points interactifs.
    - Tooltip (Survol) : Résumé (Type + Prix m²)
    - Popup (Clic) : Détail complet HTML
    """
    if df_dvf is None or df_dvf.empty:
        return None

    # 1. Nettoyage
    df_clean = df_dvf.dropna(subset=['latitude', 'longitude', 'prix_m2']).copy()
    if df_clean.empty:
        return None

    # 2. Bornes pour l'échelle de couleur (Quantiles 5-95%)
    vmin = df_clean['prix_m2'].quantile(0.05)
    vmax = df_clean['prix_m2'].quantile(0.95)
    if vmin == vmax:
        vmin, vmax = vmin * 0.9, vmax * 1.1

    # 3. Création de la Colormap
    colormap = cm.LinearColormap(
        colors=['#2c7bb6', '#abd9e9', '#ffffbf', '#fdae61', '#d7191c'],
        vmin=vmin, vmax=vmax,
        caption=f"Prix m² ({type_filtre})"
    )

    # 4. Groupe de calques Folium
    fg_dvf = folium.FeatureGroup(name=f"Transactions ({type_filtre})", show=True)
    df_clean = df_clean.sort_values('prix_m2')

    for _, row in df_clean.iterrows():
        lat, lon = row['latitude'], row['longitude']
        prix_m2 = row['prix_m2']
        valeur = row.get('valeur_fonciere', 0)
        surface = row.get('surface_reelle_bati', 0)
        type_loc = row.get('type_local', 'Indéfini')

        # Gestion Date
        date_txt = "N/A"
        if 'date_mutation' in row and pd.notnull(row['date_mutation']):
            try:
                date_txt = row['date_mutation'].strftime('%d/%m/%Y')
            except:
                date_txt = str(row['date_mutation'])[:10]

        # --- CONTENU POPUP (CLIC) ---
        popup_html = f"""
        <div style='font-family:sans-serif; font-size:13px; min-width:180px;'>
            <h5 style='margin:0; padding-bottom:5px; border-bottom:2px solid #3388ff; color:#333;'>
                Transaction
            </h5>
            <ul style='list-style-type:none; padding-left:0; margin-top:8px; line-height:1.4em;'>
                <li>📅 <b>Date :</b> {date_txt}</li>
                <li>🏠 <b>Type :</b> {type_loc}</li>
                <li>📏 <b>Surface :</b> {surface:.0f} m²</li>
                <li>💰 <b>Prix Total :</b> {valeur:,.0f} €</li>
                <li style='margin-top:5px; font-weight:bold; color:#d7191c; font-size:14px;'>
                    📊 {prix_m2:,.0f} €/m²
                </li>
            </ul>
        </div>
        """

        # --- CONTENU TOOLTIP (SURVOL) ---
        tooltip_txt = f"{type_loc} ({prix_m2:,.0f} €/m²)"

        # Ajout du marqueur
        folium.CircleMarker(
            location=[lat, lon],
            radius=6,
            color='#555',
            weight=0.5,
            fill=True,
            fill_color=colormap(prix_m2),
            fill_opacity=0.9,
            tooltip=tooltip_txt,  # Affiche l'info au survol
            popup=folium.Popup(popup_html, max_width=300)  # Affiche l'info au clic
        ).add_to(fg_dvf)

    fg_dvf.add_to(m)
    return colormap


# =================================================================
# 3. FONCTIONS DE CRÉATION DE CARTE
# =================================================================

def creer_carte_enrichie(gdf_etablissements, lat_centre, lon_centre,
                         gdf_socio=None, colonne_socio=None, nom_indicateur_socio=None,
                         gdf_poi=None, gdf_batiments=None, gdf_inondations=None, gdf_rga=None,
                         mode_affichage_etablissements='Points', rayon_cercles=1000, temps_isochrones=10,
                         df_coefficients=None, poi_lat=None, poi_lon=None,
                         poi_analysis_mode='Isochrones', poi_radius_meters=1000,
                         ref_lat=None, ref_lon=None, ref_nom="Votre Établissement",
                         df_dvf=None, dvf_type_filtre="Tous"):
    """CARTE POUR L'ANALYSE DE CONCURRENCE"""

    m = folium.Map(location=[lat_centre, lon_centre], zoom_start=11, tiles="OpenStreetMap")

    if df_dvf is not None:
        _ajouter_couche_dvf_heatmap(m, df_dvf, dvf_type_filtre)

    cmap, single_val = _ajouter_couche_socio(m, gdf_socio, colonne_socio, nom_indicateur_socio)
    _ajouter_couche_risques_inondation(m, gdf_inondations)
    _ajouter_couche_risques_rga(m, gdf_rga)

    if ref_lat and ref_lon:
        folium.Marker([ref_lat, ref_lon], icon=folium.Icon(color='red', icon='star', prefix='fa'),
                      tooltip=ref_nom, popup=f"<b>{ref_nom}</b>").add_to(m)

    legend = {}
    if gdf_etablissements is not None and not gdf_etablissements.empty:
        fg = folium.FeatureGroup(name="Concurrents", show=True).add_to(m)
        colors = ['#377eb8', '#4daf4a', '#984ea3', '#ff7f00', '#ffff33', '#a65628', '#f781bf']
        names = gdf_etablissements['nom_etablissement'].dropna().unique()
        legend = {n: colors[i % len(colors)] for i, n in enumerate(names)}

        for _, row in gdf_etablissements.iterrows():
            col = legend.get(row['nom_etablissement'], 'gray')
            popup = folium.Popup(f"<b>{row.get('nom_etablissement')}</b><br>{row.get('adresse_simplifiee')}",
                                 max_width=300)

            tooltip_txt = row['nom_etablissement']
            folium.CircleMarker([row.geometry.y, row.geometry.x], radius=6, color=col, fill=True, fill_opacity=0.9,
                                tooltip=tooltip_txt, popup=popup).add_to(fg)

            if mode_affichage_etablissements == 'Isochrones':
                feat = calculer_isochrone_et_cacher(row.geometry.x, row.geometry.y, temps_isochrones * 60 * 0.9)
                if feat: folium.GeoJson(feat, style_function=lambda x, c=col: {'fillColor': c, 'color': c, 'weight': 1,
                                                                               'fillOpacity': 0.2}).add_to(fg)
            elif mode_affichage_etablissements == 'Cercles d\'influence':
                folium.Circle([row.geometry.y, row.geometry.x], radius=rayon_cercles, color=col, fill=True,
                              fill_color=col, fill_opacity=0.2).add_to(fg)

    if gdf_poi is not None and not gdf_poi.empty:
        fg_poi = folium.FeatureGroup(name="POI", show=True).add_to(m)
        for _, r in gdf_poi.iterrows():
            folium.Marker([r.geometry.y, r.geometry.x], icon=folium.Icon(color='gray', icon='info-sign'),
                          tooltip=r['name']).add_to(fg_poi)

    Fullscreen().add_to(m)
    folium.LayerControl().add_to(m)
    return m, legend, cmap, single_val


def creer_carte_implantation(lat_centre, lon_centre, zone_analyse_geom, gdf_poi_trouves,
                             gdf_socio=None, colonne_socio=None, nom_indicateur_socio=None,
                             gdf_batiments=None, gdf_inondations=None, gdf_rga=None,
                             nom_point_central="Cible", adresse_point_central="", analysis_mode='Isochrones',
                             df_dvf=None, dvf_type_filtre="Tous", mode_affichage_dvf="Points"):
    m = folium.Map(location=[lat_centre, lon_centre], zoom_start=15, tiles="OpenStreetMap")

    # =========================================================
    # 1. ZONE D'ANALYSE (Fond de carte)
    # =========================================================
    if zone_analyse_geom and analysis_mode != 'Point seul':
        style_zone = {
            'fillColor': '#A67C00',  # Doré (Square)
            'color': '#A67C00',
            'weight': 2,
            'fillOpacity': 0.1
        }
        folium.GeoJson(
            zone_analyse_geom,
            style_function=lambda x: style_zone,
            name="Zone d'analyse"
        ).add_to(m)

    # =========================================================
    # 2. DVF (Immobilier)
    # =========================================================
    legend_dvf = None
    if df_dvf is not None and not df_dvf.empty:
        if mode_affichage_dvf == "Heatmap":
            _ajouter_couche_dvf_heatmap(m, df_dvf, dvf_type_filtre)
        else:
            legend_dvf = _ajouter_couche_dvf_points(m, df_dvf, dvf_type_filtre)

    # =========================================================
    # 3. SOCIO & RISQUES (Couches contextuelles)
    # =========================================================
    cmap, single_val = _ajouter_couche_socio(m, gdf_socio, colonne_socio, nom_indicateur_socio)
    _ajouter_couche_risques_inondation(m, gdf_inondations)
    _ajouter_couche_risques_rga(m, gdf_rga)

    # =========================================================
    # 4. POINT CENTRAL
    # =========================================================
    folium.Marker(
        [lat_centre, lon_centre],
        icon=folium.Icon(color='red', icon='crosshairs', prefix='fa'),
        tooltip=nom_point_central,
        popup=f"<b>{nom_point_central}</b><br>{adresse_point_central}",
        z_index_offset=1000
    ).add_to(m)

    # =========================================================
    # 5. BÂTIMENTS (Coloration Dynamique selon Risque)
    # =========================================================
    if gdf_batiments is not None and not gdf_batiments.empty:
        fg_bat = folium.FeatureGroup(name="Bâtiments (Audit)", show=True).add_to(m)

        # Fonction de style dynamique
        def style_batiment(feature):
            props = feature['properties']

            # Par défaut : Bleu (Sain)
            color = '#3498db'
            fill_opacity = 0.5
            weight = 1

            # HIERARCHIE DES RISQUES (Rouge > Orange > Bleu)

            # 1. Inondation (Priorité absolue) -> ROUGE
            if props.get('has_Inondation'):
                color = '#e74c3c'
                fill_opacity = 0.8
                weight = 2

            # 2. Argile (RGA) -> ORANGE
            elif props.get('has_Argile'):
                color = '#e67e22'
                fill_opacity = 0.7

            return {
                'fillColor': color,
                'color': color,
                'weight': weight,
                'fillOpacity': fill_opacity
            }

        # Info-bulle dynamique (Tooltip)
        tooltip_fields = ['surface_m2']
        tooltip_aliases = ['Surface:']

        # On ajoute les infos risques si elles existent dans les données
        if 'niveau_Inondation' in gdf_batiments.columns:
            tooltip_fields.append('niveau_Inondation')
            tooltip_aliases.append('Inondation:')

        if 'niveau_Argile' in gdf_batiments.columns:
            tooltip_fields.append('niveau_Argile')
            tooltip_aliases.append('Argile:')

        folium.GeoJson(
            gdf_batiments,
            style_function=style_batiment,
            tooltip=folium.features.GeoJsonTooltip(fields=tooltip_fields, aliases=tooltip_aliases)
        ).add_to(fg_bat)

    # =========================================================
    # 6. POI
    # =========================================================
    if gdf_poi_trouves is not None and not gdf_poi_trouves.empty:
        fg_poi = folium.FeatureGroup(name="POI Zone", show=True).add_to(m)
        # Import local pour éviter les cycles si besoin, ou utiliser l'argument passé
        from config import POI_CONFIG

        for _, r in gdf_poi_trouves.iterrows():
            cat = r.get('categorie', '')
            icon_config = POI_CONFIG.get(cat, {}).get('icon', {'icon': 'map-marker', 'color': 'gray', 'prefix': 'fa'})

            folium.Marker(
                [r.geometry.y, r.geometry.x],
                icon=folium.Icon(**icon_config),
                tooltip=f"{cat}: {r['name']}"
            ).add_to(fg_poi)

    Fullscreen().add_to(m)
    folium.LayerControl().add_to(m)

    return m, cmap, single_val, legend_dvf

def analyser_environnement_naturel(bbox):
    """
    Scanne la zone pour détecter la végétation (Proxy Incendie & Chaleur).
    Retourne :
    - distance_foret (m) : Distance au bois le plus proche
    - ratio_vegetation (%) : Part de la surface couverte par de la verdure
    """
    try:
        # Tags OSM pour la nature
        tags_nature = {
            'landuse': ['forest', 'grass', 'meadow', 'orchard', 'vineyard'],
            'natural': ['wood', 'scrub', 'heath', 'tree_row'],
            'leisure': ['park', 'garden', 'golf_course']
        }

        # On récupère les géométries (Polygones)
        # Note : On suppose que ox est importé comme osmnx
        import osmnx as ox
        gdf_nature = ox.features_from_bbox(bbox=bbox, tags=tags_nature)

        if gdf_nature.empty:
            return 9999, 0.0  # Pas de nature détectée

        # 1. Calcul Risque Incendie (Proximité Forêt/Bois)
        # On filtre uniquement ce qui brûle fort (Bois/Forêt)
        mask_foret = (gdf_nature['landuse'].isin(['forest'])) | (gdf_nature['natural'].isin(['wood', 'scrub']))
        gdf_foret = gdf_nature[mask_foret]

        dist_foret = 9999
        if not gdf_foret.empty:
            # On prend le centre de la bbox comme point de référence (le site)
            centre_lat = (bbox[1] + bbox[3]) / 2
            centre_lon = (bbox[0] + bbox[2]) / 2
            point_ref = gpd.GeoSeries([Point(centre_lon, centre_lat)], crs="EPSG:4326").to_crs("EPSG:3857")

            # Distance minimale à un polygone de forêt
            geom_foret = gdf_foret.to_crs("EPSG:3857").unary_union
            dist_foret = point_ref.distance(geom_foret).iloc[0]

        # 2. Calcul Confort Thermique (Ratio Végétal)
        # Surface totale de la bbox (approx)
        xmin, ymin, xmax, ymax = bbox
        # Calcul surface simple (degrés -> mètres approx)
        # Pour faire simple : on fait le ratio des surfaces projetées
        gdf_nature_proj = gdf_nature.to_crs("EPSG:3857")
        surface_veg = gdf_nature_proj.area.sum()

        # Surface de la zone d'étude (Bbox)
        from shapely.geometry import box
        poly_bbox = gpd.GeoSeries([box(xmin, ymin, xmax, ymax)], crs="EPSG:4326").to_crs("EPSG:3857")
        surface_totale = poly_bbox.area.iloc[0]

        ratio = (surface_veg / surface_totale) * 100

        return dist_foret, ratio

    except Exception as e:
        print(f"Erreur analyse nature : {e}")
        return 9999, 0.0