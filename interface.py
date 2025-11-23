import streamlit as st
import pandas as pd
from fonctions_cartographie import recherche_etablissements_osm
from config import POI_CONFIG
import geopandas as gpd
# MODIFIÉ : Imports corrigés
from fonctions_basiques import (
    find_etablissement_by_siret,
    find_etablissements_by_siren,
    get_etab_details_for_concurrence,
    extraire_ville_depuis_adresse,
    find_concurrents
)


# ==============================================
# Fonctions pour la page d'accueil (MODIFIÉES)
# ==============================================
def personnalisation_page():
    st.markdown(
        """<style>.title {color: #1f77b4; font-size: 40px; font-weight: bold;} .header {color: #ff7f0e; font-size: 30px; font-weight: bold;} .subheader {color: #2ca02c; font-size: 20px;} .footer {color: #1f77b4; font-size: 18px;}</style>""",
        unsafe_allow_html=True)


def affichage_titre():
    # MODIFIÉ (P3) : Titre simplifié
    st.title("🗺️ Analyse Géospatiale & SIREN")
    st.markdown(
        '<p class="footer">Explorez les données, analysez les tendances du marché, et optimisez vos stratégies commerciales.</p>',
        unsafe_allow_html=True)
    st.write("Bienvenue dans l'outil de Data Marketing. Choisissez une page dans le menu à gauche pour commencer.")


def navigation():
    with st.sidebar:
        st.markdown("## 🧭 Navigation")
        # MODIFIÉ (P3) : On retire la page INSEE de la navigation
        page_selectionnee = st.radio("Choisissez une page :", ("🏠 Accueil", "🗺️ Analyse Géospatiale"),
                                     index=0, key="navigation_main")
    if "Accueil" in page_selectionnee: return "accueil"
    if "Analyse" in page_selectionnee: return "osm"  # Renvoie "osm" pour la compatibilité


# ==============================================
# Fonctions pour la page INSEE (SUPPRIMÉES)
# ==============================================
# Les fonctions interface_apercu_donnees, interface_insee_filtres,
# interface_choix_centre_departement, et interface_choix_carte_insee
# ont été supprimées car la page_insee est désactivée (P3)

