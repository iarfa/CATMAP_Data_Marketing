# Fichier: pages/01_Analyse_Concurrence.py

import streamlit as st
import geopandas as gpd
import pandas as pd
from streamlit_folium import st_folium
import plotly.graph_objects as go
import time

# Imports des modules métiers
from fonctions_basiques import (
    charger_communes, extraction_adresse_OSM, choix_centre_OSM,
    charger_donnees_iris_socio, charger_coefficients_trafic, preparer_donnees_socio,
    charger_zones_inondables, charger_donnees_rga,
    connect_to_db,
    calculer_stats_anciennete,
    calculer_comparatif_radar
)
from fonctions_cartographie import (
    transfo_geodataframe, creer_carte_enrichie, rechercher_poi_osm
)
from interface import (
    interface_recherche_osm, interface_selection_socio,
    interface_selection_poi, POI_CONFIG,
    interface_selection_risques,
    interface_recherche_concurrence
)

# =============================================================================
# CONFIGURATION & CHEMINS
# =============================================================================

PATH_COMMUNES = "data/Communes_France_Metro.xlsx"
PATH_IRIS_SOCIO = "data/iris_socio_data_final.parquet"
PATH_COEFF_TRAFIC = "data/coefficient_temps_trajet.xlsx"
PATH_ZONES_INONDABLES = "data/zones_inondables_v2.parquet"
PATH_RGA_SECHERESSE = "data/rga_secheresse_v2.parquet"


# =============================================================================
# HELPERS LOCAUX
# =============================================================================

def _preparer_et_filtrer_gdf_risque(gdf_source, nom_risque, risque_selectionne, regions_filtrees, departements_filtres):
    """Filtre un GeoDataFrame de risque en fonction de la sélection de l'utilisateur."""
    if risque_selectionne != nom_risque or gdf_source.empty:
        return gpd.GeoDataFrame()

    # Création colonne de filtre compatible
    if 'NOM_DEP' in gdf_source.columns and 'Num_Dep' in gdf_source.columns:
        gdf_source['affichage_dep'] = gdf_source['Num_Dep'] + " - " + gdf_source['NOM_DEP'].str.upper()

    # Application des filtres
    if regions_filtrees:
        if 'NOM_REG' in gdf_source.columns:
            return gdf_source[gdf_source['NOM_REG'].isin(regions_filtrees)]
    elif departements_filtres:
        if 'affichage_dep' in gdf_source.columns:
            return gdf_source[gdf_source['affichage_dep'].isin(departements_filtres)]

    return gdf_source


