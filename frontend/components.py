# Fichier: frontend/components.py (Correction UX Sidebar & Filtre Bâtiments)

import streamlit as st
import pandas as pd
import geopandas as gpd
from config import POI_CONFIG
from utils.geo_tools import transfo_geodataframe, geocoder_adresse_nominatim
from backend.queries_siren import get_etablissement_par_siret

# --- CONFIGURATION DES INDICATEURS SOCIO (Conservée) ---
INDICATEURS_CONFIG = {
    "revenu_median": {"display": "Revenu médian (€)", "raw": "Revenu_median", "pct": None},
    "taux_pauvrete": {"display": "Taux de pauvreté (%)", "raw": "Taux_pauvrete", "pct": None},
    "population_totale": {"display": "Population totale", "raw": "Population_totale", "pct": None},
    "pop_25_54": {"display": "Actifs (25-54 ans)", "raw": "Pop_25_54_ans", "pct": "Part_actifs_25_54_ans_pct"},
    "cadres": {"display": "Ménages - Cadres (CSP3)", "raw": "Menages_cadres_prof_intelectuelles_CS3",
               "pct": "Part_cadres_CS3_pct"},
}

# --- CRITIQUE : DÉFINITION GLOBALE DES RISQUES (FIX DES SYMBOLES) ---
RISQUES_SEMANTIQUE = {
    "Inondation": {"symbole": "🌊", "clef_gdf": "inondation"},
    "Sécheresse (RGA)": {"symbole": "☀️", "clef_gdf": "secheresse"},
}


# =============================================================================
# A. LOGIQUE GÉOGRAPHIQUE DE BASE (HELPER INTERNE)
# =============================================================================

def _filtre_geo_base(df_communes, key_suffix):
    """
    Helper pour la sélection Région/Département.
    """
    regions_filtrees = []
    departements_labels = []
    departements_codes = []

    st.caption("Sélection de la maille :")

    mode = st.radio(
        "Maille géographique :",
        ["Région", "Département"],
        horizontal=True,
        key=f"mode_geo_risk_{key_suffix}",
        label_visibility="collapsed"
    )

    if mode == "Région":
        regions = sorted(df_communes['Nom_Region'].unique())
        regions_filtrees = st.multiselect(
            "Sélectionner Région(s) :",
            regions,
            key=f"reg_risk_{key_suffix}"
        )
    else:
        df_deps = df_communes[['Num_Dep', 'Nom_Dep']].copy().dropna().drop_duplicates('Num_Dep')
        df_deps['sort_key'] = df_deps['Num_Dep'].apply(lambda x: str(x).zfill(2) if str(x).isdigit() else x)
        df_deps = df_deps.sort_values('sort_key')
        df_deps['label'] = df_deps['Num_Dep'].astype(str).str.zfill(2) + " - " + df_deps['Nom_Dep'].str.upper()

        departements_labels = st.multiselect(
            "Sélectionner Département(s) :",
            df_deps['label'].tolist(),
            key=f"dep_risk_{key_suffix}"
        )
        departements_codes = [s.split(' - ')[0] for s in departements_labels]

    return regions_filtrees, departements_labels, departements_codes


# =============================================================================
# B. COMPOSANTS SIDEBAR (PAGES)
# =============================================================================

def sidebar_filtres_socio(dict_geodatas):
    """
    Sélecteur pour la couche socio-démographique (Titre de section déplacé).
    """
    # Titre de section déplacé pour la clarté UX
    options = ["Aucun"] + [v['display'] for v in INDICATEURS_CONFIG.values()]
    choix = st.selectbox("Indicateur Socio :", options, index=0, key="sel_socio_main_interface")

    if choix == "Aucun":
        return None, None, None, None

    config = next(c for c in INDICATEURS_CONFIG.values() if c['display'] == choix)
    colonne, label = config['raw'], config['display']

    maille = "IRIS"
    gdf = dict_geodatas.get(maille)

    return gdf, colonne, label, maille


def sidebar_filtres_poi():
    """
    Sélecteur pour les POI.
    """
    # st.markdown("### 2. 📍 Points d'Intérêt")
    return st.multiselect(
        "Points d'Intérêt :",
        options=list(POI_CONFIG.keys()),
        default=[],
        placeholder="Ex: Écoles, Gares...",
        key="sel_poi_main_interface"
    )


