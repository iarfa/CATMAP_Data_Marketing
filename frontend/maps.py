# Fichier: frontend/maps.py (RÉÉCRITURE INTÉGRALE)

import folium
import geopandas as gpd
import pandas as pd
import branca.colormap as cm
from folium.plugins import Fullscreen, HeatMap
from config import POI_CONFIG
from utils.geo_tools import calculer_isochrone_api
import numpy as np
import re

# --- CRITIQUE FIXÉ : DÉFINITION ABSOLUE DES SYMBOLES POUR INJECTION DANS LE NOM DU CALQUE ---
RISQUES_ABS_MAP = {
    "Inondation": {"symbole": "🌊",
                   "colors": {'aléa fort': '#08306b', 'aléa moyen': '#2171b5', 'aléa faible': '#6baed6'}},
    "Sécheresse": {"symbole": "☀️",
                   "colors": {'aléa fort': '#5D4037', 'aléa moyen': '#8D6E63', 'aléa faible': '#D7CCC8'}}
}


# =================================================================
# HELPERS COUCHES DVF (Inchangé)
# =================================================================

def _filtrer_dvf_data(df, type_filtre):
    """
    Traduit le choix utilisateur (UI) en termes techniques (Data).
    """
    if df is None or df.empty: return pd.DataFrame()

    df_clean = df.copy()

    # Mapping UI -> Data
    if type_filtre == "Résidentiel":
        # On cible les logements
        return df_clean[df_clean['type_local'].isin(['Maison', 'Appartement'])]

    elif type_filtre == "Commercial":
        # On cible les locaux commerciaux (Recherche large "Local")
        return df_clean[df_clean['type_local'].str.contains('Local', case=False, na=False)]

    # Si "Tous", on renvoie tout
    return df_clean


def _ajouter_couche_dvf_heatmap(m, df_dvf, type_filtre="Tous"):
    """Ajoute une Heatmap DVF avec filtrage correct."""
    if df_dvf is None or df_dvf.empty: return

    # 1. Filtrage
    df_filtered = _filtrer_dvf_data(df_dvf, type_filtre)
    if df_filtered.empty: return

    # 2. Préparation
    max_val = df_filtered['prix_m2'].quantile(0.95)
    data = df_filtered[['latitude', 'longitude', 'prix_m2']].copy()
    data['prix_m2'] = data['prix_m2'].clip(upper=max_val)
    heat_data = data[['latitude', 'longitude', 'prix_m2']].values.tolist()

    # 3. Style dynamique
    if type_filtre == "Commercial":
        gradient = {0.2: '#807dba', 0.5: '#e08214', 1.0: '#b30000'}  # Violet -> Rouge
        name_layer = "🔥 Heatmap: Coût Commercial"
    else:
        gradient = {0.2: '#4575b4', 0.4: '#91bfdb', 0.6: '#fee090', 0.8: '#fc8d59', 1.0: '#d73027'}  # Bleu -> Rouge
        name_layer = "🔥 Heatmap: Prix Résidentiel"

    HeatMap(
        heat_data,
        name=name_layer,
        min_opacity=0.3, radius=13, blur=15, max_zoom=15,
        gradient=gradient
    ).add_to(m)


