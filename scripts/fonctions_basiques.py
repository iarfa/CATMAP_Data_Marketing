# ==============================================
# 📦 Imports & Librairies
# ==============================================
import pandas as pd
import streamlit as st
import numpy as np
import geopandas as gpd

# ==============================================
# Section chargement des données
# ==============================================

@st.cache_data(show_spinner=False)
def charger_etablissements(path_etablissement):
    """Charge les données des établissements depuis un fichier Parquet."""
    try:
        return pd.read_parquet(path_etablissement)
    except FileNotFoundError:
        st.error(f"Fichier des établissements introuvable : {path_etablissement}")
        return pd.DataFrame()

@st.cache_data(show_spinner=False)
def charger_centres_departements(path_centres_dpt):
    """Charge les données des centres de départements depuis un fichier Excel."""
    try:
        return pd.read_excel(path_centres_dpt)
    except FileNotFoundError:
        st.error(f"Fichier des centres de départements introuvable : {path_centres_dpt}")
        return pd.DataFrame()

@st.cache_data(show_spinner=False)
def charger_communes(path_communes):
    """Charge les données des communes depuis un fichier Excel."""
    try:
        df = pd.read_excel(path_communes)
        if 'Num_Dep' in df.columns:
            df['Num_Dep'] = df['Num_Dep'].astype(str)
        else:
            st.error("La colonne 'Num_Dep' est manquante dans le fichier des communes.")
            return pd.DataFrame()
        return df
    except FileNotFoundError:
        st.error(f"Fichier des communes introuvable : {path_communes}")
        return pd.DataFrame()

@st.cache_data(show_spinner=False)
def charger_donnees_iris_socio(path_iris_socio):
    """Charge le GeoDataFrame des données IRIS depuis un fichier Parquet."""
    try:
        return gpd.read_parquet(path_iris_socio)
    except FileNotFoundError:
        st.error(f"Fichier de données socio-économiques introuvable au chemin : {path_iris_socio}")
        return None

@st.cache_data(show_spinner=False)
def charger_coefficients_trafic(path_coeff_trafic):
    """Charge la table des coefficients de trafic par ville."""
    try:
        return pd.read_excel(path_coeff_trafic)
    except FileNotFoundError:
        st.warning(f"Fichier des coefficients de trafic introuvable : {path_coeff_trafic}. Le trafic ne sera pas simulé.")
        return pd.DataFrame(columns=['ville', 'coefficient'])

@st.cache_data(show_spinner="Chargement des zones inondables...")
def charger_zones_inondables(path_parquet):
    """
    Charge les données optimisées des zones inondables depuis un fichier Parquet,
    en spécifiant explicitement le moteur de lecture.
    """
    try:
        gdf = gpd.read_parquet(path_parquet)
        return gdf
    except Exception as e:
        st.warning(f"Fichier des zones inondables introuvable ou illisible : {e}. La fonctionnalité sera désactivée.")
        return gpd.GeoDataFrame()

@st.cache_data(show_spinner="Chargement des données de sécheresse (RGA)...")
def charger_donnees_rga(path_parquet):
    """
    Charge les données optimisées sur le risque de sécheresse (RGA) depuis un fichier Parquet.
    """
    try:
        gdf = gpd.read_parquet(path_parquet)
        return gdf
    except Exception as e:
        st.warning(f"Fichier des données RGA introuvable ou illisible : {e}. La fonctionnalité sera désactivée.")
        return gpd.GeoDataFrame()

# ==============================================
# Fonctions pour la page INSEE (INCHANGÉES)
# ==============================================