def sidebar_filtres_batiments():
    """
    Filtre des bâtiments pour l'audit.
    CORRECTION : Valeurs par défaut entre 100 et 3000 m².
    """
    st.markdown("#### Audit Bâtimentaire")
    show = st.toggle("Activer l'Audit Bâtimentaire (OSM)", value=False, key="show_batiments_audit")
    if show:
        # CRITIQUE : Démarrage par défaut à 100m² min et 3000m² max
        c1, c2 = st.columns(2)
        surface_min = c1.number_input("Min m²", 0, 10000, 100, step=10, key="surf_min_bat")
        surface_max = c2.number_input("Max m²", 0, 100000, 150, step=10, key="surf_max_bat")
    else:
        # Renvoyer les valeurs par défaut
        surface_min, surface_max = 100, 150
    return show, surface_min, surface_max


def sidebar_filtres_risques(df_communes, nom_risque=None, gdf_risque=None):
    """
    Fonction unique de filtrage Geo/Risque.
    Amélioration V2 : Multiselect pour le choix des risques et Expander pour la zone géo.
    """
    is_page_02_context = (nom_risque is not None and gdf_risque is not None)

    if is_page_02_context:
        # --- CAS 1 : CONTEXTE PAGE 02 (IMPLANTATION) ---
        emoji = "🌊" if "Inondation" in nom_risque else "☀️" if "Sécheresse" in nom_risque else "🌪️"
        titre = f"#### {emoji} {nom_risque}"

        st.markdown(titre)
        show = st.checkbox(f"Afficher {nom_risque}", value=False, key=f"show_risk_{nom_risque}")

        regions_filtrees, departements_labels = [], []

        if show:
            # On range le filtre géographique dans un expander pour ne pas polluer
            with st.expander(f"📍 Filtrer la zone ({nom_risque})", expanded=False):
                regions_filtrees, departements_labels, _ = _filtre_geo_base(df_communes, nom_risque)

        return show, regions_filtrees, departements_labels

    else:
        # --- CAS 2 : CONTEXTE PAGE 01 (CONCURRENCE) ---
        st.markdown("### 🌪️ Calques Risques")

        show = st.checkbox("Activer les Risques", value=False, key="show_risk_general")

        regions_filtrees, departements_codes = [], []
        types_selectionnes = []

        if show:
            # 1. Le Multiselect permet de choisir vraiment ce qu'on veut voir
            types_selectionnes = st.multiselect(
                "Types de risques :",
                options=["Inondation", "Sécheresse (RGA)"],
                default=["Inondation", "Sécheresse (RGA)"], # Par défaut les deux
                key="type_risk_p01_select"
            )

            # 2. Zone géographique rangée dans un expander propre
            with st.expander("🌍 Restreindre la zone (Optionnel)", expanded=False):
                st.caption("Filtrer les risques par région/département :")
                regions_filtrees, _, departements_codes = _filtre_geo_base(df_communes, "general")

        return show, types_selectionnes, regions_filtrees, departements_codes