# ==============================================
# Fonctions pour la page OSM (PARTIE CORRIGÉE)
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
    CORRECTION : Gestion des départements Corses (2A/2B).
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

    # --- Cas Région ---
    if maille_recherche == 'Région':
        regions_disponibles = sorted(df_geo['Nom_Region'].unique())
        selection_geo = st.multiselect(
            "Choisissez une ou plusieurs régions",
            regions_disponibles,
            key=f"{key_prefix}_regions"
        )

    # --- Cas Département & Commune ---
    elif maille_recherche in ['Département', 'Commune']:
        df_deps = df_geo[['Num_Dep', 'Nom_Dep']].drop_duplicates().dropna()

        # Fonction locale pour trier correctement 2A et 2B
        def get_dep_sort_key(row):
            val = str(row['Num_Dep']).strip().upper()
            if val == '2A': return 20.1  # Juste après 19
            if val == '2B': return 20.2  # Juste après 2A
            if val.isdigit(): return int(val)
            return 999  # Les autres (971, etc) à la fin si format étrange

        # Construction de la liste triée
        liste_deps_temp = []
        for _, row in df_deps.iterrows():
            code = str(row['Num_Dep']).strip()
            nom = str(row['Nom_Dep']).strip()
            label = f"{code.zfill(2)} - {nom}"
            sort_key = get_dep_sort_key(row)
            liste_deps_temp.append((sort_key, label))

        # On trie la liste selon la clé numérique
        liste_deps_temp.sort(key=lambda x: x[0])

        # On ne garde que les labels pour l'affichage
        options_deps = [x[1] for x in liste_deps_temp]

        if maille_recherche == 'Département':
            selection_labels = st.multiselect(
                "Choisissez un ou plusieurs départements",
                options_deps,
                key=f"{key_prefix}_departements"
            )
            # Extraction du NOM du département (partie après le " - ")
            selection_geo = [label.split(' - ', 1)[1] for label in selection_labels]

        else:  # Cas Commune
            st.info("Pour trouver une commune, veuillez d'abord sélectionner son département.")
            dep_pour_communes_labels = st.multiselect(
                "D'abord, sélectionnez le(s) département(s)",
                options_deps,
                key=f"{key_prefix}_deps_pour_communes"
            )
            if dep_pour_communes_labels:
                # On récupère les NOMS des départements sélectionnés
                deps_selectionnes_noms = [label.split(' - ', 1)[1] for label in dep_pour_communes_labels]

                # Filtrage des communes
                communes_disponibles = sorted(
                    df_geo[df_geo['Nom_Dep'].isin(deps_selectionnes_noms)]['Nom_Ville'].unique())
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
    """
    st.sidebar.subheader("📍 Points d'Intérêt")
    selection = st.sidebar.multiselect(
        "Afficher les générateurs de flux :",
        options=list(POI_CONFIG.keys())
    )
    return selection

# ==================================================================
# MODIFIÉ : 'interface_point_interet' (Refactorisation P1, P2, P4, P5 + Tâche 4)
# ==================================================================
def interface_point_interet(engine):
    """
    Affiche une interface pour définir un POI via Adresse, Coords, ou SIREN/SIRET.
    Gère la logique de recherche SIREN (multiple) et la sélection.
    Retourne un dictionnaire unique avec la source, la valeur, et le mode d'analyse.
    """
    st.markdown("---")
    st.subheader("Définir une zone d'implantation à analyser")

    # Initialisation du dict de retour
    resultat = {
        "source": None,
        "valeur": None,
        "mode": "Point seul",
        "radius": 1000
    }

    # Initialiser st.session_state
    if 'siren_results' not in st.session_state:
        st.session_state.siren_results = None
    if 'siret_info' not in st.session_state:
        st.session_state.siret_info = None

    source_choix = st.radio(
        "Source du point d'intérêt :",
        ["Adresse", "Coordonnées", "SIREN (Siège) / SIRET (Étab.)"],
        horizontal=True,
        key="poi_source_choix",
        on_change=lambda: (
            st.session_state.update(siren_results=None, siret_info=None)
        )
    )

    # --- Panneau 1 : Recherche par Adresse ---
    if source_choix == "Adresse":
        poi_address_input = st.text_input(
            "Adresse du point d'intérêt :",
            placeholder="Ex: 8 Rue de Londres, 75009 Paris",
            help="Entrez une adresse complète pour un géocodage précis.",
            key="poi_adresse"
        )
        if poi_address_input:
            resultat["source"] = "Adresse"
            resultat["valeur"] = poi_address_input

    # --- Panneau 2 : Recherche par Coordonnées ---
    elif source_choix == "Coordonnées":
        col1, col2 = st.columns(2)
        with col1:
            poi_lat_input = st.number_input("Latitude :", value=48.85, step=0.0001, format="%.4f", key="poi_lat")
        with col2:
            poi_lon_input = st.number_input("Longitude :", value=2.35, step=0.0001, format="%.4f", key="poi_lon")

        resultat["source"] = "Coordonnées"
        resultat["valeur"] = {"latitude": poi_lat_input, "longitude": poi_lon_input}

    # --- Panneau 3 : NOUVEAU - Recherche par SIREN/SIRET ---
    elif source_choix == "SIREN (Siège) / SIRET (Étab.)":
        identifier_input = st.text_input(
            "Entrer le SIREN (9 chiffres) ou SIRET (14 chiffres) :",
            placeholder="Ex: 383597342 (Siège Carrefour) ou 38359734200010 (Étab.)",
            key="poi_siren_siret"
        )

        if st.button("Rechercher SIREN/SIRET", key="poi_siret_bouton"):
            st.session_state.siren_results = None
            st.session_state.siret_info = None

            clean_id = str(identifier_input).strip().replace(" ", "")

            if len(clean_id) == 14 and clean_id.isdigit():
                # CAS 1: SIRET (14 chiffres) - Simple
                etab_data = find_etablissement_by_siret(engine, clean_id)
                if etab_data:
                    st.success(f"Établissement trouvé : {etab_data.get('denominationunitelegale')}", icon="✅")
                    st.session_state.siret_info = etab_data  # Stocke le dict

            elif len(clean_id) == 9 and clean_id.isdigit():
                # CAS 2: SIREN (9 chiffres) - Complexe
                results = find_etablissements_by_siren(engine, clean_id)

                if isinstance(results, pd.DataFrame):
                    st.session_state.siren_results = results  # Stocke le DataFrame
                elif isinstance(results, dict):
                    st.success(f"Entreprise trouvée (établissement unique) : {results.get('denominationunitelegale')}",
                               icon="✅")
                    st.session_state.siret_info = results  # Stocke le dict
            else:
                st.warning("Entrée invalide. Veuillez entrer un SIREN (9 chiffres) ou un SIRET (14 chiffres).",
                           icon="⚠️")

        # --- Logique d'affichage si plusieurs résultats (Goal 1) ---
        if st.session_state.siren_results is not None:
            df_results = st.session_state.siren_results

            df_results['label'] = df_results.apply(
                lambda
                    row: f"{'[SIÈGE] ' if row['etablissementsiege'] else ''}{row.get('denominationunitelegale', 'N/A')} - {row.get('adresse', 'N/A')}",
                axis=1
            )

            st.warning(f"Ce SIREN possède {len(df_results)} établissements. Veuillez en choisir un :")

            df_results = df_results.sort_values(by='etablissementsiege', ascending=False)

            selected_label = st.selectbox(
                "Choisir un établissement :",
                options=df_results['label'],
                key="select_siret_from_siren",
                index=0  # Sélectionne le siège par défaut
            )

            if selected_label:
                # On récupère les infos de la ligne choisie
                selected_row = df_results[df_results['label'] == selected_label].iloc[0]
                st.session_state.siret_info = selected_row.to_dict()

        # --- Si un point est sélectionné ---
        if st.session_state.siret_info:
            resultat["source"] = "SIRET/SIREN"
            resultat["valeur"] = st.session_state.siret_info

            # (Goal 4)
            nom = st.session_state.siret_info.get('denominationunitelegale')
            if nom and "non indique" in str(nom).lower():
                st.warning("Le nom de cet établissement est 'Non indique' dans la base de données.", icon="ℹ️")

    # --- Partie commune (Mode d'analyse) ---
    st.markdown("**Mode d'analyse de la zone :**")
    analysis_mode = st.radio(
        "Mode d'analyse :",
        # MODIFIÉ (Tâche 4) : Ordre corrigé
        ('Point seul', "Cercle d'influence", 'Isochrones'),
        horizontal=True,
        key="poi_analysis_mode",
        label_visibility="collapsed"
    )

    resultat["mode"] = analysis_mode
    if analysis_mode == "Cercle d'influence":
        resultat["radius"] = st.slider("Rayon (m) :", 100, 5000, 1000, 100, key="poi_radius_slider")

    return resultat

def interface_selection_batiments():
    """
    Affiche les contrôles pour l'affichage des bâtiments.
    """
    afficher_batiments = False
    surface_min = 100
    surface_max = 250

    with st.expander("🏙️ Afficher et filtrer les bâtiments dans la zone"):
        # --- NOUVEAU : Avertissement proactif ---
        st.info(
            "ℹ️ **Note importante :** L'affichage des bâtiments nécessite une surface. Il est disponible uniquement avec les modes **'Cercle d'influence'** et **'Isochrones'** (pas en 'Point seul').")

        afficher_batiments = st.toggle(
            "Activer l'affichage des bâtiments",
            help="Affiche l'emprise au sol des bâtiments (Nécessite le mode Cercle ou Isochrone)."
        )

        if afficher_batiments:
            st.markdown("Filtrer par surface au sol :")
            col1, col2 = st.columns(2)

            with col1:
                surface_min = st.number_input(
                    "Min (m²)",
                    min_value=0,
                    max_value=100000,
                    value=0,
                    step=10,
                    key="surface_min"
                )

            with col2:
                surface_max = st.number_input(
                    "Max (m²)",
                    min_value=0,
                    max_value=100000,
                    value=3000,
                    step=50,
                    key="surface_max"
                )

    return afficher_batiments, surface_min, surface_max

def interface_selection_risques(df_communes):
    """
    Affiche les contrôles pour les risques.
    """
    st.sidebar.subheader("🌍 Données Climatiques")

    afficher_risques = st.sidebar.toggle("Enrichir avec des données climatiques")

    risque_selectionne = None
    regions_filtrees = []
    departements_filtres = []

    if afficher_risques:
        liste_risques = ["Inondations", "Sécheresse (RGA)"]
        risque_selectionne = st.sidebar.selectbox(
            "Choisir un type de risque :",
            options=liste_risques
        )

        filtre_geo = st.sidebar.radio(
            "Filtrer par :",
            options=["Région", "Département"],
            horizontal=True,
            key="filtre_geo_risque"
        )

        if filtre_geo == "Région":
            regions_disponibles = sorted(df_communes['Nom_Region'].unique())
            regions_filtrees = st.sidebar.multiselect(
                "Choisir une ou plusieurs régions :",
                options=regions_disponibles,
                key="filtre_risque_regions"
            )

        elif filtre_geo == "Département":
            df_deps = df_communes[['Num_Dep', 'Nom_Dep']].copy().dropna().drop_duplicates('Num_Dep')
            df_deps['Num_Dep'] = df_deps['Num_Dep'].astype(str).str.zfill(2)
            df_deps['Nom_Dep_Upper'] = df_deps['Nom_Dep'].str.upper().str.replace('-', ' ')
            df_deps = df_deps.sort_values('Num_Dep')

            df_deps['affichage_dep'] = df_deps['Num_Dep'] + " - " + df_deps['Nom_Dep_Upper']
            options_deps = df_deps['affichage_dep'].tolist()

            departements_filtres = st.sidebar.multiselect(
                "Choisir un ou plusieurs départements :",
                options=options_deps,
                key="filtre_risque_departements"
            )

        if not regions_filtrees and not departements_filtres:
            st.sidebar.info("Veuillez sélectionner au moins une zone géographique pour afficher les données de risque.")

    return risque_selectionne, regions_filtrees, departements_filtres

# ==================================================================
# Interface NOUVEAU : Interface pour l'étude de concurrence
# ==================================================================

def interface_recherche_concurrence(engine):
    """
    Affiche l'interface pour l'analyse de concurrence par SIRET + NAF.
    """
    if not engine:
        st.info("Connexion BDD requise.")
        return gpd.GeoDataFrame()

    if 'etab_concurrence_details' not in st.session_state:
        st.session_state.etab_concurrence_details = None

    siret_input = st.text_input(
        "Entrer le SIRET (14 chiffres) de votre établissement de référence :",
        key="concurrence_siret_input"
    )

    if st.button("1. Rechercher cet établissement", key="concurrence_search_siret"):
        st.session_state.etab_concurrence_details = get_etab_details_for_concurrence(engine, siret_input)
        st.session_state.gdf_concurrents = gpd.GeoDataFrame()

    if st.session_state.etab_concurrence_details:
        details = st.session_state.etab_concurrence_details

        code_naf = details.get('activiteprincipaleetablissement')
        desc_naf = details.get('description_naf', "Non disponible")
        adresse_complete = details.get('adresse', '')
        num_dep = details.get('numero_dep')
        nom_dep = details.get('nom_dep')

        # Extraction de la ville de référence pour l'affichage et le filtre
        ville_ref = extraire_ville_depuis_adresse(adresse_complete)

        st.success(f"Établissement trouvé : **{details.get('denominationunitelegale')}**")
        st.info(f"Code NAF : **{code_naf}** ({desc_naf})")
        st.caption(f"📍 {adresse_complete} ({nom_dep})")

        st.markdown("---")
        st.subheader("2. Définir la zone de recherche")

        # MODIFIÉ : Choix réactivé
        scope_choice = st.radio(
            "Rechercher les concurrents (même NAF) dans :",
            options=[f"Ville ({ville_ref})", f"Département ({nom_dep})"],
            key="concurrence_scope"
        )

        # Définition des paramètres de filtre
        scope = "Ville" if "Ville" in scope_choice else "Département"
        # Important : scope_value reste le DEPARTEMENT pour la requête SQL principale
        scope_value = num_dep

        if st.button("2. Lancer la recherche", type="primary", key="concurrence_find"):
            if scope and code_naf:
                gdf_concurrents = find_concurrents(
                    engine,
                    siret_input,
                    code_naf,
                    scope,
                    scope_value,
                    ville_origine=ville_ref  # On passe la ville pour le filtre Python
                )
                st.session_state.gdf_concurrents = gdf_concurrents
            else:
                st.error("Informations manquantes.")

    return st.session_state.get('gdf_concurrents', gpd.GeoDataFrame())


# ==================================================================
# Interface pour l'enrichissement de fichier (MODIFIÉ)
# ==================================================================

def interface_enrichissement_fichier():
    """
    Affiche l'interface pour l'upload et le choix des paramètres.
    Retourne : df, colonne_id, mode (siret/siren), only_siege (bool)
    """
    st.subheader("Enrichir un fichier local")

    uploaded_file = st.file_uploader(
        "Chargez votre fichier CSV",
        type=["csv"]
    )

    colonne_id = None
    type_identifiant = None
    only_siege = False  # Par défaut False

    if uploaded_file:
        try:
            df_preview = pd.read_csv(uploaded_file, nrows=5, sep=None, engine='python')
            uploaded_file.seek(0)

            col1, col2 = st.columns(2)
            with col1:
                colonne_id = st.selectbox(
                    "Quelle colonne contient les identifiants ?",
                    options=df_preview.columns
                )
            with col2:
                type_selection = st.radio(
                    "Type d'identifiant :",
                    options=["SIRET (14 chiffres)", "SIREN (9 chiffres)"]
                )

            # MODIFIÉ : Option de filtre Siège uniquement si mode SIREN
            if "SIREN" in type_selection:
                only_siege = st.checkbox(
                    "Ne récupérer que les Sièges Sociaux ?",
                    value=True,
                    help="Si décoché, récupère TOUS les établissements liés à ce SIREN (peut multiplier les lignes)."
                )

            if st.button("Lancer l'enrichissement", type="primary"):
                with st.spinner("Lecture du fichier..."):
                    # Force le type string pour préserver les zéros
                    df = pd.read_csv(uploaded_file, dtype={colonne_id: str}, sep=None, engine='python')

                mode = "siret" if "SIRET" in type_selection else "siren"
                # On retourne le booléen only_siege en plus
                return df, colonne_id, mode, only_siege

        except Exception as e:
            st.error(f"Erreur lors de la lecture du fichier : {e}")
            return None, None, None, False

    return None, None, None, False


# ==================================================================
# Interface pour le téléchargement (MODIFIÉ - Générique)
# ==================================================================

@st.cache_data
def convertir_df_en_csv(df):
    # Convertit le DataFrame en CSV, en UTF-8 avec BOM pour une meilleure compatibilité Excel
    return df.to_csv(index=False, sep=';').encode('utf-8-sig')


def interface_telechargement_fichier(df, titre_section, nom_fichier_csv, message_info=None, couleur_info="success"):
    """
    Affiche un DataFrame et un bouton de téléchargement de manière générique.
    Utilisable pour les succès ET les échecs.
    """
    st.subheader(titre_section)

    if message_info:
        if couleur_info == "success":
            st.success(message_info)
        elif couleur_info == "warning":
            st.warning(message_info)
        elif couleur_info == "error":
            st.error(message_info)

    with st.expander(f"Aperçu des données ({len(df)} lignes)"):
        st.dataframe(df.head(50))

    csv_data = convertir_df_en_csv(df)

    st.download_button(
        label=f"📥 Télécharger {nom_fichier_csv}",
        data=csv_data,
        file_name=nom_fichier_csv,
        mime="text/csv",
        key=f"dl_{nom_fichier_csv}"
    )