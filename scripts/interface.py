import streamlit as st
import pandas as pd
from fonctions_cartographie import recherche_etablissements_osm
from config import POI_CONFIG

# ==============================================
# Fonctions pour la page d'accueil (INCHANGÉES)
# ==============================================
def personnalisation_page():
    st.markdown(
        """<style>.title {color: #1f77b4; font-size: 40px; font-weight: bold;} .header {color: #ff7f0e; font-size: 30px; font-weight: bold;} .subheader {color: #2ca02c; font-size: 20px;} .footer {color: #1f77b4; font-size: 18px;}</style>""",
        unsafe_allow_html=True)


def affichage_titre():
    st.title("🌍 API étude sectorielle et concurrentielle Data Marketing")
    st.markdown(
        '<p class="footer">Explorez les données, analysez les tendances du marché, et optimisez vos stratégies commerciales.</p>',
        unsafe_allow_html=True)
    st.write("Bienvenue dans l'outil de Data Marketing. Choisissez une page dans le menu à gauche pour commencer.")


def navigation():
    with st.sidebar:
        st.markdown("## 🧭 Navigation")
        page_selectionnee = st.radio("Choisissez une page :", ("🏠 Accueil", "📊 Données INSEE", "🗺️ Données OSM"),
                                     index=0)
    if "Accueil" in page_selectionnee: return "accueil"
    if "INSEE" in page_selectionnee: return "insee"
    if "OSM" in page_selectionnee: return "osm"


# ==============================================
# Fonctions pour la page OSM (Corrigées et améliorées)
# ==============================================

INDICATEURS_CONFIG = {
    "revenu_median": {"display": "Revenu médian (€)", "raw": "Revenu_median", "pct": None},
    "taux_pauvrete": {"display": "Taux de pauvreté (%)", "raw": "Taux_pauvrete", "pct": None},
    "population_totale": {"display": "Population totale", "raw": "Population_totale", "pct": None},
    "pop_15_24": {"display": "Population 15-24 ans", "raw": "Pop_15_24_ans", "pct": "Part_jeunes_15_24_ans_pct"},
    "pop_25_54": {"display": "Population 25-54 ans", "raw": "Pop_25_54_ans", "pct": "Part_actifs_25_54_ans_pct"},
    "pop_55_79": {"display": "Population 55-79 ans", "raw": "Pop_55_79_ans", "pct": "Part_seniors_55_79_ans_pct"},
    "pop_80_plus": {"display": "Population 80 ans et plus", "raw": "Pop_80_ans_plus",
                    "pct": "Part_seniors_80_ans_plus_pct"},
    "menages_total": {"display": "Nombre total de ménages", "raw": "Nb_menages_total", "pct": None},
    "menages_monoparentaux": {"display": "Ménages monoparentaux", "raw": "Menages_monoparental",
                              "pct": "Part_menages_monoparentaux_pct"},
    "agriculteurs": {"display": "Ménages - Agriculteurs (CSP1)", "raw": "Menages_agriculteurs_CS1",
                     "pct": "Part_agriculteurs_CS1_pct"},
    "artisans": {"display": "Ménages - Artisans, commerçants (CSP2)", "raw": "Menages_artisans_commercants_CS2",
                 "pct": "Part_artisans_commercants_CS2_pct"},
    "cadres": {"display": "Ménages - Cadres (CSP3)", "raw": "Menages_cadres_prof_intelectuelles_CS3",
               "pct": "Part_cadres_CS3_pct"},
    "prof_intermediaires": {"display": "Ménages - Prof. intermédiaires (CSP4)",
                            "raw": "Menages_prof_intermediaires_CS4", "pct": "Part_prof_intermediaires_CS4_pct"},
    "employes": {"display": "Ménages - Employés (CSP5)", "raw": "Menages_employes_CS5", "pct": "Part_employes_CS5_pct"},
    "ouvriers": {"display": "Ménages - Ouvriers (CSP6)", "raw": "Menages_ouvriers_CS6", "pct": "Part_ouvriers_CS6_pct"},
    "retraites": {"display": "Ménages - Retraités (CSP7)", "raw": "Menages_retraites_CS7",
                  "pct": "Part_retraites_CS7_pct"},
    "autres": {"display": "Ménages - Autres sans act. pro. (CSP8)", "raw": "Menages_autres_sans_act_pro_CS8",
               "pct": "Part_autres_CS8_pct"}
}