def sidebar_filtres_reseau():
    """Filtres pour l'analyse de cannibalisation/réseau."""
    mode_cannibale = st.toggle("Activer Analyse Réseau", value=False, key="toggle_cannibale")
    gdf_reseau_client = gpd.GeoDataFrame()
    nom_enseigne_reseau = ""
    rayon_search = 15
    source_reseau = "Base de Données (SIRENE)"  # Par défaut

    if mode_cannibale:
        st.markdown("### Cannibalisation / Réseau")

        source_reseau = st.radio("Source des points de vente :",
                                 ["Base de Données (SIRENE)", "Fichier Client (CSV/Excel)"],
                                 horizontal=True)

        if "Fichier Client" in source_reseau:
            uploaded_reseau = st.file_uploader("Fichier Réseau (CSV/Excel)", type=["csv", "xlsx"],
                                               key="upload_reseau_cannibale")

            if uploaded_reseau:
                try:
                    df_res = pd.read_csv(uploaded_reseau) if uploaded_reseau.name.endswith('.csv') else pd.read_excel(
                        uploaded_reseau)

                    lat_col = next((c for c in df_res.columns if 'lat' in c.lower()), None)
                    lon_col = next((c for c in df_res.columns if 'lon' in c.lower()), None)

                    if lat_col and lon_col:
                        gdf_reseau_client = transfo_geodataframe(df_res, lon_col, lat_col)
                        st.success(f"✅ {len(gdf_reseau_client)} points de réseau chargés")
                    else:
                        st.error("❌ Colonnes 'lat' ou 'lon' introuvables.")
                except Exception as e:
                    st.error(f"❌ Erreur de lecture du fichier : {e}")

        else:  # Mode BDD SIRENE
            nom_enseigne_reseau = st.text_input("Nom de l'enseigne à exclure :", placeholder="Ex: Auchan, Sephora...",
                                                key="txt_enseigne_cannibale")
            rayon_search = st.number_input("Rayon de recherche (km)", 1, 100, 15, key="rayon_bdd_cannibale")

    return mode_cannibale, gdf_reseau_client, nom_enseigne_reseau, rayon_search


# =============================================================================
# C. POINT CENTRAL & GÉOCODAGE
# =============================================================================

def selection_point_central(engine):
    """
    Interface définition zone (Adresse / Coords / SIRET).
    """
    st.markdown("---")
    st.subheader("Définir une zone d'implantation")

    if 'poi_selection_resultat' not in st.session_state:
        st.session_state['poi_selection_resultat'] = {
            "source": None, "valeur": None, "mode": "Point seul", "radius": 1000
        }

    resultat = st.session_state['poi_selection_resultat']

    if 'siren_results_comp' not in st.session_state: st.session_state.siren_results_comp = None
    if 'siret_info_comp' not in st.session_state: st.session_state.siret_info_comp = None

    source_choix = st.radio(
        "Source d'identification:",
        ["Adresse", "Coordonnées", "SIRET"],
        horizontal=True,
        key="poi_source_choix",
        label_visibility="collapsed",
        on_change=lambda: st.session_state.update(
            siren_results_comp=None,
            siret_info_comp=None,
            poi_selection_resultat={"source": None, "valeur": None, "mode": "Point seul", "radius": 1000}
        )
    )
    resultat["source"] = source_choix

    current_inp = st.session_state.get("poi_siren_siret", "")

    if source_choix == "Adresse":
        val = st.text_input("Adresse :", placeholder="Ex: 8 Rue de Londres, 75009 Paris", key="poi_adresse")
        if st.button("Géocoder", key="btn_geocode_addr"):
            if val:
                with st.spinner("Géocodage..."):
                    res = geocoder_adresse_nominatim(val)

                    if res:
                        st.success(f"Trouvé : {res.get('adresse', 'Point trouvé')[:50]}...")
                        resultat["valeur"] = res
                    else:
                        st.warning(f"Adresse introuvable : {val}")

    elif source_choix == "Coordonnées":
        c1, c2 = st.columns(2)
        lat = c1.number_input("Latitude :", value=48.85, format="%.4f", key="poi_lat")
        lon = c2.number_input("Longitude :", value=2.35, format="%.4f", key="poi_lon")

        resultat["valeur"] = {
            "latitude": lat, "longitude": lon,
            "denominationunitelegale": "Coordonnées manuelles",
            "adresse": f"Lat: {lat}, Lon: {lon}"
        }

    elif source_choix == "SIREN/SIRET":
        inp = st.text_input("SIREN/SIRET :", placeholder="383597342...", key="poi_siren_siret", value=current_inp)

        if st.button("Rechercher SIRET", key="btn_search_siret"):
            if inp:
                siret_clean = inp.strip().replace(" ", "")
                if len(siret_clean) == 14:
                    etab = get_etablissement_par_siret(engine, siret_clean)
                    if etab and etab.get('latitude') and etab.get('longitude'):
                        st.success(f"Trouvé : {etab.get('denominationunitelegale')}")
                        st.session_state.siret_info_comp = etab
                        st.session_state.siren_results_comp = None
                        resultat["valeur"] = etab
                    else:
                        st.warning("SIRET trouvé, mais coordonnées GPS manquantes ou invalides.")

                elif len(siret_clean) == 9:
                    st.warning(
                        "Pour un SIREN (9 chiffres), veuillez utiliser l'outil Concurrence (Page 01) ou Enrichissement (Page 04).")

        if st.session_state.siret_info_comp:
            resultat["valeur"] = st.session_state.siret_info_comp

    st.markdown("**Mode d'analyse :**")
    mode = st.radio(
        "Mode d'analyse zone:",
        ["Point seul", "Isochrones", "Cercle d'influence"],
        horizontal=True,
        label_visibility="collapsed",
        key="mode_analyse_main",
        # Gestion de l'index par défaut selon le state
        index=["Point seul", "Isochrones", "Cercle d'influence"].index(resultat["mode"])
        if resultat["mode"] in ["Point seul", "Isochrones", "Cercle d'influence"] else 0
    )
    resultat["mode"] = mode

    if mode == "Isochrones":
        # CORRECTION : Défaut 5 min au lieu de 10
        temps_min = st.slider("Temps (min)", 1, 30, 5, 1, key="poi_iso_slider")
        # On stocke en secondes pour l'API (5 * 60 = 300s)
        # Note: L'API attend des secondes, mais on stocke ici le paramètre brut si besoin,
        # c'est la page 02 qui fait la conversion x60.
        # ATTENTION : La page 02 utilise calcule_isochrone_api(..., 600).
        # On va devoir passer cette valeur dynamique.
        resultat["radius"] = temps_min * 60

    elif mode == "Cercle d'influence":
        radius_km = st.slider("Rayon (km)", 0.1, 5.0, resultat["radius"] / 1000 if resultat["radius"] else 1.0, 0.1,
                              key="poi_radius_slider")
        resultat["radius"] = int(radius_km * 1000)

    st.session_state['poi_selection_resultat'] = resultat

    return resultat