def _ajouter_couche_dvf_points(m, df_dvf, type_filtre="Tous"):
    """
    Ajoute les transactions DVF (Points) avec Popup Riche.
    """
    if df_dvf is None or df_dvf.empty: return None

    # 1. Filtrage
    df_clean = _filtrer_dvf_data(df_dvf, type_filtre)

    # 2. Nettoyage technique (Coordonnées obligatoires)
    df_clean = df_clean.dropna(subset=['latitude', 'longitude', 'prix_m2']).copy()
    if df_clean.empty: return None

    # 3. Configuration visuelle
    COLOR_DEFAULT = '#3388ff'  # Bleu (Résidentiel)
    COLOR_COMMERCE = '#FF7F0E'  # Orange (Commercial)

    fg_dvf = folium.FeatureGroup(name=f"Transactions DVF ({type_filtre})", show=True)

    # Sécurité Volumétrie : On limite à 2000 points aléatoires pour ne pas crasher le navigateur
    if len(df_clean) > 2000:
        df_clean = df_clean.sample(2000)

    for _, row in df_clean.iterrows():
        lat, lon = row['latitude'], row['longitude']

        # Données brutes
        prix_m2 = row.get('prix_m2', 0)
        valeur = row.get('valeur_fonciere', 0)
        surface = row.get('surface_reelle_bati', 0)
        type_loc = row.get('type_local', 'Indéfini')

        # Formatage Date (YYYY-MM-DD)
        date_raw = row.get('date_mutation', 'N/A')
        date_txt = str(date_raw)[:10]

        # Choix couleur
        point_color = COLOR_COMMERCE if "Local" in str(type_loc) else COLOR_DEFAULT

        # --- POPUP HTML ENRICHI ---
        popup_html = f"""
        <div style='font-family:sans-serif; font-size:12px; min-width:200px;'>
            <h5 style='margin:0 0 8px 0; border-bottom:3px solid {point_color}; color:#333; padding-bottom:4px;'>
                {type_loc}
            </h5>
            <table style='width:100%; border-collapse:collapse;'>
                <tr>
                    <td style='color:#666;'>📅 Date</td>
                    <td style='text-align:right; font-weight:bold;'>{date_txt}</td>
                </tr>
                <tr>
                    <td style='color:#666;'>📏 Surface</td>
                    <td style='text-align:right; font-weight:bold;'>{surface:.0f} m²</td>
                </tr>
                <tr>
                    <td style='color:#666;'>💰 Prix Total</td>
                    <td style='text-align:right; font-weight:bold;'>{valeur:,.0f} €</td>
                </tr>
                <tr style='border-top:1px solid #eee;'>
                    <td style='color:#d7191c; padding-top:4px;'>📊 Prix m²</td>
                    <td style='text-align:right; font-weight:bold; color:#d7191c; padding-top:4px;'>
                        {prix_m2:,.0f} €
                    </td>
                </tr>
            </table>
        </div>
        """

        tooltip_txt = f"{type_loc} | {prix_m2:,.0f} €/m²"

        folium.CircleMarker(
            location=[lat, lon],
            radius=5,  # Point légèrement plus gros
            color='white',  # Contour blanc pour contraste
            weight=1,
            fill=True,
            fill_color=point_color,
            fill_opacity=0.8,
            tooltip=tooltip_txt,
            popup=folium.Popup(popup_html, max_width=250)
        ).add_to(fg_dvf)

    fg_dvf.add_to(m)
    return None


# =================================================================
# HELPERS COUCHES CRITIQUES (SOCIO & RISQUES)
# =================================================================

def _ajouter_couche_socio(m, gdf_socio, colonne_socio, nom_indicateur_socio):
    """
    Ajoute la couche Choroplèthe Socio-Démographique.
    (Logique conservée - NE PAS ajouter la légende à la carte).
    """
    colormap, single_val = None, None
    if gdf_socio is None or gdf_socio.empty or not colonne_socio: return None, None

    if colonne_socio not in gdf_socio.columns: return None, None

    gdf_clean = gdf_socio.dropna(subset=['geometry', colonne_socio]).copy()
    if gdf_clean.empty: return None, None

    vals = gdf_clean[colonne_socio]
    if vals.nunique() > 1:
        colormap = cm.LinearColormap(colors=['#ffffcc', '#fd8d3c', '#800026'], vmin=vals.min(), vmax=vals.max())
        colormap.caption = nom_indicateur_socio
    else:
        single_val = {"label": nom_indicateur_socio, "value": vals.iloc[0]}

    try:
        folium.GeoJson(
            gdf_clean.to_json(),
            name="Socio-Démo",
            style_function=lambda x: {
                'fillColor': colormap(x['properties'][colonne_socio]) if colormap else '#800026',
                'color': '#555', 'weight': 0.5, 'fillOpacity': 0.7
            },
            tooltip=folium.features.GeoJsonTooltip(
                fields=[colonne_socio], aliases=[f'{nom_indicateur_socio}:']
            )
        ).add_to(m)
    except Exception as e:
        print(f"Erreur de rendu GeoJson Socio: {e}")
        pass

    return colormap, single_val