def _afficher_resultats_concurrence(gdf_resultats, source_name, df_coefficients, gdf_socio_filtre, indicateur,
                                    nom_indicateur, poi_selectionnes_sidebar, gdf_inondations, gdf_rga, ref_lat=None,
                                    ref_lon=None, ref_nom=None,
                                    engine=None, code_naf=None, scope=None, scope_value=None, ville_ref=None,
                                    df_communes=None):  # Ajout df_communes
    """
    Fonction principale d'affichage : KPIs -> Carte -> Radar.
    """
    st.markdown("---")

    # --- 1. BLOC KPIs ---
    nb_etablissements = len(gdf_resultats)

    # Détection intelligente de la zone principale pour l'affichage
    zone_info = "Zone Large"
    if 'ville' in gdf_resultats.columns:
        top_ville = gdf_resultats['ville'].mode()
        if not top_ville.empty: zone_info = top_ville[0]
    elif 'nom_dep' in gdf_resultats.columns:
        top_dep = gdf_resultats['nom_dep'].mode()
        if not top_dep.empty: zone_info = top_dep[0]

    # Info Source
    valeur_source = "N/A"
    full_list_tooltip = ""
    label_source = "Critère"

    if not gdf_resultats.empty:
        if source_name == "OSM":
            label_source = "Enseigne(s)"
            enseignes_uniques = gdf_resultats['nom_etablissement'].unique()
            nb_enseignes = len(enseignes_uniques)
            full_list_tooltip = ", ".join(enseignes_uniques)
            valeur_source = enseignes_uniques[
                0] if nb_enseignes == 1 else f"{enseignes_uniques[0]} (+{nb_enseignes - 1})"
        else:  # SIREN
            label_source = "Code NAF"
            valeur_source = gdf_resultats.iloc[0]['activiteprincipaleetablissement']
            full_list_tooltip = f"Code activité : {valeur_source}"

    # Calcul Ancienneté (Uniquement mode SIREN)
    age_moyen_display = None
    age_help = ""
    if source_name == "SIREN" and engine and code_naf:
        stats_age = calculer_stats_anciennete(engine, code_naf, scope, scope_value, ville_ref)
        if stats_age:
            age_moyen_display = f"{stats_age['age_moyen']} ans"
            age_help = (f"Moyenne : {stats_age['age_moyen']} ans\n"
                        f"Médiane : {stats_age['age_median']} ans\n"
                        f"Plus vieux : {stats_age['plus_vieux']} ans")

    # Affichage Colonnes KPI
    if age_moyen_display:
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    else:
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi4 = None

    with kpi1:
        st.metric(label="Établissements", value=f"{nb_etablissements}")
    with kpi2:
        st.metric(label="Zone Principale", value=zone_info)
    with kpi3:
        st.metric(label=label_source, value=valeur_source, help=full_list_tooltip)
    if kpi4 and age_moyen_display:
        with kpi4: st.metric(label="Ancienneté Moy.", value=age_moyen_display, help=age_help)

    st.markdown("---")

    # --- 2. CARTE INTERACTIVE ---
    col_map_ctrl, col_map_visu = st.columns([1, 3])

    with col_map_ctrl:
        st.subheader(f"Carte ({source_name})")

        mode_affichage = st.radio(
            "Mode d'affichage :",
            ('Points', 'Cercles', 'Isochrones'),
            key=f"mode_aff_{source_name}"
        )
        rayon_cercles, temps_isochrones = 1000, 10
        if mode_affichage == 'Cercles':
            rayon_cercles = st.slider("Rayon (m) :", 100, 5000, 1000, 100, key=f"ray_{source_name}")
        elif mode_affichage == 'Isochrones':
            temps_isochrones = st.slider("Temps (min) :", 2, 20, 10, 1, key=f"tps_{source_name}")

    # Centrage Carte
    if ref_lat and ref_lon:
        lat_centre, lon_centre = ref_lat, ref_lon
    else:
        lat_centre, lon_centre = choix_centre_OSM(gdf_resultats)

    # Récupération POI (Si demandés dans Sidebar)
    gdf_poi_final = gpd.GeoDataFrame()
    if poi_selectionnes_sidebar:
        bounds = gdf_resultats.total_bounds
        # Si un seul point ou très proche, on force une bbox minimale
        if len(gdf_resultats) < 2 and lat_centre:
            bounds = [lon_centre - 0.05, lat_centre - 0.05, lon_centre + 0.05, lat_centre + 0.05]

        marge = 0.05
        bbox_poi = (bounds[0] - marge, bounds[1] - marge, bounds[2] + marge, bounds[3] + marge)

        with st.spinner(f"Chargement POI..."):
            liste_gdf_poi = [rechercher_poi_osm(bbox_poi, POI_CONFIG[cat]['tags']).assign(categorie=cat) for cat in
                             poi_selectionnes_sidebar]
            liste_gdf_poi_non_vides = [gdf for gdf in liste_gdf_poi if not gdf.empty]
            if liste_gdf_poi_non_vides:
                gdf_poi_final = pd.concat(liste_gdf_poi_non_vides, ignore_index=True)

    with col_map_visu:
        map_object, legend_enseignes, legend_socio_color, legend_socio_single = creer_carte_enrichie(
            gdf_etablissements=gdf_resultats,
            lat_centre=lat_centre, lon_centre=lon_centre,
            gdf_socio=gdf_socio_filtre, colonne_socio=indicateur, nom_indicateur_socio=nom_indicateur,
            gdf_poi=gdf_poi_final, gdf_inondations=gdf_inondations, gdf_rga=gdf_rga,
            mode_affichage_etablissements=mode_affichage if mode_affichage != 'Cercles' else 'Cercles d\'influence',
            rayon_cercles=rayon_cercles, temps_isochrones=temps_isochrones,
            df_coefficients=df_coefficients, ref_lat=ref_lat, ref_lon=ref_lon, ref_nom=ref_nom
        )
        st_folium(map_object, width=None, height=500, returned_objects=[], key=f"map_{source_name}")

        if legend_enseignes:
            with st.expander("Voir la légende détaillée"):
                for nom, color in legend_enseignes.items():
                    st.markdown(f'<span style="color:{color};">●</span> {nom}', unsafe_allow_html=True)

    # =========================================================
    # 3. RADAR & PROFIL TYPE (NOUVEAU LAYOUT + COMPARATIF)
    # =========================================================
    if not gdf_resultats.empty and 'dict_geodatas' in st.session_state:
        st.markdown("---")
        st.subheader("🧬 Profil Type de la Clientèle Ciblée")

        # --- ETAPE A : PARAMÈTRES (HAUT, PLEINE LARGEUR) ---
        with st.container(border=True):
            col_titre_param, col_slider_param, col_comp_param = st.columns([1, 2, 1])

            with col_titre_param:
                st.write("**Paramètres d'analyse**")
                st.caption(f"Calculé sur les {len(gdf_resultats)} points.")

            with col_slider_param:
                # Le slider est persistant grâce au st.session_state géré dans interface.py
                rayon_km = st.slider("Rayon d'analyse (km)", 1, 20, 3, key=f"slider_radar_{source_name}")

            # NOUVEAU : Sélecteur de Comparaison
            with col_comp_param:
                niveau_comp = st.selectbox(
                    "Comparer à :",
                    ["Département", "Région", "France"],
                    key=f"sel_comp_concurrence_{source_name}"
                )

        try:
            # 1. Calcul Zone (Union des buffers)
            gdf_buffers = gdf_resultats.to_crs("EPSG:2154").buffer(rayon_km * 1000)
            zone_globale_concurrents = gdf_buffers.unary_union
            zone_analyse_geom = \
            gpd.GeoDataFrame(geometry=[zone_globale_concurrents], crs="EPSG:2154").to_crs("EPSG:4326").geometry.iloc[0]

            # 2. Calcul Indicateurs (Avec nouveau param niveau_comp)
            metriques_concurrence = ["Revenus", "Jeunes", "Actifs", "Seniors", "Retraités", "Cadres", "Ouvriers"]

            # Important: Passer df_communes pour le mapping Région
            df_radar, nom_ref = calculer_comparatif_radar(
                st.session_state['dict_geodatas']['IRIS'],
                zone_analyse_geom,
                metriques_demandees=metriques_concurrence,
                df_communes_ref=df_communes,  # Nécessaire pour Région
                niveau_comparaison=niveau_comp  # Dept/Region/France
            )

            if df_radar is not None and not df_radar.empty:

                # --- ETAPE B : CONTENU (2 COLONNES) ---
                col_radar, col_kpis = st.columns([1.5, 1])

                # --- B1. GAUCHE : GRAPHIQUE RADAR ---
                with col_radar:
                    fig = go.Figure()

                    # Trace Ref (Moyenne du Dept/Region/France)
                    fig.add_trace(go.Scatterpolar(
                        r=[100] * len(df_radar), theta=df_radar['Metrique'],
                        fill=None, name=f"Ref ({nom_ref})",  # Nom Dynamique
                        line_color='gray', line_dash='dot', hoverinfo='skip'
                    ))
                    # Trace Zone
                    fig.add_trace(go.Scatterpolar(
                        r=df_radar['Indice_100'], theta=df_radar['Metrique'],
                        fill='toself', name=f'Zone ({rayon_km}km)',
                        line_color='#E63946'
                    ))

                    fig.update_layout(
                        polar=dict(
                            radialaxis=dict(visible=True, range=[0, max(140, df_radar['Indice_100'].max() + 10)])),
                        showlegend=True,
                        height=400,
                        margin=dict(t=20, b=20, l=40, r=40),
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        legend=dict(orientation="h", yanchor="bottom", y=-0.1, xanchor="center", x=0.5)
                    )
                    st.plotly_chart(fig, use_container_width=True)

                # --- B2. DROITE : TOP 3 ÉCARTS ---
                with col_kpis:
                    st.markdown("#### 💡 Spécificités")
                    st.caption(f"Top 3 écarts vs {nom_ref}")

                    # Tri par écart absolu
                    df_radar['delta'] = df_radar['Indice_100'] - 100
                    df_radar['delta_abs'] = df_radar['delta'].abs()
                    top_3 = df_radar.sort_values('delta_abs', ascending=False).head(3)

                    for _, row in top_3.iterrows():
                        delta = row['delta']
                        label = row['Metrique']
                        val = row['Zone']
                        txt_val = f"{val:,.0f} €" if "Revenu" in label else f"{val:.1f}%"

                        if delta > 0:
                            st.metric(label=f"{label}", value=txt_val, delta=f"+{delta:.0f} pts", delta_color="normal")
                        else:
                            st.metric(label=f"{label}", value=txt_val, delta=f"{delta:.0f} pts", delta_color="normal")

            else:
                st.warning(f"Pas assez de données IRIS dans un rayon de {rayon_km}km.")

        except Exception as e:
            st.error(f"Erreur Radar : {e}")


