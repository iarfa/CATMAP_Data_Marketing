# Fichier: interface.py
import streamlit as st
import pandas as pd
from config import POI_CONFIG
from fonctions_cartographie import recherche_etablissements_osm, geocoder_adresse_nominatim_ui
from fonctions_basiques import (
    find_etablissement_by_siret,
    find_etablissements_by_siren,
    get_etab_details_for_concurrence,
    find_concurrents,
    extraire_ville_depuis_adresse
)

# ==============================================
# CONFIGURATION DES INDICATEURS SOCIO
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


# ==============================================
# 1. FONCTIONS SIDEBAR (OPTIMISÉES "CLEAN")
# ==============================================

def interface_selection_socio(dict_geodatas):
    """Affiche l'interface de sélection socio-économique dans un EXPANDER."""
    gdf_socio_filtre, colonne_a_afficher, nom_indicateur_final, maille_choisie = None, None, None, None

    # MODIFIÉ : Utilisation d'un expander pour cacher les détails par défaut
    with st.sidebar.expander("📊 Données Socio-Démographiques", expanded=False):
        activer_socio = st.toggle("Activer la couche Socio", value=False)

        if activer_socio:
            nom_affiche_choisi = st.selectbox("Indicateur :", [v['display'] for v in INDICATEURS_CONFIG.values()])
            config_choisie = next(c for c in INDICATEURS_CONFIG.values() if c['display'] == nom_affiche_choisi)
            colonne_a_afficher, nom_indicateur_final = config_choisie['raw'], config_choisie['display']

            if config_choisie['pct'] is not None:
                type_affichage = st.radio("Format :", ("Valeur absolue", "Pourcentage (%)"), horizontal=True)
                if type_affichage == "Pourcentage (%)":
                    colonne_a_afficher, nom_indicateur_final = config_choisie['pct'], f"{config_choisie['display']} (%)"

            maille_disponible = ['IRIS', 'Commune', 'Département']
            maille_choisie = st.radio("Maillage :", maille_disponible, index=1, horizontal=True)
            gdf_a_afficher = dict_geodatas.get(maille_choisie)

            if gdf_a_afficher is not None:
                df_deps = dict_geodatas.get('Département')
                if df_deps is not None:
                    df_deps['label'] = df_deps['CODE_DEPT'] + ' - ' + df_deps['NOM_COM']
                    deps_selectionnes = st.multiselect("Filtrer (Optionnel) :",
                                                       options=df_deps['label'].unique().tolist())
                    if deps_selectionnes:
                        codes_deps = [d.split(' - ')[0] for d in deps_selectionnes]
                        gdf_socio_filtre = gdf_a_afficher[gdf_a_afficher['CODE_DEPT'].isin(codes_deps)]
                    else:
                        gdf_socio_filtre = gdf_a_afficher  # On retourne tout si pas de filtre
            else:
                st.error(f"Données non disponibles pour la maille {maille_choisie}")

    return gdf_socio_filtre, colonne_a_afficher, nom_indicateur_final, maille_choisie


def interface_selection_poi():
    """
    Affiche un multiselect pour les POI dans un EXPANDER.
    """
    selection = []
    # MODIFIÉ : Expander pour alléger la vue
    with st.sidebar.expander("📍 Points d'Intérêt (POI)", expanded=False):
        selection = st.multiselect(
            "Générateurs de flux :",
            options=list(POI_CONFIG.keys()),
            default=[]
        )
    return selection


def interface_selection_risques(df_communes):
    """
    Affiche les contrôles pour les risques dans un EXPANDER.
    """
    risque_selectionne = None
    regions_filtrees = []
    departements_filtres = []

    # MODIFIÉ : Expander
    with st.sidebar.expander("🌍 Risques & Climat", expanded=False):
        afficher_risques = st.toggle("Activer la couche Risques", value=False)

        if afficher_risques:
            liste_risques = ["Inondations", "Sécheresse (RGA)"]
            risque_selectionne = st.selectbox("Type de risque :", options=liste_risques)

            filtre_geo = st.radio("Zone géographique :", options=["Région", "Département"], horizontal=True)

            if filtre_geo == "Région":
                regions_disponibles = sorted(df_communes['Nom_Region'].unique())
                regions_filtrees = st.multiselect("Régions :", options=regions_disponibles)

            elif filtre_geo == "Département":
                df_deps = df_communes[['Num_Dep', 'Nom_Dep']].copy().dropna().drop_duplicates('Num_Dep')

                # Tri optimisé pour la Corse (2A/2B)
                def get_sort_key(val):
                    v = str(val).upper()
                    if v == '2A': return 20.1
                    if v == '2B': return 20.2
                    return int(v) if v.isdigit() else 999

                df_deps['sort_key'] = df_deps['Num_Dep'].apply(get_sort_key)
                df_deps = df_deps.sort_values('sort_key')

                df_deps['label'] = df_deps['Num_Dep'].astype(str).str.zfill(2) + " - " + df_deps['Nom_Dep'].str.upper()
                departements_filtres = st.multiselect("Départements :", options=df_deps['label'].tolist())

            if not regions_filtrees and not departements_filtres:
                st.caption("⚠️ Sélectionnez une zone pour afficher le risque.")

    return risque_selectionne, regions_filtrees, departements_filtres