def _style_risk(feature, colors):
    """Helper pour la coloration des risques (logique fusionnée)."""
    val = str(feature['properties'].get('NIVEAU_ALEA', '')).lower().replace('é', 'e')
    col = 'gray'
    if 'fort' in val:
        col = colors['aléa fort']
    elif 'moyen' in val:
        col = colors['aléa moyen']
    elif 'faible' in val:
        col = colors['aléa faible']
    return {'fillColor': col, 'color': col, 'weight': 0.5, 'fillOpacity': 0.6}


# --- NOUVEAU : FONCTION RISQUE INONDATION (CRITIQUE A) ---
def _ajouter_couche_risques_inondation(m, gdf):
    """
    Ajoute la couche Inondation avec le symbole 🌊 forcé dans le nom du calque.
    (Remplace l'ancien appel générique _ajouter_couche_risques).
    """
    if gdf is None or gdf.empty:
        return

    config = RISQUES_ABS_MAP['Inondation']
    layer_name = config['symbole'] + " Risque Inondation"
    colors = config['colors']

    fg = folium.FeatureGroup(name=layer_name, show=True)

    try:
        gdf_valid = gdf[gdf.geometry.is_valid].to_crs("EPSG:4326")
        if not gdf_valid.empty:
            folium.GeoJson(
                gdf_valid.to_json(),
                style_function=lambda x: _style_risk(x, colors),
                tooltip=folium.features.GeoJsonTooltip(fields=['NIVEAU_ALEA'], aliases=['Niveau:'])
            ).add_to(fg)
    except Exception as e:
        print(f"ERREUR CRITIQUE RENDU FOLIUM Inondation: {e}")

    fg.add_to(m)


# --- NOUVEAU : FONCTION RISQUE SÉCHERESSE (CRITIQUE A) ---
def _ajouter_couche_risques_rga(m, gdf):
    """
    Ajoute la couche Sécheresse avec le symbole ☀️ forcé dans le nom du calque.
    (Remplace l'ancien appel générique _ajouter_couche_risques).
    """
    if gdf is None or gdf.empty:
        return

    config = RISQUES_ABS_MAP['Sécheresse']
    layer_name = config['symbole'] + " Risque Sécheresse (RGA)"
    colors = config['colors']

    fg = folium.FeatureGroup(name=layer_name, show=True)

    try:
        gdf_valid = gdf[gdf.geometry.is_valid].to_crs("EPSG:4326")
        if not gdf_valid.empty:
            folium.GeoJson(
                gdf_valid.to_json(),
                style_function=lambda x: _style_risk(x, colors),
                tooltip=folium.features.GeoJsonTooltip(fields=['NIVEAU_ALEA'], aliases=['Niveau:'])
            ).add_to(fg)
    except Exception as e:
        print(f"ERREUR CRITIQUE RENDU FOLIUM Sécheresse: {e}")

    fg.add_to(m)


# =================================================================
# CRÉATION CARTE IMPLANTATION (PAGE 02) (Modifiée pour les Risques)
# =================================================================

# Fichier: frontend/maps.py