def filtrer_donnees(data, categories, villes):
    """
    Filtre le DataFrame des établissements en fonction des catégories et des villes sélectionnées.

    Args:
        data (pd.DataFrame): Le DataFrame source.
        categories (list): La liste des catégories (Intitules_NAF_VF) à conserver.
        villes (list): La liste des villes (libelleCommuneEtablissement) à conserver.

    Returns:
        pd.DataFrame: Le DataFrame filtré.
    """
    # Si les listes de filtres sont fournies mais vides, cela signifie que l'utilisateur n'a rien sélectionné
    # et qu'on ne doit rien afficher. Si les listes ne sont pas fournies (None), on n'applique pas de filtre.
    if categories is not None and not categories:
        return pd.DataFrame(columns=data.columns)
    if villes is not None and not villes:
        return pd.DataFrame(columns=data.columns)

    # Crée des conditions de filtrage dynamiques
    condition_categorie = data["Intitules_NAF_VF"].isin(categories) if categories else pd.Series(True, index=data.index)
    condition_ville = data["libelleCommuneEtablissement"].isin(villes) if villes else pd.Series(True, index=data.index)

    # Applique les filtres et réinitialise l'index
    data_filtree = data[condition_categorie & condition_ville].reset_index(drop=True)

    return data_filtree

# ==============================================
# Fonctions pour la page OSM (OPTIMISÉES)
# ==============================================

def extraction_adresse_OSM(ligne_etab):
    """Extrait une adresse simplifiée et définit une précision de géocodage pour la sortie OSM."""
    adresse_ini = ligne_etab["adresse"].split(", ")
    if adresse_ini[0].isdigit():
        adresse_simp = ", ".join(adresse_ini[:4])
        precision_geocodage = "numero"
    else:
        adresse_simp = ", ".join(adresse_ini[:3])
        precision_geocodage = "voie"
    return pd.Series([adresse_simp, precision_geocodage])

def choix_centre_OSM(data):
    """Laisse à l'utilisateur le choix de la ville pour centrer la carte."""
    centre_ville = data.groupby("ville").first().reset_index()[["ville", "latitude", "longitude"]]
    centre_ville_utilisateur = st.selectbox("Choisissez une ville pour le centre de votre carte", centre_ville["ville"])
    coordonnees_centre = centre_ville[centre_ville["ville"] == centre_ville_utilisateur]
    lon_centre = coordonnees_centre["longitude"].iloc[0]
    lat_centre = coordonnees_centre["latitude"].iloc[0]
    return lat_centre, lon_centre


