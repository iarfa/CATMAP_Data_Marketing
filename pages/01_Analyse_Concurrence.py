# Fichier: pages/01_Analyse_Concurrence.py (RÉÉCRITURE INTÉGRALE V4 - FIX LONGITUDE & LÉGENDE SÉLECTIVE)

import streamlit as st
import pandas as pd
import geopandas as gpd
from streamlit_folium import st_folium
import plotly.express as px
import numpy as np

# --- IMPORTS ---
from backend.database import connect_to_db
from backend.data_loaders import (
    charger_communes, charger_donnees_iris_socio, charger_zones_risques
)
from backend.queries_siren import (
    get_concurrents_sql, get_etablissement_par_siret, calculer_stats_anciennete
)
from backend.calculators import preparer_donnees_socio, calculer_comparatif_radar
from frontend.components import (
    sidebar_filtres_socio, render_selection_territoire_compact, sidebar_filtres_poi, sidebar_filtres_risques
)
from frontend.maps import creer_carte_concurrence
from frontend.charts import plot_radar_comparatif
from utils.geo_tools import (
    transfo_geodataframe, rechercher_poi_overpass, extraction_adresse_OSM, executer_recherche_osm_masse,
    extraire_ville_depuis_adresse
)
from config import POI_CONFIG

# =============================================================================
# 1. INITIALISATION
# =============================================================================
st.title("📊 Analyse de la Concurrence")

if 'data_loaded' not in st.session_state:
    with st.status("🚀 Démarrage de GeoRisk...", expanded=True) as status:
        st.write("🔌 Connexion Base de Données...")
        engine = connect_to_db()
        st.session_state['engine'] = engine
        st.write("🗺️ Chargement Référentiel Communes...")
        df_communes = charger_communes()
        st.session_state['df_communes'] = df_communes
        st.write("👥 Chargement Données Socio-Démographiques...")
        raw_iris = charger_donnees_iris_socio()
        st.session_state['dict_geo'] = preparer_donnees_socio(raw_iris, df_communes)
        status.update(label="Chargement terminé !", state="complete", expanded=False)
    st.session_state['data_loaded'] = True

engine = st.session_state.get('engine')
df_communes = st.session_state.get('df_communes')
dict_geo = st.session_state.get('dict_geo')

# =============================================================================
# 2. SIDEBAR
# =============================================================================
with st.sidebar:
    st.header("🎛️ Paramètres de la Carte")

    with st.container(border=True):
        # 1. Socio
        gdf_socio_full, col_socio, lbl_socio, maille_socio = sidebar_filtres_socio(dict_geo)

        st.divider()

        # 2. POI
        poi_selectionnes_sidebar = sidebar_filtres_poi()
        st.divider()

        # 3. Risques (Utilisation de la fonction P01)
        show_risk, type_risk, regions_filtrees, departements_filtres_codes = sidebar_filtres_risques(df_communes)