def creer_carte_implantation(lat_centre, lon_centre, zone_analyse_geom, gdf_poi_trouves,
                             gdf_socio=None, colonne_socio=None, nom_indicateur_socio=None,
                             gdf_batiments=None, gdf_inondations=None, gdf_rga=None,
                             nom_point_central="Cible", adresse_point_central="", analysis_mode='Isochrones',
                             df_dvf=None, dvf_type_filtre="Tous", mode_affichage_dvf="Points",
                             gdf_reseau_cannibale=None):
    """
    Génère la carte d'analyse d'implantation (Page 02).
    Retourne : (objet_carte_folium, objet_legende_socio)
    """
    # 1. MAP INIT
    m = folium.Map(location=[lat_centre, lon_centre], zoom_start=14, tiles="OpenStreetMap")

    # 2. ZONE D'ANALYSE
    if zone_analyse_geom and zone_analyse_geom.geom_type in ['Polygon', 'MultiPolygon']:
        folium.GeoJson(
            zone_analyse_geom,
            style_function=lambda x: {'fillColor': '#A67C00', 'color': '#A67C00', 'weight': 2, 'fillOpacity': 0.1},
            name="Zone d'étude"
        ).add_to(m)

    # 3. DVF (Immobilier)
    if df_dvf is not None and not df_dvf.empty:
        if mode_affichage_dvf == "Heatmap":
            _ajouter_couche_dvf_heatmap(m, df_dvf, dvf_type_filtre)
        else:
            _ajouter_couche_dvf_points(m, df_dvf, dvf_type_filtre)

    # 4. COUCHES CONTEXTUELLES (Socio & Risques)
    # MODIFICATION : On récupère la légende (cmap) mais on NE l'ajoute PAS à la carte (add_to supprimé)
    # Elle sera retournée pour affichage externe.
    cmap, single_val = _ajouter_couche_socio(m, gdf_socio, colonne_socio, nom_indicateur_socio)

    _ajouter_couche_risques_inondation(m, gdf_inondations)
    _ajouter_couche_risques_rga(m, gdf_rga)

    # 5. POINT CENTRAL
    folium.Marker(
        [lat_centre, lon_centre],
        icon=folium.Icon(color='red', icon='crosshairs', prefix='fa'),
        tooltip=nom_point_central,
        popup=adresse_point_central,
        z_index_offset=1000
    ).add_to(m)

    # 6. POI
    if gdf_poi_trouves is not None and not gdf_poi_trouves.empty:
        fg_poi = folium.FeatureGroup(name="POI Zone", show=True)
        for _, r in gdf_poi_trouves.iterrows():
            cat = r.get('categorie', 'Divers')
            icon_config = POI_CONFIG.get(cat, {}).get('icon', {'icon': 'map-marker', 'color': 'gray', 'prefix': 'fa'})

            folium.Marker(
                [r.geometry.y, r.geometry.x],
                icon=folium.Icon(**icon_config),
                tooltip=f"{cat}: {r.get('name', '')}"
            ).add_to(fg_poi)
        fg_poi.add_to(m)

    # 7. BÂTIMENTS (Audit Risque)
    if gdf_batiments is not None and not gdf_batiments.empty:
        fg_bat = folium.FeatureGroup(name="Bâtiments (Audit)", show=True)

        def style_bat(f):
            props = f['properties']
            col = '#3498db' # Bleu par défaut
            if 'ort' in str(props.get('niveau_Inondation', '')): col = '#e74c3c' # Rouge
            elif 'ort' in str(props.get('niveau_Argile', '')): col = '#e67e22' # Orange
            return {'fillColor': col, 'color': col, 'weight': 1, 'fillOpacity': 0.6}

        # On convertit en GeoJson avec Tooltip (Survol) et Popup (Clic)
        folium.GeoJson(
            gdf_batiments.to_json(),
            style_function=style_bat,
            tooltip=folium.features.GeoJsonTooltip(
                fields=['surface_m2', 'niveau_Inondation', 'niveau_Argile'],
                aliases=['Surface (m²):', 'Inondation:', 'Sécheresse:'],
                localize=True
            ),
            popup=folium.GeoJsonPopup(fields=['surface_m2'], aliases=['Surface (m²)'])
        ).add_to(fg_bat)
        fg_bat.add_to(m)

    # 8. CANNIBALISATION
    if gdf_reseau_cannibale is not None and not gdf_reseau_cannibale.empty:
        folium.GeoJson(
            gdf_reseau_cannibale.to_json(),
            style_function=lambda x: {'fillColor': 'red', 'color': 'red', 'weight': 2, 'fillOpacity': 0.3},
            name="Zone de Cannibalisation"
        ).add_to(m)

    Fullscreen().add_to(m)
    folium.LayerControl().add_to(m)

    return m, cmap


# =================================================================
# CRÉATION CARTE CONCURRENCE (PAGE 01) (Modifiée pour Signature & POI)
# =================================================================