@st.cache_data(show_spinner=False)
def preparer_donnees_socio(_df_iris_base, _df_communes_france):
    """
    Nettoie, enrichit, simplifie et prépare les données socio-économiques en gérant
    les données partielles et les populations nulles.
    """
    df = _df_iris_base.copy()
    try:
        df['geometry'] = df['geometry'].simplify(tolerance=100, preserve_topology=True)
    except Exception as e:
        st.warning(f"Avertissement lors de la simplification des géométries : {e}")

    df_ref_deps = _df_communes_france[['Num_Dep', 'Nom_Dep']].drop_duplicates()
    df_ref_deps['Num_Dep'] = df_ref_deps['Num_Dep'].astype(str).str.zfill(2)

    df['CODE_COM'] = df['IRIS'].str.slice(0, 5)
    df['CODE_DEPT'] = df['IRIS'].str.slice(0, 2)

    stats_communes = df.groupby('CODE_COM')['Nb_menages_total'].agg(['size', 'count']).reset_index()
    stats_communes['incomplet'] = (stats_communes['size'] - stats_communes['count']) > stats_communes['count']
    communes_incompletes = stats_communes[stats_communes['incomplet']]['CODE_COM'].tolist()

    cols_a_vider = [
        'Nb_menages_total', 'Pop_15_24_ans', 'Pop_25_54_ans', 'Pop_55_79_ans', 'Pop_80_ans_plus',
        'Nb_menages_sans_famille', 'Nb_menages_famille', 'Menages_couple_sans_enfant',
        'Menages_couple_avec_enfant', 'Menages_monoparental', 'Menages_agriculteurs_CS1',
        'Menages_artisans_commercants_CS2', 'Menages_cadres_prof_intelectuelles_CS3',
        'Menages_prof_intermediaires_CS4', 'Menages_employes_CS5', 'Menages_ouvriers_CS6',
        'Menages_retraites_CS7', 'Menages_autres_sans_act_pro_CS8',
        'Taux_pauvrete', 'Revenu_median'
    ]

    if communes_incompletes:
        #st.info(f"{len(communes_incompletes)} communes avec données partielles ont été masquées (ex: {communes_incompletes[0]}).")
        df.loc[df['CODE_COM'].isin(communes_incompletes), cols_a_vider] = np.nan

    COLS_COMPTAGE = cols_a_vider[:-2]

    PROPORTIONS_POPULATION = {
        'Part_jeunes_15_24_ans_pct': 'Pop_15_24_ans', 'Part_actifs_25_54_ans_pct': 'Pop_25_54_ans',
        'Part_seniors_55_79_ans_pct': 'Pop_55_79_ans', 'Part_seniors_80_ans_plus_pct': 'Pop_80_ans_plus'
    }
    PROPORTIONS_MENAGES = {
        'Part_menages_monoparentaux_pct': 'Menages_monoparental',
        'Part_agriculteurs_CS1_pct': 'Menages_agriculteurs_CS1',
        'Part_artisans_commercants_CS2_pct': 'Menages_artisans_commercants_CS2',
        'Part_cadres_CS3_pct': 'Menages_cadres_prof_intelectuelles_CS3',
        'Part_prof_intermediaires_CS4_pct': 'Menages_prof_intermediaires_CS4',
        'Part_employes_CS5_pct': 'Menages_employes_CS5',
        'Part_ouvriers_CS6_pct': 'Menages_ouvriers_CS6', 'Part_retraites_CS7_pct': 'Menages_retraites_CS7',
        'Part_autres_CS8_pct': 'Menages_autres_sans_act_pro_CS8'
    }

    for col in COLS_COMPTAGE:
        if col in df.columns:
            df[col] = df[col].fillna(0).round(0).astype(int)

    df['Population_totale'] = df[['Pop_15_24_ans', 'Pop_25_54_ans', 'Pop_55_79_ans', 'Pop_80_ans_plus']].sum(axis=1)
    pop_total_safe = df['Population_totale'].replace(0, np.nan)
    menages_total_safe = df['Nb_menages_total'].replace(0, np.nan)

    for new_col, source_col in PROPORTIONS_POPULATION.items():
        df[new_col] = (df[source_col] / pop_total_safe * 100)
    for new_col, source_col in PROPORTIONS_MENAGES.items():
        df[new_col] = (df[source_col] / menages_total_safe * 100)

    df = df.merge(df_ref_deps, left_on='CODE_DEPT', right_on='Num_Dep', how='left')
    df.drop(columns=['Num_Dep'], inplace=True, errors='ignore')

    agg_funcs = {
        'NOM_COM': 'first', 'Nom_Dep': 'first', 'Taux_pauvrete': 'mean', 'Revenu_median': 'mean',
        'Population_totale': 'sum', **{col: 'sum' for col in COLS_COMPTAGE}
    }

    df_commune = df.dissolve(by='CODE_COM', aggfunc=agg_funcs, as_index=False)
    df_commune['CODE_DEPT'] = df_commune['CODE_COM'].str.slice(0, 2)
    df_departement = df_commune.dissolve(by='CODE_DEPT', aggfunc=agg_funcs, as_index=False)
    df_departement['NOM_COM'] = df_departement['Nom_Dep']

    for dframe in [df_commune, df_departement]:
        pop_total_safe = dframe['Population_totale'].replace(0, np.nan)
        menages_total_safe = dframe['Nb_menages_total'].replace(0, np.nan)
        for new_col, source_col in PROPORTIONS_POPULATION.items():
            dframe[new_col] = (dframe[source_col] / pop_total_safe * 100)
        for new_col, source_col in PROPORTIONS_MENAGES.items():
            dframe[new_col] = (dframe[source_col] / menages_total_safe * 100)
        if 'Revenu_median' in dframe.columns: dframe['Revenu_median'] = dframe['Revenu_median'].round(0)
        if 'Taux_pauvrete' in dframe.columns: dframe['Taux_pauvrete'] = dframe['Taux_pauvrete'].round(1)
        proportion_cols = list(PROPORTIONS_POPULATION.keys()) + list(PROPORTIONS_MENAGES.keys())
        for col in proportion_cols:
            if col in dframe.columns: dframe[col] = dframe[col].round(1)

    ### RÈGLE FINALE : TRAITER LES POPULATIONS NULLES COMME "ND" ###
    # On ajoute la colonne 'Population_totale' à la liste des colonnes à vider si ce n'est pas déjà fait.
    cols_a_vider_final = cols_a_vider + ['Population_totale']
    # On s'assure qu'il n'y a pas de doublons
    cols_a_vider_final = list(set(cols_a_vider_final))

    for dframe in [df_commune, df_departement]:
        # On identifie les lignes où la population totale est nulle
        lignes_a_modifier = dframe['Population_totale'] == 0

        # Pour ces lignes, on met toutes les colonnes d'indicateurs à NaN
        # pour qu'elles apparaissent comme "ND" sur la carte et dans les tooltips.
        if lignes_a_modifier.any():
            colonnes_presentes = [col for col in cols_a_vider_final if col in dframe.columns]
            dframe.loc[lignes_a_modifier, colonnes_presentes] = np.nan

    return {"IRIS": df, "Commune": df_commune, "Département": df_departement}