# =============================================================================
# 3. FONCTIONS DE PRÉPARATION
# =============================================================================
def preparer_calques_carte_optimise(nums_deps_zone, geo_communes_df):
    # 1. Calque Socio (Filtré par Département(s) sélectionné(s))
    socio_layer = None
    if gdf_socio_full is not None and nums_deps_zone:
        socio_layer = gdf_socio_full[gdf_socio_full['CODE_DEPT'].isin(nums_deps_zone)]

    # 2. Calques Risques (Renvoyer les deux couches filtrées)
    inond_layer, rga_layer = gpd.GeoDataFrame(), gpd.GeoDataFrame()

    if show_risk and not geo_communes_df.empty:
        try:
            # --- CORRECTION CRITIQUE 1 : Utilisation des noms de colonnes corrects ---
            temp_gdf = transfo_geodataframe(geo_communes_df, 'Longitude_Centre', 'Latitude_Centre')

            if temp_gdf.empty or temp_gdf.geometry.is_empty.all(): return socio_layer, inond_layer, rga_layer

            minx, miny, maxx, maxy = temp_gdf.unary_union.bounds

            b_minx, b_miny, b_maxx, b_maxy = minx - 0.05, miny - 0.05, maxx + 0.05, maxy + 0.05
            bbox_geo = [b_minx, b_miny, b_maxx, b_maxy]

            with st.spinner("Chargement des risques..."):
                raw_inond = charger_zones_risques("INONDATION")
                raw_rga = charger_zones_risques("RGA")

                # --- 2.1 Filtrage et Simplification Inondation ---
                if not raw_inond.empty:
                    inond_layer = raw_inond.cx[bbox_geo[0]:bbox_geo[2], bbox_geo[1]:bbox_geo[3]].copy()
                    if departements_filtres_codes:
                        if 'Num_Dep' in inond_layer.columns: inond_layer = inond_layer[
                            inond_layer['Num_Dep'].isin(departements_filtres_codes)]
                    inond_layer = inond_layer.dropna(subset=['geometry'])
                    if not inond_layer.empty: inond_layer['geometry'] = inond_layer['geometry'].simplify(0.0001)

                # --- 2.2 Filtrage et Simplification RGA ---
                if not raw_rga.empty:
                    rga_layer = raw_rga.cx[bbox_geo[0]:bbox_geo[2], bbox_geo[1]:bbox_geo[3]].copy()
                    if departements_filtres_codes:
                        if 'Num_Dep' in rga_layer.columns: rga_layer = rga_layer[
                            rga_layer['Num_Dep'].isin(departements_filtres_codes)]
                    rga_layer = rga_layer.dropna(subset=['geometry'])
                    if not rga_layer.empty: rga_layer['geometry'] = rga_layer['geometry'].simplify(0.0001)

        except Exception as e:
            # Afficher l'erreur corrigée pour la trace
            st.error(f"Erreur de filtrage des calques risques: {e}")

    # Renvoyer les deux couches, même si vides
    return socio_layer, inond_layer, rga_layer


def preparer_poi_pour_carte(geo_communes_df, pois_selectionnes):
    gdf_poi = gpd.GeoDataFrame()

    if not pois_selectionnes or geo_communes_df.empty:
        return gdf_poi

    try:
        # --- CORRECTION CRITIQUE 1 : Utilisation des noms de colonnes corrects ---
        temp_gdf = transfo_geodataframe(geo_communes_df, 'Longitude_Centre', 'Latitude_Centre')

        if temp_gdf.empty or temp_gdf.geometry.is_empty.all(): return gdf_poi

        minx, miny, maxx, maxy = temp_gdf.unary_union.bounds
        bbox_agrandie = [minx - 0.005, miny - 0.005, maxx + 0.005, maxy + 0.005]

        tags_a_chercher = {}
        for cat in pois_selectionnes:
            if cat in POI_CONFIG:
                tags_a_chercher.update(POI_CONFIG[cat]['tags'])

        if tags_a_chercher:
            # 1. Recherche via Overpass
            gdf_poi_brut = rechercher_poi_overpass(bbox_agrandie, tags_a_chercher)

            # 2. Enrichissement (Critique B V4) et Filtrage
            if not gdf_poi_brut.empty:

                # --- CORRECTION CRITIQUE 3 : Garantie de la colonne 'categorie' ---
                def assigner_categorie_robuste(row_poi):
                    name = row_poi.get('name', '')

                    # Logique: Trouver la catégorie si un de ses tags correspond (méthode la plus fiable sans accès aux tags bruts OSM)
                    for cat_name, config in POI_CONFIG.items():
                        if cat_name in pois_selectionnes:
                            # S'il y a un match simple dans le nom du POI
                            if cat_name.lower() in name.lower():
                                return cat_name
                            # Plus difficile de matcher par tag ici, on privilégie l'association simple nom/catégorie

                    # Si POI_CONFIG est vide, ça utilise 'Divers'
                    return list(POI_CONFIG.keys())[0] if POI_CONFIG else "Divers"

                gdf_poi_brut['categorie'] = gdf_poi_brut.apply(
                    lambda r: assigner_categorie_robuste({'name': r.get('name')}), axis=1)

                # Le filtrage final doit se faire sur l'union des géométries des communes
                zone_union = temp_gdf.unary_union
                gdf_poi = gdf_poi_brut[gdf_poi_brut.within(zone_union)].copy()

    except Exception as e:
        print(f"Erreur lors de la recherche des POI: {e}")

    return gdf_poi