# ==============================================
# 2. FONCTIONS RECHERCHE (MAIN AREA)
# ==============================================

def interface_recherche_osm(df_geo, key_prefix):
    """Interface recherche OSM (Avec gestion Corse)."""
    if df_geo is None or df_geo.empty:
        st.error("Données géographiques non chargées.")
        return pd.DataFrame()

    noms_etablissements_osm = st.text_input(
        "Noms d'établissements (séparés par des virgules)",
        placeholder="Ex: Carrefour, Lidl",
        key=f"{key_prefix}_noms_etablissements"
    )
    noms_etablissements = [nom.strip() for nom in noms_etablissements_osm.split(",") if nom.strip()]

    st.markdown("Zone de recherche")
    maille_recherche = st.radio("Maille :", ('Région', 'Département', 'Commune'), horizontal=True,
                                key=f"{key_prefix}_maille_osm")

    selection_geo = []

    if maille_recherche == 'Région':
        regions = sorted(df_geo['Nom_Region'].unique())
        selection_geo = st.multiselect("Régions :", regions, key=f"{key_prefix}_regions")

    elif maille_recherche in ['Département', 'Commune']:
        df_deps = df_geo[['Num_Dep', 'Nom_Dep']].drop_duplicates().dropna()

        # Tri Corse
        def get_sort(row):
            v = str(row['Num_Dep']).upper()
            if v == '2A': return 20.1
            if v == '2B': return 20.2
            return int(v) if v.isdigit() else 999

        df_deps['sort'] = df_deps.apply(get_sort, axis=1)
        df_deps = df_deps.sort_values('sort')
        options_deps = (df_deps['Num_Dep'].astype(str).str.zfill(2) + " - " + df_deps['Nom_Dep']).tolist()

        if maille_recherche == 'Département':
            sel = st.multiselect("Départements :", options_deps, key=f"{key_prefix}_departements")
            selection_geo = [s.split(' - ')[1] for s in sel]
        else:
            st.info("Sélectionnez d'abord un département.")
            dep_sel = st.multiselect("Département(s) :", options_deps, key=f"{key_prefix}_deps_pour_communes")
            if dep_sel:
                noms_deps = [s.split(' - ')[1] for s in dep_sel]
                communes = sorted(df_geo[df_geo['Nom_Dep'].isin(noms_deps)]['Nom_Ville'].unique())
                selection_geo = st.multiselect("Communes :", communes, key=f"{key_prefix}_communes")

    if st.button("Lancer la recherche", type="primary", key=f"{key_prefix}_btn"):
        villes = []
        if selection_geo:
            if maille_recherche == 'Région':
                villes = df_geo[df_geo['Nom_Region'].isin(selection_geo)]['Nom_Ville'].tolist()
            elif maille_recherche == 'Département':
                villes = df_geo[df_geo['Nom_Dep'].isin(selection_geo)]['Nom_Ville'].tolist()
            elif maille_recherche == 'Commune':
                villes = selection_geo

        if noms_etablissements and villes:
            with st.spinner("Recherche OSM..."):
                df_res = recherche_etablissements_osm(noms_etablissements, list(set(villes)))
            return df_res if df_res is not None else pd.DataFrame()
        else:
            st.warning("Remplissez les champs.")
            return pd.DataFrame()

    return pd.DataFrame()


def interface_recherche_concurrence(engine):
    """Interface recherche SIREN/NAF avec filtre Ville."""
    if not engine: return pd.DataFrame()

    if 'etab_concurrence_details' not in st.session_state:
        st.session_state.etab_concurrence_details = None

    siret_input = st.text_input("SIRET de référence (14 chiffres) :", key="concurrence_siret_input")

    if st.button("1. Rechercher l'établissement", key="concurrence_search"):
        st.session_state.etab_concurrence_details = get_etab_details_for_concurrence(engine, siret_input)
        st.session_state.gdf_concurrents = pd.DataFrame()

    if st.session_state.etab_concurrence_details:
        d = st.session_state.etab_concurrence_details
        naf = d.get('activiteprincipaleetablissement')
        desc = d.get('description_naf', 'Non dispo')
        addr = d.get('adresse', '')
        ville_ref = extraire_ville_depuis_adresse(addr)

        st.success(f"Trouvé : **{d.get('denominationunitelegale')}**")
        st.info(f"NAF : **{naf}** ({desc})")
        st.caption(f"📍 {addr}")

        st.markdown("---")
        st.subheader("2. Zone de recherche")

        # Boutons de choix
        choix = st.radio("Périmètre :", [f"Ville ({ville_ref})", f"Département ({d.get('nom_dep')})"], key="scope_conc")
        scope = "Ville" if "Ville" in choix else "Département"

        if st.button("2. Lancer l'analyse", type="primary"):
            return find_concurrents(engine, siret_input, naf, scope, d.get('numero_dep'), ville_ref)

    return st.session_state.get('gdf_concurrents', pd.DataFrame())