def enrichir_donnees_risques_avec_num_dep(gdf_risques, df_communes):
    """
    Enrichit un GeoDataFrame de risques (inondation, RGA, etc.) avec le numéro de département.
    La jointure est faite sur le nom du département, en normalisant le texte pour plus de robustesse.

    Args:
        gdf_risques (gpd.GeoDataFrame): Données de risque avec la colonne 'NOM_DEP'.
        df_communes (pd.DataFrame): Données de référence des communes avec 'Num_Dep' et 'Nom_Dep'.

    Returns:
        gpd.GeoDataFrame: Le GeoDataFrame de risque enrichi avec la colonne 'Num_Dep'.
    """
    # Vérification de la présence des colonnes nécessaires
    if 'NOM_DEP' not in gdf_risques.columns:
        st.warning("La colonne 'NOM_DEP' est manquante dans les données de risque. Impossible d'enrichir.")
        return gdf_risques
    if gdf_risques.empty:
        return gdf_risques

    # 1. Préparer la table de référence : Num_Dep et Nom_Dep uniques
    df_ref_deps = df_communes[['Num_Dep', 'Nom_Dep']].copy().drop_duplicates('Nom_Dep')

    # 2. Normaliser les noms de département pour assurer une jointure fiable
    # On met tout en majuscules et on enlève les tirets, des deux côtés.
    df_ref_deps['join_key'] = df_ref_deps['Nom_Dep'].str.upper().str.replace('-', ' ')
    gdf_risques['join_key'] = gdf_risques['NOM_DEP'].str.upper().str.replace('-', ' ')

    # 3. Effectuer la jointure pour ajouter 'Num_Dep'
    gdf_enrichi = gdf_risques.merge(
        df_ref_deps[['Num_Dep', 'join_key']],
        on='join_key',
        how='left'
    )

    # 4. Nettoyer les colonnes temporaires
    gdf_enrichi = gdf_enrichi.drop(columns=['join_key'])

    # S'assurer que le Num_Dep est bien un string formaté
    if 'Num_Dep' in gdf_enrichi.columns:
        gdf_enrichi['Num_Dep'] = gdf_enrichi['Num_Dep'].astype(str).str.zfill(2)

    return gdf_enrichi