# =============================================================================
# 4. AFFICHAGE RÉSULTATS
# =============================================================================
def afficher_resultats_persistants(key_data, source_name):
    data = st.session_state[key_data]
    gdf = data['gdf']  # GDF des Concurrents
    nums_deps = data['nums_deps']  # Codes des départements sélectionnés
    age_stats = data.get('age_stats')
    siret_info = st.session_state.get('ref_etab_data', {})
    geo_communes_df = data.get('geo_communes_df', pd.DataFrame())  # GeoDataFrame des communes pour le périmètre

    # --- 1. PRÉPARATION DU GDF POI (Recherche sur la zone d'étude complète) ---
    global poi_selectionnes_sidebar
    gdf_poi = preparer_poi_pour_carte(geo_communes_df, poi_selectionnes_sidebar)

    st.divider()

    # --- KPI ---
    nb = len(gdf)
    # Détermination de la ville de référence
    ville_top = siret_info.get('nom_dep', "N/A")
    if siret_info and siret_info.get('adresse'):
        ville_top = extraire_ville_depuis_adresse(siret_info.get('adresse'))
    elif 'ville' in gdf.columns and not gdf['ville'].dropna().empty:
        ville_top = gdf['ville'].mode()[0]
    elif 'ville_recherche' in gdf.columns:
        ville_top = gdf['ville_recherche'].mode()[0]

    code_dep = nums_deps[0] if nums_deps else "?"

    # KPI ROW
    if age_stats:
        k1, k2, k3, k4 = st.columns(4)
        k4.metric("Ancienneté Moy.", f"{age_stats['age_moyen']} ans", help=f"Médiane : {age_stats['age_median']} ans")
    else:
        k1, k2, k3 = st.columns(3)

    k1.metric("Établissements", nb)
    k2.metric("Zone Principale", f"{ville_top} ({code_dep})")
    k3.metric("Source", source_name)

    st.markdown("---")

    # --- CARTE ---
    c_mode, c_slide, _ = st.columns([2, 2, 3])
    with c_mode:
        mode_aff = st.radio("Affichage", ["Points", "Cercles", "Isochrones"], key=f"mode_{key_data}", horizontal=True,
                            label_visibility="collapsed")
    with c_slide:
        if mode_aff == "Cercles":
            rayon = st.slider("Rayon (m)", 500, 5000, 1000, 100, key=f"rad_{key_data}", label_visibility="collapsed")
        else:
            rayon = 1000
        if mode_aff == "Isochrones":
            temps = st.slider("Temps (min)", 5, 30, 10, 5, key=f"tps_{key_data}", label_visibility="collapsed")
        else:
            temps = 10

    c_map, c_legend = st.columns([3, 1])
    with c_map:
        # Passage des communes sélectionnées pour définir la BBox des risques
        socio, inond, rga = preparer_calques_carte_optimise(nums_deps, geo_communes_df)

        # Sécurité : Si le GDF des concurrents est vide, on prend les coordonnées des communes
        if not gdf.empty:
            lat_c, lon_c = gdf.geometry.y.mean(), gdf.geometry.x.mean()
        elif not geo_communes_df.empty:
            lat_c, lon_c = geo_communes_df['Latitude_Centre'].mean(), geo_communes_df['Longitude_Centre'].mean()
        else:
            lat_c, lon_c = 46.603354, 1.888334  # Centre France par défaut

        # --- CRITIQUE A & B : Appel de la carte corrigée avec les deux calques de risque et les POI enrichis ---
        # Déballage à 4 valeurs pour être compatible maps.py (Critique D V1)
        m, leg_ens, stats_socio, _ = creer_carte_concurrence(
            gdf_points=gdf, lat_centre=lat_c, lon_centre=lon_c,
            gdf_socio=socio, col_socio=col_socio, lbl_socio=lbl_socio,
            # Les deux couches sont passées pour garantir les calques distincts et les symboles
            gdf_inond=inond, gdf_rga=rga,
            mode_affichage=mode_aff, rayon_cercles=rayon, temps_isochrones=temps,
            gdf_poi=gdf_poi  # GDF POI enrichi avec 'categorie' et filtré sur la zone complète
        )
        # st_folium est sécurisé par returned_objects=[] (fix C V1)
        st_folium(m, height=550, use_container_width=True, returned_objects=[])

    with c_legend:
        st.markdown("#### Légende")
        with st.container(border=True):
            st.caption("📍 Enseignes")
            if leg_ens:
                items = list(leg_ens.items())
                for nom, color in items[:10]:
                    st.markdown(f'<span style="color:{color};">●</span> {nom}', unsafe_allow_html=True)
                if len(items) > 10: st.caption(f"... +{len(items) - 10} autres")
            else:
                st.caption("Aucune")

            # Légende Socio
            if stats_socio and lbl_socio:
                st.divider()
                st.caption(f"📊 {lbl_socio}")
                st.markdown(
                    '<div style="background: linear-gradient(to right, #ffffcc, #fd8d3c, #800026); width: 100%; height: 10px; border-radius: 5px;"></div>',
                    unsafe_allow_html=True)
                if stats_socio.get('max'): st.caption(
                    f"Min: {stats_socio['min']:,.0f} | Max: {stats_socio['max']:,.0f}")

            # Légende Risques (CRITIQUE 2 : Rétablissement de la légende sélective)
            if show_risk:
                st.divider()
                # On affiche SEULEMENT le risque sélectionné
                if "Inondation" in type_risk and not inond.empty:
                    st.caption(f"🌊 Risque Inondation")
                    symb = "🌊"
                elif "Sécheresse" in type_risk and not rga.empty:
                    st.caption(f"☀️ Risque Sécheresse")
                    symb = "☀️"
                else:
                    st.caption("🌪️ Risques (Non affichés)")
                    symb = ""

                if symb:
                    # Affichage des légendes des niveaux
                    st.markdown(
                        """
                        <div style="font-size:13px; line-height:1.5;">
                            <span style="color:#e74c3c;">■</span> Aléa Fort<br>
                            <span style="color:#e67e22;">■</span> Aléa Moyen<br>
                            <span style="color:#95a5a6;">■</span> Aléa Faible
                        </div>
                        """,
                        unsafe_allow_html=True)

    st.info("ℹ️ **Note :** Les données de revenus peuvent être masquées par l'INSEE dans les zones peu denses.")

    st.divider()

    # =========================================================
    # LOGIQUE DISTINCTE : OSM vs SIREN
    # =========================================================

    # CAS 1 : OPENSTREETMAP (Analyse Zone / Radar)
    if source_name == "OpenStreetMap":
        t_rad, t_list = st.tabs(["🧬 Profil Zone (Radar)", "📋 Liste"])

        with t_rad:
            with st.container(border=True):
                st.markdown("#### ⚙️ Paramètres d'analyse")
                c_p1, _ = st.columns([3, 1])
                with c_p1:
                    rayon_ana = st.slider("Rayon d'analyse (km)", 1, 10, 3, key=f"rad_{key_data}_ana")

                st.markdown("**Profils Rapides :**")
                b1, b2, b3 = st.columns(3)

                if b1.button("💎 CSP+", key=f"btn_csp_{key_data}", use_container_width=True):
                    st.session_state[f"met_{key_data}"] = ["Cadres", "Seniors", "Retraités"]
                    st.rerun()

                if b2.button("👨‍👩‍👧 Familles", key=f"btn_fam_{key_data}", use_container_width=True):
                    st.session_state[f"met_{key_data}"] = ["Familles", "Jeunes", "Actifs", "Monoparental"]
                    st.rerun()

                if b3.button("🏭 Populaire", key=f"btn_pop_{key_data}", use_container_width=True):
                    st.session_state[f"met_{key_data}"] = ["Ouvriers", "Familles", "Jeunes"]
                    st.rerun()

                # Init
                if f"met_{key_data}" not in st.session_state:
                    st.session_state[f"met_{key_data}"] = ["Jeunes", "Cadres", "Ouvriers", "Familles",
                                                           "Actifs"]  # Sans revenu par défaut

                metrics = st.multiselect(
                    "Indicateurs :",
                    ["Revenus", "Jeunes", "Actifs", "Seniors", "Cadres", "Ouvriers", "Familles", "Retraités",
                     ],
                    key=f"met_{key_data}"
                )

        if not gdf.empty:
            # 1. Calcul de la zone (Buffer autour des points)
            zone_proj = gdf.to_crs("EPSG:2154").buffer(rayon_ana * 1000).unary_union

            if not zone_proj.is_empty:
                # 2. Conversion géométrique
                geom_finale = gpd.GeoSeries([zone_proj], crs="EPSG:2154").to_crs("EPSG:4326").iloc[0]

                # 3. Calcul Backend
                stats, nom_ref = calculer_comparatif_radar(dict_geo['IRIS'], geom_finale, metrics, df_communes)

                # 4. Affichage
                if stats is not None:
                    st.divider()
                    c_radar, c_top3 = st.columns([2, 1])

                    # A. Radar
                    with c_radar:
                        st.markdown("#### Profil Clientèle (Base 100)")
                        fig = plot_radar_comparatif(stats, nom_ref)
                        st.plotly_chart(fig, use_container_width=True)

                    # B. Top 3 Écarts
                    with c_top3:
                        st.markdown("#### 💡 Top Écarts")
                        if 'Indice_100' in stats.columns:
                            stats['d'] = (stats['Indice_100'] - 100).abs()
                            for _, r in stats.sort_values('d', ascending=False).head(3).iterrows():
                                ic = "📈" if r['Indice_100'] > 100 else "📉"
                                # Gestion unité €/%
                                unit = "€" if "Revenu" in r['Metrique'] else "%"
                                val_aff = f"{r['Zone']:,.0f}".replace(",", " ") + unit

                                st.metric(
                                    f"{ic} {r['Metrique']}",
                                    val_aff,
                                    f"{r['Indice_100'] - 100:+.0f} pts",
                                    delta_color="normal"
                                )

        with t_list:
            # Sécurisation des colonnes : on ne demande que ce qui existe vraiment
            cols_souhaitees = ['nom_etablissement', 'adresse_simplifiee', 'ville', 'ville_recherche',
                               'datecreationetablissement']
            cols_reelles = [c for c in cols_souhaitees if c in gdf.columns]
            st.dataframe(gdf[cols_reelles], use_container_width=True)

    # CAS 2 : SIREN (Analyse Concurrentielle / Pression / Age)
    else:
        t_press, t_age, t_list = st.tabs(["🎯 Pression & Proximité", "⏳ Ancienneté", "📋 Liste"])

        with t_press:
            st.subheader("Analyse de Proximité")
            if siret_info and 'latitude' in siret_info:

                mode_calc = st.radio("Métrie :", ["Distance (km)", "Temps (min, estimé)"], horizontal=True,
                                     key=f"metrie_{key_data}")

                gdf_calc = gdf.copy().to_crs("EPSG:2154")
                ref_point = gpd.GeoSeries([gpd.points_from_xy([siret_info['longitude']], [siret_info['latitude']])[0]],
                                          crs="EPSG:4326").to_crs("EPSG:2154").iloc[0]
                gdf_calc['dist_m'] = gdf_calc.distance(ref_point)

                val_col, seuil_proche, seuil_loin, suffix = 'dist_m', 1000, 5000, "m"

                if "Temps" in mode_calc:
                    gdf_calc['temps_min'] = gdf_calc['dist_m'] * 0.002  # estim 30km/h
                    val_col, seuil_proche, seuil_loin, suffix = 'temps_min', 3, 10, " min"
                    gdf_calc['val_aff'] = gdf_calc['temps_min'].round(1)
                else:
                    gdf_calc['val_aff'] = (gdf_calc['dist_m'] / 1000).round(2)
                    suffix = " km"

                # Catégorisation avec numérotation pour forcer l'ordre de tri si besoin,
                # mais ici on utilise category_orders de Plotly
                def segmenter(v):
                    if v < seuil_proche:
                        return "🔴 Frontale"
                    elif v < seuil_loin:
                        return "🟠 Zone Chalandise"
                    return "🟢 Eloignée"

                gdf_calc['Catégorie'] = gdf_calc[val_col].apply(segmenter)

                # Explications contextuelles
                st.info(
                    f"""
                    **Légende des zones :**
                    - **🔴 Frontale** (< {seuil_proche}{suffix}) : Menace immédiate, captation de flux piéton.
                    - **🟠 Zone Chalandise** ({seuil_proche}-{seuil_loin}{suffix}) : Concurrence standard voiture/transport.
                    - **🟢 Eloignée** (> {seuil_loin}{suffix}) : Faible impact quotidien.
                    """
                )

                c_g, c_k = st.columns([2, 1])
                with c_g:
                    # Ordre imposé : Frontale -> Chalandise -> Eloignée
                    ordre_cat = ["🟢 Eloignée", "🟠 Zone Chalandise", "🔴 Frontale"]

                    fig_bar = px.bar(
                        gdf_calc['Catégorie'].value_counts().reset_index(),
                        x='count', y='Catégorie',  # Orientation Horizontale pour lisibilité
                        orientation='h',
                        title="Répartition de la Menace",
                        color='Catégorie',
                        color_discrete_map={"🔴 Frontale": "#d62728", "🟠 Zone Chalandise": "#ff7f0e",
                                            "🟢 Eloignée": "#2ca02c"},
                        category_orders={"Catégorie": ordre_cat}  # Force l'ordre
                    )
                    fig_bar.update_layout(yaxis_title=None, xaxis_title="Nombre d'établissements")
                    st.plotly_chart(fig_bar, use_container_width=True)

                with c_k:
                    closest = gdf_calc.loc[gdf_calc['dist_m'].idxmin()]
                    st.metric("Concurrent le + proche", f"{closest['val_aff']}{suffix}",
                              f"{closest['nom_etablissement']}")
                    st.caption(f"📍 {closest['adresse_simplifiee']}")

            else:
                st.info("⚠️ Analyse de proximité disponible uniquement avec un SIRET de référence.")

        with t_age:
            if source_name == "Base SIRENE (NAF)" and 'datecreationetablissement' in gdf.columns:
                st.subheader("Distribution des Âges")
                try:
                    df_age = gdf.copy()
                    df_age['date_creation'] = pd.to_datetime(df_age['datecreationetablissement'], errors='coerce')
                    # Calcul age en années
                    df_age['Ancienneté'] = ((pd.Timestamp.now() - df_age['date_creation']).dt.days / 365.25)
                    # On ne garde que les âges valides
                    df_age = df_age[df_age['Ancienneté'] >= 0].sort_values('Ancienneté', ascending=False)

                    # Calculs statistiques du marché
                    moy_age = df_age['Ancienneté'].mean()
                    min_age = df_age['Ancienneté'].min()
                    max_age = df_age['Ancienneté'].max()

                    age_ref = 0
                    if siret_info and siret_info.get('datecreationetablissement'):
                        d_ref = pd.to_datetime(siret_info['datecreationetablissement'])
                        age_ref = (pd.Timestamp.now() - d_ref).days / 365.25

                    # --- BLOC INSIGHT AMÉLIORÉ ---
                    if age_ref > 0:
                        # Ranking : Combien sont plus vieux strictement ?
                        plus_vieux = df_age[df_age['Ancienneté'] > age_ref].shape[0]
                        total = len(df_age)
                        rang = plus_vieux + 1

                        # Choix de la couleur et du message
                        if rang == 1:
                            msg_titre = f"🏆 Vous êtes le doyen (1er/{total}) !"

                        elif rang <= total * 0.25:  # Top 25%
                            msg_titre = f"✅ Top Tier : {rang}ème plus ancien sur {total}."

                        elif rang > total * 0.75:  # Derniers 25%
                            msg_titre = f"👶 Nouvel entrant : {rang}ème sur {total}."

                        else:
                            msg_titre = f"📊 Position médiane : {rang}ème sur {total}."

                        # Affichage sous forme de "Carte d'identité"
                        st.markdown(f"""
                        <div style="padding: 15px; border-radius: 5px; background-color: #f0f2f6; border-left: 5px solid #ff4b4b;">
                            <h4 style="margin-top:0;">{msg_titre}</h4>
                            <p style="font-size:15px;">
                                Avec <b>{age_ref:.1f} années</b> d'existence, vous vous situez par rapport au marché :
                            </p>
                            <ul style="margin-bottom:0;">
                                <li>📉 <b>Le plus récent :</b> {min_age:.1f} ans</li>
                                <li>⚖️ <b>Moyenne zone :</b> {moy_age:.1f} ans</li>
                                <li>👴 <b>Le plus ancien :</b> {max_age:.1f} ans</li>
                            </ul>
                        </div>
                        <br>
                        """, unsafe_allow_html=True)

                    # Histogramme Plotly
                    fig_hist = px.histogram(
                        df_age, x="Ancienneté", nbins=20,
                        title="Pyramide des âges",
                        color_discrete_sequence=['#B8860B'],
                        labels={'Ancienneté': "Années d'existence", "count": "Nombre d'établissements"}
                    )
                    if age_ref > 0:
                        fig_hist.add_vline(x=age_ref, line_width=3, line_dash="dash", line_color="red")
                        fig_hist.add_annotation(x=age_ref, y=0, text="Vous", showarrow=True, arrowhead=1,
                                                yanchor="bottom")

                    st.plotly_chart(fig_hist, use_container_width=True)

                except Exception as e:
                    st.error(f"Erreur calcul ancienneté : {e}")
            else:
                st.info("Données d'ancienneté non disponibles pour cette source.")

        with t_list:
            # Sécurisation : On ne sélectionne que les colonnes qui existent vraiment
            cols_ideales = ['nom_etablissement', 'adresse_simplifiee', 'ville', 'ville_recherche',
                            'datecreationetablissement']
            cols_reelles = [c for c in cols_ideales if c in gdf.columns]

            st.dataframe(
                gdf[cols_reelles],
                use_container_width=True,
                column_config={
                    "datecreationetablissement": st.column_config.DateColumn("Date Création", format="DD/MM/YYYY"),
                    "ville": "Ville",
                    "ville_recherche": "Ville"
                }
            )


