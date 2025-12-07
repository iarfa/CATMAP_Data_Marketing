# Fichier: interface.py
import streamlit as st
import pandas as pd
from config import POI_CONFIG

# Imports des fonctions backend nécessaires
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
# 1. FONCTIONS SIDEBAR (FILTRES)
# ==============================================

def interface_selection_socio(dict_geodatas):
    """
    Sélecteur pour la couche socio-démographique.
    Utilisé par Page 01 et Page 02.
    """
    st.markdown("### 👥 Socio-Démographie")

    # On ajoute une option vide pour ne rien afficher par défaut
    options = ["Aucun"] + [v['display'] for v in INDICATEURS_CONFIG.values()]
    # Clé unique pour éviter les conflits entre pages
    choix = st.selectbox("Indicateur :", options, index=0, key="sel_socio_main_interface")

    if choix == "Aucun":
        return None, None, None, None

    config = next(c for c in INDICATEURS_CONFIG.values() if c['display'] == choix)
    colonne, label = config['raw'], config['display']

    # Option pourcentage si disponible
    if config['pct']:
        c1, c2 = st.columns([3, 1])
        with c2:
            is_pct = st.toggle("%", value=True, help="Afficher en pourcentage", key="tog_pct_socio_interface")
        if is_pct:
            colonne, label = config['pct'], f"{config['display']} (%)"

    # Par défaut on renvoie la maille IRIS
    return dict_geodatas.get('IRIS'), colonne, label, 'IRIS'

def interface_selection_poi():
    """Sélecteur pour les POI."""
    st.markdown("### 📍 Points d'Intérêt")
    return st.multiselect(
        "Afficher sur la carte :",
        options=list(POI_CONFIG.keys()),
        default=[],
        placeholder="Ex: Écoles, Gares...",
        key="sel_poi_main_interface"
    )

def interface_filtre_geo_risque(df_communes, key_suffix):
    """
    NOUVEAU (Page 02) : Génère les filtres Région/Département pour un risque spécifique (Inondation ou RGA).
    Permet d'avoir deux blocs de filtres indépendants dans la même page.
    """
    regions_filtrees = []
    departements_filtres = []

    mode = st.radio(
        "Filtrer par :",
        ["Région", "Département"],
        horizontal=True,
        key=f"mode_geo_{key_suffix}",
        label_visibility="collapsed"
    )

    if mode == "Région":
        regions = sorted(df_communes['Nom_Region'].unique())
        regions_filtrees = st.multiselect(
            "Sélectionner Région(s) :",
            regions,
            key=f"reg_{key_suffix}"
        )
    else:
        # Préparation et tri propre des départements
        df_deps = df_communes[['Num_Dep', 'Nom_Dep']].copy().dropna().drop_duplicates('Num_Dep')
        df_deps['sort_key'] = df_deps['Num_Dep'].apply(lambda x: str(x).zfill(2) if str(x).isdigit() else x)
        df_deps = df_deps.sort_values('sort_key')
        df_deps['label'] = df_deps['Num_Dep'].astype(str).str.zfill(2) + " - " + df_deps['Nom_Dep'].str.upper()

        departements_filtres = st.multiselect(
            "Sélectionner Département(s) :",
            df_deps['label'].tolist(),
            key=f"dep_{key_suffix}"
        )

    return regions_filtrees, departements_filtres

def interface_selection_risques(df_communes):
    """
    Interface harmonisée pour la Sidebar (Page 01).
    Plus d'expander caché, on affiche tout clairement comme les autres sections.
    """
    st.markdown("### 🌪️ Risques & Climat")

    # On force l'affichage par défaut pour que l'utilisateur voit les options
    # Ou on met un toggle si on veut gagner de la place
    afficher_risques = st.toggle("Activer la couche Risques", value=False, key="tog_risk_harmonized")

    risque_selectionne = None
    regions_filtrees = []
    departements_filtres = []

    if afficher_risques:
        liste_risques = ["Inondations", "Sécheresse (RGA)"]
        risque_selectionne = st.selectbox("Type de risque :", options=liste_risques, key="sel_risk_harmonized")

        st.caption("Filtrage Géographique (Optionnel)")
        filtre_geo = st.radio("Zone :", options=["Région", "Département"], horizontal=True,
                              label_visibility="collapsed", key="rad_geo_harmonized")

        if filtre_geo == "Région":
            regions_disponibles = sorted(df_communes['Nom_Region'].unique())
            regions_filtrees = st.multiselect("Choisir Région(s) :", options=regions_disponibles,
                                              key="mul_reg_harmonized")

        elif filtre_geo == "Département":
            df_deps = df_communes[['Num_Dep', 'Nom_Dep']].copy().dropna().drop_duplicates('Num_Dep')
            df_deps['sort_key'] = df_deps['Num_Dep'].apply(lambda x: str(x).zfill(2) if str(x).isdigit() else x)
            df_deps = df_deps.sort_values('sort_key')
            df_deps['label'] = df_deps['Num_Dep'].astype(str).str.zfill(2) + " - " + df_deps['Nom_Dep'].str.upper()
            departements_filtres = st.multiselect("Choisir Département(s) :", options=df_deps['label'].tolist(),
                                                  key="mul_dep_harmonized")

    return risque_selectionne, regions_filtrees, departements_filtres