def interface_recherche_osm(df_geo, key_prefix):
    """
    Affiche une interface complète pour la recherche OSM.
    Le titre est géré par la page appelante.
    """
    if df_geo is None or df_geo.empty:
        st.error("Données géographiques de référence non chargées.")
        return pd.DataFrame()

    noms_etablissements_osm = st.text_input(
        "Noms d'établissements (séparés par des virgules)",
        placeholder="Ex: Carrefour, Lidl",
        key=f"{key_prefix}_noms_etablissements"
    )
    noms_etablissements = [nom.strip() for nom in noms_etablissements_osm.split(",") if nom.strip()]

    st.markdown("Zone de recherche")
    maille_recherche = st.radio(
        "Maille :", ('Région', 'Département', 'Commune'),
        horizontal=True,
        key=f"{key_prefix}_maille_osm"
    )

    selection_geo = []
    if maille_recherche == 'Région':
        regions_disponibles = sorted(df_geo['Nom_Region'].unique())
        selection_geo = st.multiselect(
            "Choisissez une ou plusieurs régions",
            regions_disponibles,
            key=f"{key_prefix}_regions"
        )
    elif maille_recherche in ['Département', 'Commune']:
        df_deps = df_geo[['Num_Dep', 'Nom_Dep']].drop_duplicates()
        options_tuples = sorted([(int(row['Num_Dep']), f"{str(row['Num_Dep']).zfill(2)} - {row['Nom_Dep']}") for _, row in df_deps.iterrows() if str(row['Num_Dep']).isdigit()])
        options_deps = [label for num, label in options_tuples]

        if maille_recherche == 'Département':
            selection_labels = st.multiselect(
                "Choisissez un ou plusieurs départements",
                options_deps,
                key=f"{key_prefix}_departements"
            )
            selection_geo = [label.split(' - ')[1] for label in selection_labels]
        else:
            st.info("Pour trouver une commune, veuillez d'abord sélectionner son département.")
            dep_pour_communes_labels = st.multiselect(
                "D'abord, sélectionnez le(s) département(s)",
                options_deps,
                key=f"{key_prefix}_deps_pour_communes"
            )
            if dep_pour_communes_labels:
                deps_selectionnes = [label.split(' - ')[1] for label in dep_pour_communes_labels]
                communes_disponibles = sorted(df_geo[df_geo['Nom_Dep'].isin(deps_selectionnes)]['Nom_Ville'].unique())
                selection_geo = st.multiselect(
                    "Puis, choisissez une ou plusieurs communes",
                    communes_disponibles,
                    key=f"{key_prefix}_communes"
                )

    if st.button("Lancer la recherche", type="primary", key=f"{key_prefix}_bouton_recherche"):
        session_state_key_results = f"df_etablissements_osm_{key_prefix}"
        villes_a_chercher = []
        if selection_geo:
            if maille_recherche == 'Région':
                villes_a_chercher = df_geo[df_geo['Nom_Region'].isin(selection_geo)]['Nom_Ville'].tolist()
            elif maille_recherche == 'Département':
                villes_a_chercher = df_geo[df_geo['Nom_Dep'].isin(selection_geo)]['Nom_Ville'].tolist()
            elif maille_recherche == 'Commune':
                villes_a_chercher = selection_geo
        if noms_etablissements and villes_a_chercher:
            with st.spinner(f"Recherche en cours..."):
                df_resultats = recherche_etablissements_osm(noms_etablissements, list(set(villes_a_chercher)))
            st.session_state[session_state_key_results] = df_resultats if df_resultats is not None else pd.DataFrame()
        else:
            st.warning("Veuillez entrer un nom d’établissement ET sélectionner une zone.")
            st.session_state[session_state_key_results] = pd.DataFrame()

    return st.session_state.get(f"df_etablissements_osm_{key_prefix}", pd.DataFrame())