# =============================================================================
# MAIN EXECUTION
# =============================================================================

st.title("📊 Analyse de la Concurrence")
engine = connect_to_db()

with st.spinner("Chargement des référentiels..."):
    df_communes = charger_communes(PATH_COMMUNES)
    gdf_inondations = charger_zones_inondables(PATH_ZONES_INONDABLES)
    gdf_rga = charger_donnees_rga(PATH_RGA_SECHERESSE)
    df_iris_base = charger_donnees_iris_socio(PATH_IRIS_SOCIO)
    df_coefficients = charger_coefficients_trafic(PATH_COEFF_TRAFIC)

# Init Session
if 'dict_geodatas' not in st.session_state:
    st.session_state['dict_geodatas'] = preparer_donnees_socio(df_iris_base, df_communes)
dict_geodatas = st.session_state['dict_geodatas']

# --- SIDEBAR (FILTRES HARMONISÉS) ---
with st.sidebar:
    st.header("🎛️ Calques & Filtres")

    # 1. Socio
    gdf_socio_filtre, indicateur, nom_indicateur, maille = interface_selection_socio(dict_geodatas)
    st.divider()

    # 2. POI
    poi_selectionnes_sidebar = interface_selection_poi()
    st.divider()

    # 3. Risques
    risque_selectionne, regions_filtrees, departements_filtres = interface_selection_risques(df_communes)