# --- CORRECTION D : AJUSTEMENT DE LA SIGNATURE DE RETOUR (4 VALEURS) ---
def creer_carte_concurrence(gdf_points, lat_centre, lon_centre,
                            gdf_socio=None, col_socio=None, lbl_socio=None,
                            gdf_inond=None, gdf_rga=None,
                            mode_affichage='Points', rayon_cercles=1000, temps_isochrones=10,
                            gdf_poi=None):
    m = folium.Map(location=[lat_centre, lon_centre], zoom_start=12, tiles="OpenStreetMap")

    # 1. Couches de fond (Socio, Risques)
    cmap, single_val = _ajouter_couche_socio(m, gdf_socio, col_socio, lbl_socio)

    # --- CORRECTION A : Utilisation des fonctions séparées ---
    _ajouter_couche_risques_inondation(m, gdf_inond)
    _ajouter_couche_risques_rga(m, gdf_rga)

    # --- 2. POINTS D'INTÉRÊT (POI) (CRITIQUE B : Rendu POI restauré) ---
    if gdf_poi is not None and not gdf_poi.empty:
        fg_poi = folium.FeatureGroup(name="📍 POI Locaux", show=True).add_to(m)

        for _, r in gdf_poi.iterrows():
            name = r.get('name', 'POI Inconnu')
            # CRITIQUE B: La colonne 'categorie' DOIT être présente dans gdf_poi (enrichie dans P01)
            cat = r.get('categorie', 'Divers')
            icon_config = POI_CONFIG.get(cat, {}).get('icon', {'icon': 'info-sign', 'color': 'gray', 'prefix': 'fa'})

            folium.Marker(
                [r.geometry.y, r.geometry.x],
                icon=folium.Icon(**icon_config),
                tooltip=f"{cat}: {name}"
            ).add_to(fg_poi)

    # --- 3. POINTS DES CONCURRENTS (Logique conservée) ---
    legend_enseignes = {}
    if not gdf_points.empty:
        fg_points = folium.FeatureGroup(name="Concurrents", show=True).add_to(m)

        colors_pool = ['#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4', '#46f0f0', '#f032e6',
                       '#bcf60c', '#fabebe']
        names = gdf_points['nom_etablissement'].unique()
        legend_enseignes = {n: colors_pool[i % len(colors_pool)] for i, n in enumerate(names)}

        for _, row in gdf_points.iterrows():
            nom = row['nom_etablissement']
            col = legend_enseignes.get(nom, 'gray')

            # Marker
            folium.CircleMarker(
                [row.geometry.y, row.geometry.x], radius=6, color='black', weight=1,
                fill=True, fill_color=col, fill_opacity=1.0,
                tooltip=nom, popup=f"<b>{nom}</b><br>{row.get('adresse_simplifiee', '')}"
            ).add_to(fg_points)

            if mode_affichage == 'Cercles':
                folium.Circle(
                    [row.geometry.y, row.geometry.x], radius=rayon_cercles,
                    color=col, weight=1, fill=True, fill_color=col, fill_opacity=0.1
                ).add_to(fg_points)

            elif mode_affichage == 'Isochrones':
                iso_feature = calculer_isochrone_api(row.geometry.x, row.geometry.y, temps_isochrones * 60)

                if iso_feature:
                    folium.GeoJson(
                        iso_feature,
                        style_function=lambda x, color=col: {'fillColor': color, 'color': color, 'weight': 1,
                                                             'fillOpacity': 0.2},
                        tooltip=f"Isochrone {temps_isochrones} min"
                    ).add_to(fg_points)

    Fullscreen().add_to(m)
    folium.LayerControl().add_to(m)

    stats_socio = {}
    if cmap:
        stats_socio = {'min': cmap.vmin, 'max': cmap.vmax}

    # --- CRITIQUE D: Retour forcé à 4 valeurs pour compatibilité P01 ---
    # La 4ème valeur est conventionnellement la Colormap DVF/Socio ou un dict vide
    return m, legend_enseignes, stats_socio, {}