# ==============================================
# 3. FONCTIONS IMPLANTATION
# ==============================================

def interface_point_interet(engine):
    """
    Affiche une interface pour définir un POI via Adresse, Coords, ou SIREN/SIRET.
    """
    st.markdown("---")
    st.subheader("Définir une zone d'implantation à analyser")

    resultat = {
        "source": None,
        "valeur": None,
        "mode": "Point seul",
        "radius": 1000
    }

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

    # --- Adresse ---
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

    # --- Coordonnées ---
    elif source_choix == "Coordonnées":
        col1, col2 = st.columns(2)
        with col1:
            poi_lat_input = st.number_input("Latitude :", value=48.85, step=0.0001, format="%.4f", key="poi_lat")
        with col2:
            poi_lon_input = st.number_input("Longitude :", value=2.35, step=0.0001, format="%.4f", key="poi_lon")

        resultat["source"] = "Coordonnées"
        resultat["valeur"] = {"latitude": poi_lat_input, "longitude": poi_lon_input}

    # --- SIREN/SIRET ---
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
                etab_data = find_etablissement_by_siret(engine, clean_id)
                if etab_data:
                    st.success(f"Établissement trouvé : {etab_data.get('denominationunitelegale')}", icon="✅")
                    st.session_state.siret_info = etab_data

            elif len(clean_id) == 9 and clean_id.isdigit():
                results = find_etablissements_by_siren(engine, clean_id)

                if isinstance(results, pd.DataFrame):
                    st.session_state.siren_results = results
                elif isinstance(results, dict):
                    st.success(f"Entreprise trouvée (établissement unique) : {results.get('denominationunitelegale')}",
                               icon="✅")
                    st.session_state.siret_info = results
            else:
                st.warning("Entrée invalide. Veuillez entrer un SIREN (9 chiffres) ou un SIRET (14 chiffres).",
                           icon="⚠️")

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
                index=0
            )
            if selected_label:
                selected_row = df_results[df_results['label'] == selected_label].iloc[0]
                st.session_state.siret_info = selected_row.to_dict()

        if st.session_state.siret_info:
            resultat["source"] = "SIRET/SIREN"
            resultat["valeur"] = st.session_state.siret_info
            nom = st.session_state.siret_info.get('denominationunitelegale')
            if nom and "non indique" in str(nom).lower():
                st.warning("Le nom de cet établissement est 'Non indique' dans la base de données.", icon="ℹ️")

    # --- Mode d'analyse ---
    st.markdown("**Mode d'analyse de la zone :**")
    analysis_mode = st.radio(
        "Mode d'analyse :",
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
    surface_min = 0
    surface_max = 3000

    with st.expander("🏙️ Afficher et filtrer les bâtiments dans la zone"):
        st.info(
            "ℹ️ **Note :** L'affichage des bâtiments nécessite le mode **'Cercle'** ou **'Isochrones'** (pas 'Point seul').")

        afficher_batiments = st.toggle(
            "Activer l'affichage des bâtiments",
            help="Affiche l'emprise au sol des bâtiments (Nécessite une zone)."
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


# ==============================================
# 4. FONCTIONS ENRICHISSEMENT
# ==============================================

def interface_enrichissement_fichier():
    """
    Affiche l'interface pour l'upload et le choix des paramètres.
    """
    st.subheader("Enrichir un fichier local")

    uploaded_file = st.file_uploader(
        "Chargez votre fichier CSV",
        type=["csv"]
    )

    colonne_id = None
    type_identifiant = None
    only_siege = False

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

            if "SIREN" in type_selection:
                only_siege = st.checkbox(
                    "Ne récupérer que les Sièges Sociaux ?",
                    value=True,
                    help="Si décoché, récupère TOUS les établissements liés à ce SIREN."
                )

            if st.button("Lancer l'enrichissement", type="primary"):
                with st.spinner("Lecture du fichier..."):
                    df = pd.read_csv(uploaded_file, dtype={colonne_id: str}, sep=None, engine='python')

                mode = "siret" if "SIRET" in type_selection else "siren"
                return df, colonne_id, mode, only_siege

        except Exception as e:
            st.error(f"Erreur lors de la lecture du fichier : {e}")
            return None, None, None, False

    return None, None, None, False


@st.cache_data
def convertir_df_en_csv(df):
    return df.to_csv(index=False, sep=';').encode('utf-8-sig')


def interface_telechargement_fichier(df, titre_section, nom_fichier_csv, message_info=None, couleur_info="success"):
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