def interface_selection_batiments():
    """
    Sélecteur simple pour les critères bâtiments.
    Utilisé dans Page 02 (Sidebar).
    """
    c1, c2 = st.columns(2)
    with c1:
        surface_min = st.number_input("Min (m²)", 0, 100000, 0, step=50, key="surf_min_bat")
    with c2:
        surface_max = st.number_input("Max (m²)", 0, 100000, 3000, step=100, key="surf_max_bat")

    return True, surface_min, surface_max
# ==============================================
# 2. FONCTIONS RECHERCHE (MAIN AREA)
# ==============================================

def interface_recherche_osm(df_geo, key_prefix):
    """
    Interface recherche OSM avec Session State pour corriger le bug du Radar.
    """
    # Clé unique pour stocker les résultats de cette recherche spécifique
    session_key = f"{key_prefix}_resultats"

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
        df_deps['sort_key'] = df_deps['Num_Dep'].apply(lambda x: str(x).zfill(2) if str(x).isdigit() else x)
        df_deps = df_deps.sort_values('sort_key')
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

    # BOUTON DE RECHERCHE
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
                # On stocke le résultat dans la session
                st.session_state[session_key] = recherche_etablissements_osm(noms_etablissements, list(set(villes)))
        else:
            st.warning("Remplissez les champs.")
            st.session_state[session_key] = pd.DataFrame()

    # On retourne ce qui est stocké en mémoire (persiste après rechargement)
    return st.session_state.get(session_key, pd.DataFrame())

def interface_recherche_concurrence(engine, df_communes):
    """
    Interface SIREN (Déjà corrigée précédemment, je remets juste pour être sûr qu'on utilise bien Session State).
    """
    if not engine: return pd.DataFrame()

    if 'etab_concurrence_details' not in st.session_state:
        st.session_state.etab_concurrence_details = None

    # Clé de stockage des résultats
    if 'gdf_concurrents' not in st.session_state:
        st.session_state.gdf_concurrents = pd.DataFrame()

    siret_input = st.text_input("SIRET de référence (14 chiffres) :", key="concurrence_siret_input")

    if st.button("1. Rechercher l'établissement", key="concurrence_search"):
        with st.spinner("Interrogation base SIRENE..."):
            st.session_state.etab_concurrence_details = get_etab_details_for_concurrence(engine, siret_input)
            # On vide les résultats précédents si on change d'établissement cible
            st.session_state.gdf_concurrents = pd.DataFrame()

    if st.session_state.etab_concurrence_details:
        d = st.session_state.etab_concurrence_details
        naf = d.get('activiteprincipaleetablissement')
        desc = d.get('description_naf', 'Non dispo')
        addr = d.get('adresse', '')
        num_dep_etab = d.get('numero_dep')
        # nom_dep_etab = d.get('nom_dep') # Variable inutilisée pour le moment
        ville_ref = extraire_ville_depuis_adresse(addr)

        st.success(f"Trouvé : **{d.get('denominationunitelegale')}**")
        st.info(f"NAF : **{naf}** ({desc})")

        st.markdown("---")
        st.subheader("2. Zone de recherche")

        # Logique de pré-remplissage Scope
        region_etab = "Inconnue"
        if not df_communes.empty and num_dep_etab:
            match_reg = df_communes[df_communes['Num_Dep'] == str(num_dep_etab)]
            if not match_reg.empty:
                region_etab = match_reg.iloc[0]['Nom_Region']

        choix_scope = st.radio(
            "Périmètre d'analyse :",
            [f"Ville ({ville_ref})", f"Département ({num_dep_etab})", f"Région ({region_etab})", "France Entière"],
            key="scope_conc_radio"
        )

        scope_type = "Département"
        scope_value = num_dep_etab

        if "Ville" in choix_scope:
            scope_type = "Ville"
        elif "Département" in choix_scope:
            scope_type = "Département"
        elif "Région" in choix_scope:
            scope_type = "Région"
            if not df_communes.empty:
                deps_region = df_communes[df_communes['Nom_Region'] == region_etab]['Num_Dep'].unique().tolist()
                scope_value = deps_region
            else:
                scope_value = [num_dep_etab]
        elif "France" in choix_scope:
            scope_type = "France"
            scope_value = None

        if st.button(f"2. Lancer l'analyse ({scope_type})", type="primary"):
            with st.spinner(f"Recherche des concurrents sur : {scope_type}..."):
                # On stocke dans la session
                st.session_state.gdf_concurrents = find_concurrents(engine, siret_input, naf, scope_type, scope_value,
                                                                    ville_ref)

    # On retourne la donnée persistée
    return st.session_state.gdf_concurrents