def interface_selection_socio(dict_geodatas):
    """Affiche l'interface de sélection socio-économique et retourne les données filtrées."""
    gdf_socio_filtre, colonne_a_afficher, nom_indicateur_final, maille_choisie = None, None, None, None

    st.sidebar.subheader("📊 Analyse du Territoire")
    if st.sidebar.toggle("Enrichir avec des données de territoire"):
        nom_affiche_choisi = st.sidebar.selectbox("Indicateur :", [v['display'] for v in INDICATEURS_CONFIG.values()])
        config_choisie = next(c for c in INDICATEURS_CONFIG.values() if c['display'] == nom_affiche_choisi)
        colonne_a_afficher, nom_indicateur_final = config_choisie['raw'], config_choisie['display']

        if config_choisie['pct'] is not None:
            type_affichage = st.sidebar.radio("Afficher en :", ("Valeur absolue", "Pourcentage (%)"), horizontal=True)
            if type_affichage == "Pourcentage (%)":
                colonne_a_afficher, nom_indicateur_final = config_choisie['pct'], f"{config_choisie['display']} (%)"

        maille_disponible = ['IRIS', 'Commune', 'Département']
        maille_choisie = st.sidebar.radio("Niveau d'analyse :", maille_disponible, index=1, horizontal=True)
        gdf_a_afficher = dict_geodatas.get(maille_choisie)

        if gdf_a_afficher is not None:
            df_deps = dict_geodatas.get('Département')
            if df_deps is not None:
                df_deps['label'] = df_deps['CODE_DEPT'] + ' - ' + df_deps['NOM_COM']
                deps_selectionnes = st.sidebar.multiselect("Filtrer par département :",
                                                           options=df_deps['label'].unique().tolist())
                if deps_selectionnes:
                    codes_deps = [d.split(' - ')[0] for d in deps_selectionnes]
                    gdf_socio_filtre = gdf_a_afficher[gdf_a_afficher['CODE_DEPT'].isin(codes_deps)]
                else:
                    st.sidebar.info("Sélectionnez au moins un département pour afficher les données sur la carte.")
            else:
                gdf_socio_filtre = gdf_a_afficher
        else:
            st.sidebar.error(f"Données non disponibles pour la maille {maille_choisie}")

    return gdf_socio_filtre, colonne_a_afficher, nom_indicateur_final, maille_choisie



def interface_selection_poi():
    """
    Affiche un multiselect dans la sidebar pour choisir les types de POI.
    Retourne la liste des catégories sélectionnées par l'utilisateur.
    """
    st.sidebar.subheader("📍 Points d'Intérêt")
    selection = st.sidebar.multiselect(
        "Afficher les générateurs de flux :",
        options=list(POI_CONFIG.keys())
    )
    return selection

def interface_point_interet():
    """
    Affiche une interface pour définir un POI et choisir le mode d'analyse de sa zone.
    Le titre est maintenant simplifié.
    """
    st.markdown("---")
    st.subheader("Définir une zone d'implantation à analyser") # Titre simplifié

    # Initialisation des variables de retour
    poi_address, poi_lat, poi_lon = None, None, None
    analysis_mode = 'Isochrones'
    radius_meters = 1000

    tab1, tab2 = st.tabs(["Saisir une adresse", "Saisir des coordonnées"])

    with tab1:
        poi_address = st.text_input(
            "Adresse du point d'intérêt :",
            placeholder="Ex: 8 Rue de Londres, 75009 Paris",
            help="Entrez une adresse complète pour un géocodage précis.",
            key="poi_adresse"
        )

    with tab2:
        col1, col2 = st.columns(2)
        with col1:
            poi_lat = st.number_input("Latitude :", value=48.85, step=0.0001, format="%.4f", key="poi_lat")
        with col2:
            poi_lon = st.number_input("Longitude :", value=2.35, step=0.0001, format="%.4f", key="poi_lon")

    st.markdown("**Mode d'analyse de la zone :**")
    analysis_mode = st.radio(
        "Mode d'analyse :",
        ('Isochrones', "Cercle d'influence"),
        horizontal=True,
        key="poi_analysis_mode",
        label_visibility="collapsed"
    )

    if analysis_mode == "Cercle d'influence":
        radius_meters = st.slider("Rayon (m) :", 100, 5000, 1000, 100, key="poi_radius_slider")

    if poi_address:
        return poi_address, None, None, analysis_mode, radius_meters
    else:
        return None, poi_lat, poi_lon, analysis_mode, radius_meters


def interface_selection_batiments():
    """
    Affiche les contrôles pour l'affichage des bâtiments directement dans la page
    (et non plus dans la sidebar), à l'intérieur d'un expander.
    """
    afficher_batiments = False
    surface_min = 0
    surface_max = 5000  # Valeur par défaut haute

    with st.expander("🏙️ Afficher et filtrer les bâtiments dans la zone"):
        afficher_batiments = st.toggle(
            "Activer l'affichage des bâtiments",
            help="Affiche l'emprise au sol des bâtiments présents dans la zone d'analyse définie."
        )

        if afficher_batiments:
            st.markdown("Filtrer par surface :")
            col1, col2 = st.columns(2)

            with col1:
                surface_min = st.number_input(
                    "Min (m²)",
                    min_value=0,
                    max_value=100000,
                    value=50,  # Valeur par défaut
                    step=10,
                    key="surface_min"
                )

            with col2:
                surface_max = st.number_input(
                    "Max (m²)",
                    min_value=0,
                    max_value=100000,
                    value=500,  # Valeur par défaut
                    step=10,
                    key="surface_max"
                )

    return afficher_batiments, surface_min, surface_max