# =============================================================================
# 5. RECHERCHE (Mise à jour pour stocker geo_communes_df)
# =============================================================================
tab_osm, tab_siren = st.tabs(["🔍 Par Enseigne (OSM)", "🏢 Par Etablissement (SIRET)"])

with tab_osm:
    with st.container(border=True):
        c1, c2 = st.columns([1, 1.5])
        with c1:
            st.text_input("Enseignes :", "Lidl", key="txt_osm")
        with c2:
            geo = render_selection_territoire_compact(df_communes,
                                                      "osm")  # geo['data_communes'] contient les centres des communes
        if st.button("Lancer", key="btn_osm", type="primary"):
            if geo["data_communes"].empty:
                st.error("Sélectionnez une zone.")
            else:
                with st.spinner("Recherche..."):
                    res = executer_recherche_osm_masse([x.strip() for x in st.session_state.txt_osm.split(',')],
                                                       geo["data_communes"])
                    if not res.empty:
                        res[['adresse_simplifiee', '_']] = res.apply(extraction_adresse_OSM, axis=1)
                        # --- MODIFICATION CRITIQUE : AJOUT DE LA ZONE GÉOGRAPHIQUE ---
                        st.session_state['res_osm'] = {'gdf': transfo_geodataframe(res, 'longitude', 'latitude'),
                                                       'nums_deps': geo["nums_deps"],
                                                       'geo_communes_df': geo["data_communes"],
                                                       'age_stats': None}
                        if 'ref_etab_data' in st.session_state: del st.session_state['ref_etab_data']
                    else:
                        st.warning("Rien trouvé.")
    if 'res_osm' in st.session_state: afficher_resultats_persistants('res_osm', "OpenStreetMap")