# ==============================================
# 3. ZONE & FICHIERS
# ==============================================

def interface_point_interet(engine):
    """
    Interface définition zone (Adresse / Coords / SIRET).
    Utilisé partout (Page 02, Page 03).
    """
    st.markdown("---")
    st.subheader("Définir une zone d'implantation")

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
        on_change=lambda: st.session_state.update(siren_results=None, siret_info=None)
    )

    # --- Adresse ---
    if source_choix == "Adresse":
        val = st.text_input("Adresse :", placeholder="Ex: 8 Rue de Londres, 75009 Paris", key="poi_adresse")
        if val:
            resultat["source"] = "Adresse"
            resultat["valeur"] = val

    # --- Coordonnées ---
    elif source_choix == "Coordonnées":
        c1, c2 = st.columns(2)
        lat = c1.number_input("Latitude :", value=48.85, format="%.4f", key="poi_lat")
        lon = c2.number_input("Longitude :", value=2.35, format="%.4f", key="poi_lon")
        resultat["source"] = "Coordonnées"
        resultat["valeur"] = {"latitude": lat, "longitude": lon}

    # --- SIREN/SIRET ---
    elif source_choix == "SIREN (Siège) / SIRET (Étab.)":
        inp = st.text_input("SIREN/SIRET :", placeholder="383597342...", key="poi_siren_siret")

        if st.button("Rechercher", key="poi_siret_bouton"):
            clean = inp.strip().replace(" ", "")
            if len(clean) == 14:
                res = find_etablissement_by_siret(engine, clean)
                if res:
                    st.success(f"Trouvé : {res.get('denominationunitelegale')}")
                    st.session_state.siret_info = res
            elif len(clean) == 9:
                res = find_etablissements_by_siren(engine, clean)
                if isinstance(res, dict):
                    st.success(f"Trouvé : {res.get('denominationunitelegale')}")
                    st.session_state.siret_info = res
                elif isinstance(res, pd.DataFrame):
                    st.session_state.siren_results = res

        if st.session_state.siren_results is not None:
            df = st.session_state.siren_results
            df['label'] = df.apply(lambda
                                       r: f"{'[SIÈGE] ' if r['etablissementsiege'] else ''}{r['denominationunitelegale']} - {r['adresse']}",
                                   axis=1)
            sel = st.selectbox("Choisir établissement :", df['label'], key="select_siret_from_siren")
            if sel:
                st.session_state.siret_info = df[df['label'] == sel].iloc[0].to_dict()

        if st.session_state.siret_info:
            resultat["source"] = "SIRET/SIREN"
            resultat["valeur"] = st.session_state.siret_info

    # --- MODE D'ANALYSE ---
    st.markdown("**Mode d'analyse :**")
    mode = st.radio("", ["Point seul", "Isochrones", "Cercle d'influence"], horizontal=True,
                    label_visibility="collapsed", key="mode_analyse_main")
    resultat["mode"] = mode

    if mode == "Cercle d'influence":
        # CORRECTION ICI : Slider en KM pour l'UX, conversion en Mètres pour le backend
        radius_km = st.slider("Rayon (km)", 0.1, 5.0, 1.0, 0.1, key="poi_radius_slider")
        resultat["radius"] = int(radius_km * 1000)

    return resultat

def interface_enrichissement_fichier():
    """Interface upload enrichissement (Page 03)."""
    st.subheader("Enrichir un fichier local")
    uploaded_file = st.file_uploader("Chargez votre fichier CSV", type=["csv"])
    if uploaded_file:
        try:
            df_preview = pd.read_csv(uploaded_file, nrows=5, sep=None, engine='python')
            uploaded_file.seek(0)
            c1, c2 = st.columns(2)
            col_id = c1.selectbox("Colonne Identifiant :", df_preview.columns)
            typ = c2.radio("Type :", ["SIRET (14)", "SIREN (9)"])
            siege = st.checkbox("Sièges uniquement ?", value=True) if "SIREN" in typ else False

            if st.button("Lancer"):
                with st.spinner("Lecture..."):
                    df = pd.read_csv(uploaded_file, dtype={col_id: str}, sep=None, engine='python')
                return df, col_id, "siret" if "SIRET" in typ else "siren", siege
        except Exception as e:
            st.error(f"Erreur : {e}")
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

    with st.expander(f"Aperçu ({len(df)} lignes)"):
        st.dataframe(df.head(50))

    st.download_button(f"📥 Télécharger {nom_fichier_csv}", convertir_df_en_csv(df), nom_fichier_csv, "text/csv")