def render_selection_territoire_compact(df_communes, key_suffix=""):
    """
    Restaure la fonction de sélection géographique compacte (utilisée dans la page Concurrence/Recherche - P01).
    """
    st.markdown("**Zone de Recherche**")

    # Mode : Département ou Commune (pas Région dans ce filtre P01)
    mode = st.radio("Maille :", ["Département", "Commune"], horizontal=True, label_visibility="collapsed",
                    key=f"mode_terr_{key_suffix}")

    # Préparation et tri des départements
    df_deps = df_communes[['Num_Dep', 'Nom_Dep']].drop_duplicates().dropna(subset=['Num_Dep'])
    df_deps['sort_key'] = df_deps['Num_Dep'].astype(str).str.zfill(2)
    df_deps = df_deps.sort_values('sort_key')
    df_deps['label'] = df_deps['sort_key'] + " - " + df_deps['Nom_Dep'].str.upper()

    # Sélection des Départements
    sel_deps = st.multiselect("Département(s)", df_deps['label'], key=f"sel_deps_{key_suffix}")

    nums_deps = []
    if sel_deps:
        # Récupération des codes départementaux (XXX - Nom)
        nums_deps = df_deps[df_deps['label'].isin(sel_deps)]['Num_Dep'].tolist()

    data_communes = pd.DataFrame()
    if nums_deps:
        # Filtrage des communes correspondant aux départements sélectionnés
        data_communes = df_communes[df_communes['Num_Dep'].isin(nums_deps)]

    # Si le mode est "Commune", on offre la sélection des villes dans les départements choisis
    if mode == "Commune" and not data_communes.empty:
        # Tri et sélection des villes
        sel_villes = st.multiselect("Communes spécifiques", sorted(data_communes['Nom_Ville'].unique()),
                                    key=f"sel_villes_{key_suffix}")
        if sel_villes:
            # Filtre final par les communes sélectionnées
            data_communes = data_communes[data_communes['Nom_Ville'].isin(sel_villes)]
        else:
            # Si mode Commune est choisi mais aucune commune sélectionnée, on retourne vide.
            data_communes = pd.DataFrame()

            # Retourne le mode (Département/Commune), les codes départements sélectionnés, et le DataFrame des communes filtrées
    return {"mode": mode, "nums_deps": nums_deps, "data_communes": data_communes}