with tab_siren:
    with st.container(border=True):
        st.info("Ciblage par SIRET de référence (Détection automatique NAF + Zone)")
        c1, c2 = st.columns([3, 1])
        with c1:
            siret = st.text_input("SIRET (14 chiffres) :", key="siret_in")
        with c2:
            st.write("");
            st.write("")
            load = st.button("Charger", key="btn_load")

        if load and len(siret) == 14:
            inf = get_etablissement_par_siret(engine, siret)
            if inf:
                st.session_state['ref_etab_data'] = inf
                st.success(f"Trouvé : {inf.get('denominationunitelegale')}")
            else:
                st.error("Inconnu.")

        if 'ref_etab_data' in st.session_state:
            inf = st.session_state['ref_etab_data']
            naf, dep = inf.get('activiteprincipaleetablissement'), inf.get('numero_dep')
            ville = extraire_ville_depuis_adresse(inf.get('adresse'))

            reg_txt = ""
            # On cherche la région pour l'affichage
            df_deps_filtered = df_communes[df_communes['Num_Dep'] == str(dep)]
            if not df_deps_filtered.empty:
                reg_txt = f" - {df_deps_filtered.iloc[0]['Nom_Region']}"

            # Créer la liste des communes dans le département pour la recherche (si besoin)
            communes_du_dep = df_communes[df_communes['Num_Dep'] == str(dep)]

            st.markdown("---")
            c_i, c_s = st.columns([1, 1.5])
            with c_i:
                st.caption("Cible")
                st.markdown(f"**NAF {naf}**\n\n{ville} ({dep})")
            with c_s:
                st.caption("Périmètre")
                scope = st.radio("Zone :", [f"Ville ({ville})", f"Dépt ({dep})", f"Région ({reg_txt.strip(' - ')})"],
                                 key="scope_rad")

            if st.button("🚀 Analyser", type="primary", use_container_width=True):
                z_type = "Ville" if "Ville" in scope else "Département" if "Dépt" in scope else "Région"
                with st.spinner("Analyse..."):
                    df = get_concurrents_sql(engine, naf, dep, siret)
                    stats = calculer_stats_anciennete(engine, naf, z_type, dep, ville)

                    if not df.empty:
                        if z_type == "Ville":
                            df['v'] = df['adresse'].apply(extraire_ville_depuis_adresse)
                            df = df[df['v'] == ville.upper()]

                        # Déterminer les communes pour la zone d'étude (si SIREN)
                        if z_type == "Ville":
                            # Ne garder que la ligne de commune de la ville cible
                            geo_df_cible = df_communes[(df_communes['Nom_Ville'].str.upper() == ville.upper()) & (
                                        df_communes['Num_Dep'] == str(dep))]
                        else:
                            # Garder toutes les communes du département
                            geo_df_cible = communes_du_dep

                        if not df.empty:
                            gdf = transfo_geodataframe(df, 'longitude', 'latitude')
                            gdf['nom_etablissement'] = gdf['denominationunitelegale']
                            gdf['adresse_simplifiee'] = gdf['adresse']
                            gdf['ville'] = df['adresse'].apply(extraire_ville_depuis_adresse)

                            # --- MODIFICATION CRITIQUE : AJOUT DE LA ZONE GÉOGRAPHIQUE ---
                            st.session_state['res_siren'] = {'gdf': gdf, 'nums_deps': [dep],
                                                             'geo_communes_df': geo_df_cible,
                                                             'age_stats': stats}
                        else:
                            st.warning("Aucun concurrent sur la ville.")
                    else:
                        st.warning("Aucun concurrent sur le département.")

    if 'res_siren' in st.session_state: afficher_resultats_persistants('res_siren', "Base SIRENE (NAF)")