# --- PRÉPARATION CALQUES ---
gdf_inondations_a_afficher = _preparer_et_filtrer_gdf_risque(
    gdf_inondations, "Inondations", risque_selectionne, regions_filtrees, departements_filtres
)
gdf_rga_a_afficher = _preparer_et_filtrer_gdf_risque(
    gdf_rga, "Sécheresse (RGA)", risque_selectionne, regions_filtrees, departements_filtres
)

# --- ONGLETS PRINCIPAUX ---
subtab_osm, subtab_siren = st.tabs(["🔍 Par Enseigne (OSM)", "🏢 Par Activité (SIREN)"])

with subtab_osm:
    st.info("Rechercher des enseignes par leur nom (ex: 'Lidl', 'Carrefour') via OpenStreetMap.")
    # Interface persistant avec Session State
    df_etablissements_osm = interface_recherche_osm(df_communes, key_prefix="concurrence_osm")

    if not df_etablissements_osm.empty:
        df_etablissements_osm[["adresse_simplifiee", "precision_geocodage"]] = df_etablissements_osm.apply(
            extraction_adresse_OSM, axis=1)
        gdf_osm_final = transfo_geodataframe(df_etablissements_osm, "longitude", "latitude")

        _afficher_resultats_concurrence(
            gdf_resultats=gdf_osm_final, source_name="OSM", df_coefficients=df_coefficients,
            gdf_socio_filtre=gdf_socio_filtre, indicateur=indicateur, nom_indicateur=nom_indicateur,
            poi_selectionnes_sidebar=poi_selectionnes_sidebar,
            gdf_inondations=gdf_inondations_a_afficher, gdf_rga=gdf_rga_a_afficher,
            df_communes=df_communes  # Passage indispensable pour le mapping Région
        )

with subtab_siren:
    st.info("Trouver des concurrents ayant le même code NAF qu'un établissement de référence.")
    # Interface corrigée (Scope Région/France + df_communes) et persistante
    gdf_concurrents = interface_recherche_concurrence(engine, df_communes)

    # Variables contextuelles
    ref_lat, ref_lon, ref_nom = None, None, "Votre Établissement"
    code_naf, scope, scope_value, ville_ref = None, None, None, None

    if st.session_state.get('etab_concurrence_details'):
        d = st.session_state.etab_concurrence_details
        ref_lat, ref_lon = d.get('latitude'), d.get('longitude')
        ref_nom = d.get('denominationunitelegale', "Votre Établissement")
        code_naf, scope_value = d.get('activiteprincipaleetablissement'), d.get('numero_dep')

        # Récupération du scope depuis le widget session state
        scope_widget = st.session_state.get('scope_conc_radio', 'Département')
        scope = "Ville" if "Ville" in scope_widget else "Région" if "Région" in scope_widget else "France" if "France" in scope_widget else "Département"

    if not gdf_concurrents.empty:
        if st.checkbox("Afficher le détail (tableau)", value=True, key="details_table_siren"):
            cols = ['denominationunitelegale', 'siret', 'siren', 'adresse', 'activiteprincipaleetablissement']
            st.dataframe(gdf_concurrents[[c for c in cols if c in gdf_concurrents.columns]])

        _afficher_resultats_concurrence(
            gdf_resultats=gdf_concurrents, source_name="SIREN", df_coefficients=df_coefficients,
            gdf_socio_filtre=gdf_socio_filtre, indicateur=indicateur, nom_indicateur=nom_indicateur,
            poi_selectionnes_sidebar=poi_selectionnes_sidebar,
            gdf_inondations=gdf_inondations_a_afficher, gdf_rga=gdf_rga_a_afficher,
            ref_lat=ref_lat, ref_lon=ref_lon, ref_nom=ref_nom,
            engine=engine, code_naf=code_naf, scope=scope, scope_value=scope_value, ville_ref=ville_ref,
            df_communes=df_communes  # Passage indispensable pour le mapping Région
        )