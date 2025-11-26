# ==============================================
# 📦 Imports & Librairies
# ==============================================
import pandas as pd
import streamlit as st
import numpy as np
import geopandas as gpd
import sqlalchemy
import re


# ==============================================
# SECTION : CONNEXION BASE DE DONNÉES
# ==============================================

@st.cache_resource(show_spinner="Connexion à la base de données SIREN...")
def connect_to_db():
    """
    Crée et met en cache un moteur de connexion SQLAlchemy vers la BDD PostGIS.
    """
    try:
        db_user = st.secrets["DB_USER"]
        db_pass = st.secrets["DB_PASS"]
        db_host = st.secrets["DB_HOST"]
        db_port = st.secrets["DB_PORT"]
        db_name = st.secrets["DB_NAME"]

        db_uri = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        engine = sqlalchemy.create_engine(db_uri)

        with engine.connect() as conn:
            pass

        print("Connexion à la base de données SIREN réussie.")
        return engine

    except Exception as e:
        st.error(f"Erreur de connexion à la base de données SIREN : {e}")
        st.warning(
            "Vérifiez vos secrets (DB_USER, DB_PASS...) et que le conteneur Docker 'bdd_sirene_postgis' est bien lancé.")
        return None


# ==================================================================
# MODIFIÉ : Logique de recherche SIRET (P1, P2)
# ==================================================================

@st.cache_data(show_spinner="Recherche du SIRET dans la base de données...")
def find_etablissement_by_siret(_engine, siret):
    """
    Interroge la BDD locale pour trouver un établissement par son SIRET.
    Retourne un dictionnaire de résultats ou None.
    """
    if not _engine:
        st.error("Connexion à la base de données échouée.")
        return None

    siret = str(siret).strip().replace(" ", "")
    if not siret.isdigit() or len(siret) != 14:
        st.warning("SIRET invalide. Veuillez entrer un numéro à 14 chiffres.", icon="⚠️")
        return None

    # MODIFIÉ (P1) : Requête corrigée, on prend tout
    query = sqlalchemy.text("""
        SELECT * FROM etablissements
        WHERE siret = :siret
        LIMIT 1;
    """)
    params = {"siret": siret}

    try:
        with _engine.connect() as conn:
            result = conn.execute(query, params).fetchone()

        if result:
            # MODIFIÉ (P2) : On retourne le dict complet
            return dict(result._mapping)
        else:
            st.warning(f"SIRET {siret} non trouvé.", icon="⚠️")
            return None

    except Exception as e:
        st.error(f"Erreur lors de la requête SIRET : {e}")
        return None


@st.cache_data(show_spinner="Recherche du SIREN dans la base de données...")
def find_etablissements_by_siren(_engine, siren):
    """
    Interroge la BDD locale pour trouver TOUS les établissements d'un SIREN.
    Retourne un DataFrame s'il y en a plusieurs,
    ou un dict s'il est unique.
    """
    if not _engine:
        st.error("Connexion à la base de données échouée.")
        return None

    siren = str(siren).strip().replace(" ", "")
    if not siren.isdigit() or len(siren) != 9:
        st.warning("SIREN invalide. Veuillez entrer un numéro à 9 chiffres.", icon="⚠️")
        return None

    # MODIFIÉ (P1) : Requête corrigée, on prend tout
    query = sqlalchemy.text("""
        SELECT *
        FROM etablissements
        WHERE siren = :siren;
    """)
    params = {"siren": siren}

    try:
        with _engine.connect() as conn:
            results_df = pd.read_sql_query(query, conn, params=params)

        if results_df.empty:
            st.warning(f"SIREN {siren} non trouvé.", icon="⚠️")
            return None

        # MODIFIÉ (P2) : On retourne un dict si une seule ligne
        if len(results_df) == 1:
            return results_df.iloc[0].to_dict()

        st.warning(f"Ce SIREN possède {len(results_df)} établissements. Veuillez en choisir un.")
        return results_df

    except Exception as e:
        st.error(f"Erreur lors de la requête SIREN : {e}")
        return None


# ==================================================================
# Logique d'enrichissement de fichier (Goal 2 / P6)
# ==================================================================

@st.cache_data(show_spinner="Enrichissement du fichier en cours (requête BDD)...")
def enrichir_dataframe_siren(_engine, df, colonne_id, type_identifiant, only_siege=True):
    """
    Enrichit un DataFrame.
    CORRIGÉ : Suppression des colonnes 'codepostaletablissement' et 'libellecommuneetablissement'
    qui n'existent plus dans la nouvelle structure de base.
    """
    if not _engine:
        st.error("Connexion à la base de données échouée.")
        return df, pd.DataFrame(), pd.DataFrame()

    # 1. Nettoyage préliminaire
    try:
        df['clean_id'] = df[colonne_id].astype(str).str.replace(' ', '', regex=False).str.replace('.', '',
                                                                                                  regex=False).str.strip()
        df['clean_id'] = df['clean_id'].apply(lambda x: x[:-2] if x.endswith('.0') else x)
    except KeyError:
        st.error(f"Colonne '{colonne_id}' non trouvée dans le fichier.")
        return df, pd.DataFrame(), pd.DataFrame()

    # 2. Validation du format
    mask_valid = pd.Series([False] * len(df), index=df.index)

    if type_identifiant == "siret":
        mask_valid = (df['clean_id'].str.len() == 14) & (df['clean_id'].str.isdigit())

        # MODIFIÉ : Suppression des colonnes inexistantes
        query_str = """
            SELECT 
                siret AS join_key,
                siren, denominationunitelegale, adresse, latitude, longitude,
                activiteprincipaleetablissement, intitules_naf_vf, numero_dep, nom_dep,
                etablissementsiege
            FROM etablissements WHERE siret IN :liste_ids
        """

    elif type_identifiant == "siren":
        mask_valid = (df['clean_id'].str.len() == 9) & (df['clean_id'].str.isdigit())

        clause_siege = "AND etablissementsiege = True" if only_siege else ""

        # MODIFIÉ : Suppression des colonnes inexistantes
        query_str = f"""
            SELECT 
                siren AS join_key,
                siret, denominationunitelegale, adresse, latitude, longitude,
                activiteprincipaleetablissement, intitules_naf_vf, numero_dep, nom_dep,
                etablissementsiege
            FROM etablissements 
            WHERE siren IN :liste_ids {clause_siege}
        """

    # --- DataFrame 3 : REJETS DE FORMAT ---
    df_rejet_format = df[~mask_valid].copy()
    if 'clean_id' in df_rejet_format.columns:
        df_rejet_format = df_rejet_format.drop(columns=['clean_id'])

    ids_valides_uniques = df.loc[mask_valid, 'clean_id'].unique().tolist()

    if not ids_valides_uniques:
        return pd.DataFrame(), pd.DataFrame(), df_rejet_format

    # 3. Exécution
    try:
        query = sqlalchemy.text(query_str)
        params = {"liste_ids": tuple(ids_valides_uniques)}
        with _engine.connect() as conn:
            resultats_df = pd.read_sql_query(query, conn, params=params)
    except Exception as e:
        st.error(f"Erreur SQL : {e}")
        return pd.DataFrame(), pd.DataFrame(), df_rejet_format

    # 4. Fusion
    df_valide_input = df[mask_valid].copy()

    df_merged = pd.merge(
        df_valide_input,
        resultats_df,
        left_on='clean_id',
        right_on='join_key',
        how='left'
    )

    cols_to_drop = ['join_key', 'clean_id']
    df_merged = df_merged.drop(columns=[c for c in cols_to_drop if c in df_merged.columns])

    # 5. Séparation
    mask_found = df_merged['denominationunitelegale'].notna()

    df_succes = df_merged[mask_found].copy()

    df_echec_not_found = df_merged[~mask_found].copy()
    cols_resultats = [c for c in resultats_df.columns if c != 'join_key']
    df_echec_not_found = df_echec_not_found.drop(columns=cols_resultats, errors='ignore')

    return df_succes, df_echec_not_found, df_rejet_format

# ==================================================================
# NOUVEAU : Logique de concurrence (Pour Goal 3 / P4)
# ==================================================================
@st.cache_data(show_spinner="Récupération des détails de l'établissement...")
def get_etab_details_for_concurrence(_engine, siret):
    """
    Trouve un SIRET et retourne ses infos clés.
    ADAPTÉ : Inclut latitude/longitude pour l'affichage du point de référence.
    """
    if not _engine:
        return None

    siret = str(siret).strip().replace(" ", "")
    if not siret.isdigit() or len(siret) != 14:
        st.warning("SIRET invalide. Veuillez entrer un numéro à 14 chiffres.", icon="⚠️")
        return None

    # MODIFIÉ : Ajout de 'latitude' et 'longitude'
    query = sqlalchemy.text("""
        SELECT 
            denominationunitelegale, 
            activiteprincipaleetablissement,
            intitules_naf_vf AS description_naf,
            adresse,
            numero_dep,
            nom_dep,
            latitude, 
            longitude
        FROM etablissements
        WHERE siret = :siret
        LIMIT 1;
    """)

    try:
        with _engine.connect() as conn:
            result = conn.execute(query, {"siret": siret}).fetchone()

        if result:
            return dict(result._mapping)
        else:
            st.warning(f"SIRET {siret} non trouvé.", icon="⚠️")
            return None
    except Exception as e:
        st.error(f"Erreur lors de la requête SIRET : {e}")
        return None

# Fonction utilitaire pour extraire la ville (à mettre en dehors ou dans find_concurrents)
def extraire_ville_depuis_adresse(adresse_str):
    if not isinstance(adresse_str, str):
        return "Ville Inconnue"
    # Cherche 5 chiffres (CP) et prend ce qui suit
    match = re.search(r'\b[0-9]{5}\b\s+(.*)', adresse_str)
    if match:
        return match.group(1).strip().upper()  # On met en majuscule pour comparer
    return "Ville Inconnue"

@st.cache_data(show_spinner="Recherche des concurrents...")
def find_concurrents(_engine, siret_origine, code_naf, scope, scope_value, ville_origine=None):
    """
    Trouve les concurrents.
    - scope : 'Département' ou 'Ville'
    - scope_value : Le numéro de département (toujours utilisé pour la requête SQL initiale)
    - ville_origine : Le nom de la ville cible (utilisé pour filtrer si scope == 'Ville')
    """
    if not _engine:
        return gpd.GeoDataFrame()

    siret_origine = str(siret_origine).strip()
    siren_origine = siret_origine[:9]

    # 1. Requête SQL : On tire toujours par département d'abord (c'est indexé, c'est rapide)
    query = sqlalchemy.text(f"""
        SELECT 
            siret, siren, denominationunitelegale, adresse,
            latitude, longitude, activiteprincipaleetablissement,
            intitules_naf_vf AS description_naf
        FROM etablissements
        WHERE 
            activiteprincipaleetablissement = :code_naf AND
            numero_dep = :num_dep AND
            siren != :siren_origine; 
    """)

    params = {
        "code_naf": code_naf,
        "num_dep": scope_value,  # scope_value doit être le num_dep
        "siren_origine": siren_origine
    }

    try:
        with _engine.connect() as conn:
            results_df = pd.read_sql_query(query, conn, params=params)

        if results_df.empty:
            st.info("Aucun concurrent trouvé dans ce département.")
            return gpd.GeoDataFrame()

        # 2. Enrichissement avec la colonne 'ville' via Regex
        results_df['ville'] = results_df['adresse'].apply(extraire_ville_depuis_adresse)

        # 3. Filtrage Python si scope == 'Ville'
        if scope == 'Ville' and ville_origine:
            # On ne garde que les lignes où la ville extraite correspond à la ville d'origine
            nb_avant = len(results_df)
            results_df = results_df[results_df['ville'] == ville_origine.upper()]

            if results_df.empty:
                st.info(
                    f"Des concurrents existent dans le département, mais aucun trouvé spécifiquement à {ville_origine}.")
                return gpd.GeoDataFrame()

        # 4. Conversion Géographique
        results_df['longitude'] = pd.to_numeric(results_df['longitude'], errors='coerce')
        results_df['latitude'] = pd.to_numeric(results_df['latitude'], errors='coerce')
        results_df = results_df.dropna(subset=['longitude', 'latitude'])

        if results_df.empty:
            st.info("Concurrents trouvés mais non géocodés.")
            return gpd.GeoDataFrame()

        from fonctions_cartographie import transfo_geodataframe
        gdf_concurrents = transfo_geodataframe(results_df, "longitude", "latitude")

        gdf_concurrents['nom_etablissement'] = gdf_concurrents['denominationunitelegale']
        gdf_concurrents['adresse_simplifiee'] = gdf_concurrents['adresse']
        gdf_concurrents['precision_geocodage'] = 'siren_db'

        st.success(f"{len(gdf_concurrents)} concurrent(s) trouvé(s) dans la zone : {scope}.")
        return gdf_concurrents

    except Exception as e:
        st.error(f"Erreur lors de la recherche : {e}")
        return gpd.GeoDataFrame()

# ==============================================
# MODIFIÉ : Fonction générale (déplacée)
# ==============================================
def transfo_geodataframe(df, longitude_col, latitude_col, crs="EPSG:4326"):
    """Crée un GeoDataFrame à partir de colonnes de longitude et latitude."""
    # On s'assure que les colonnes sont numériques
    df[longitude_col] = pd.to_numeric(df[longitude_col], errors='coerce')
    df[latitude_col] = pd.to_numeric(df[latitude_col], errors='coerce')
    # On supprime les lignes où la géolocalisation a échoué
    df = df.dropna(subset=[longitude_col, latitude_col])

    if df.empty:
        return gpd.GeoDataFrame()

    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df[longitude_col], df[latitude_col]), crs=crs)

# ==============================================
# Section chargement des données (INCHANGÉE)
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
@st.cache_data(show_spinner=False)
def charger_donnees_iris_socio(path):
    """Charge les données IRIS et convertit en WGS84 (GPS) pour compatibilité."""
    try:
        gdf = gpd.read_parquet(path)
        # Conversion forcée en EPSG:4326 (GPS) si ce n'est pas le cas
        if gdf.crs is not None and gdf.crs.to_string() != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
        elif gdf.crs is None:
            gdf.set_crs("EPSG:4326", inplace=True)
        return gdf
    except Exception as e:
        print(f"Erreur chargement IRIS: {e}")
        return None


@st.cache_data(show_spinner=False)
def charger_coefficients_trafic(path_coeff_trafic):
    """Charge la table des coefficients de trafic par ville."""
    try:
        return pd.read_excel(path_coeff_trafic)
    except FileNotFoundError:
        st.warning(
            f"Fichier des coefficients de trafic introuvable : {path_coeff_trafic}. Le trafic ne sera pas simulé.")
        return pd.DataFrame(columns=['ville', 'coefficient'])


@st.cache_data(show_spinner="Chargement des zones inondables...")
def charger_zones_inondables(path_parquet):
    """
    Charge les données optimisées des zones inondables.
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
    Charge les données optimisées sur le risque de sécheresse (RGA).
    """
    try:
        gdf = gpd.read_parquet(path_parquet)
        return gdf
    except Exception as e:
        st.warning(f"Fichier des données RGA introuvable ou illisible : {e}. La fonctionnalité sera désactivée.")
        return gpd.GeoDataFrame()


# ==============================================
# Fonctions pour la page OSM (INCHANGÉES)
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
    # S'assurer que les colonnes existent avant de les utiliser
    if 'ville' not in data.columns or 'latitude' not in data.columns or 'longitude' not in data.columns:
        # Cas pour les dataframes de concurrents (qui n'ont pas 'ville')
        if 'libellecommuneetablissement' in data.columns:
            data = data.rename(columns={'libellecommuneetablissement': 'ville'})
        else:
            st.warning("Données insuffisantes pour choisir un centre.")
            return 48.85, 2.35  # Paris par défaut

    centre_ville = data.groupby("ville").first().reset_index()[["ville", "latitude", "longitude"]]

    if centre_ville.empty:
        lat_centre = data['latitude'].mean()
        lon_centre = data['longitude'].mean()
        return lat_centre, lon_centre

    centre_ville_utilisateur = st.selectbox("Choisissez une ville pour le centre de votre carte", centre_ville["ville"])
    coordonnees_centre = centre_ville[centre_ville["ville"] == centre_ville_utilisateur]
    lon_centre = coordonnees_centre["longitude"].iloc[0]
    lat_centre = coordonnees_centre["latitude"].iloc[0]
    return lat_centre, lon_centre


@st.cache_data(show_spinner=False)
def preparer_donnees_socio(_df_iris_base, _df_communes_france):
    """
    Nettoie, enrichit, simplifie et prépare les données socio-économiques.
    """
    if _df_iris_base is None:
        st.error("Données IRIS non chargées, impossible de préparer les données socio-économiques.")
        return {}

    df = _df_iris_base.copy()
    try:
        df['geometry'] = df['geometry'].simplify(tolerance=100, preserve_topology=True)
    except Exception as e:
        st.warning(f"Avertissement lors de la simplification des géométries : {e}")

    if _df_communes_france.empty:
        st.error("Fichier des communes non chargé, impossible de préparer les données socio-économiques.")
        return {}

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

    cols_a_vider_final = list(set(cols_a_vider + ['Population_totale']))

    for dframe in [df_commune, df_departement]:
        lignes_a_modifier = dframe['Population_totale'] == 0
        if lignes_a_modifier.any():
            colonnes_presentes = [col for col in cols_a_vider_final if col in dframe.columns]
            dframe.loc[lignes_a_modifier, colonnes_presentes] = np.nan

    return {"IRIS": df, "Commune": df_commune, "Département": df_departement}


def enrichir_donnees_risques_avec_num_dep(gdf_risques, df_communes):
    """
    Enrichit un GeoDataFrame de risques (inondation, RGA, etc.) avec le numéro de département.
    """
    if 'NOM_DEP' not in gdf_risques.columns:
        st.warning("La colonne 'NOM_DEP' est manquante dans les données de risque. Impossible d'enrichir.")
        return gdf_risques
    if gdf_risques.empty:
        return gdf_risques

    df_ref_deps = df_communes[['Num_Dep', 'Nom_Dep']].copy().drop_duplicates('Nom_Dep')
    df_ref_deps['join_key'] = df_ref_deps['Nom_Dep'].str.upper().str.replace('-', ' ')
    gdf_risques['join_key'] = gdf_risques['NOM_DEP'].str.upper().str.replace('-', ' ')

    gdf_enrichi = gdf_risques.merge(
        df_ref_deps[['Num_Dep', 'join_key']],
        on='join_key',
        how='left'
    )

    gdf_enrichi = gdf_enrichi.drop(columns=['join_key'])

    if 'Num_Dep' in gdf_enrichi.columns:
        gdf_enrichi['Num_Dep'] = gdf_enrichi['Num_Dep'].astype(str).str.zfill(2)

    return gdf_enrichi


# Fichier: fonctions_basiques.py
# ... (Gardez les imports et les autres fonctions) ...

@st.cache_data(show_spinner="Calcul des statistiques d'ancienneté...")
def calculer_stats_anciennete(_engine, code_naf, scope, scope_value, ville_origine=None):
    """
    Calcule l'âge moyen, min et max des établissements actifs pour un code NAF donné
    dans une zone géographique (Département ou Ville).
    """
    if not _engine:
        return None

    # 1. Construction de la clause géographique (identique à find_concurrents)
    # Note : Pour la ville, on doit filtrer en Python ou faire un LIKE en SQL.
    # Comme la colonne 'ville' n'existe plus, on filtre d'abord large (Département) en SQL.

    query = sqlalchemy.text("""
        SELECT 
            datecreationetablissement,
            adresse
        FROM etablissements
        WHERE 
            activiteprincipaleetablissement = :code_naf AND
            numero_dep = :num_dep;
    """)

    params = {
        "code_naf": code_naf,
        "num_dep": scope_value  # scope_value est le numéro de département
    }

    try:
        with _engine.connect() as conn:
            df_dates = pd.read_sql_query(query, conn, params=params)

        if df_dates.empty:
            return None

        # 2. Si le scope est 'Ville', on filtre ici avec notre Regex (comme pour la carte)
        if scope == 'Ville' and ville_origine:
            # On réutilise la logique d'extraction (assurez-vous d'avoir importé re)
            df_dates['ville_extract'] = df_dates['adresse'].apply(extraire_ville_depuis_adresse)
            df_dates = df_dates[df_dates['ville_extract'] == ville_origine.upper()]

            if df_dates.empty:
                return None

        # 3. Calcul de l'âge
        # La date est en string 'YYYY-MM-DD', on convertit en datetime
        df_dates['date_creation'] = pd.to_datetime(df_dates['datecreationetablissement'], errors='coerce')
        df_dates = df_dates.dropna(subset=['date_creation'])

        # Calcul de l'âge en années (Date du jour - Date création) / 365.25
        now = pd.Timestamp.now()
        df_dates['age_annees'] = (now - df_dates['date_creation']).dt.days / 365.25

        # 4. Agrégation
        stats = {
            "age_moyen": round(df_dates['age_annees'].mean(), 1),
            "age_median": round(df_dates['age_annees'].median(), 1),
            "plus_vieux": round(df_dates['age_annees'].max(), 1),
            "plus_recent": round(df_dates['age_annees'].min(), 1),
            "nb_etablissements_dates": len(df_dates)
        }

        return stats

    except Exception as e:
        print(f"Erreur calcul ancienneté : {e}")
        return None


@st.cache_data(show_spinner="Chargement des valeurs foncières (DVF)...")
def charger_donnees_dvf(path_parquet):
    """
    Charge le fichier Parquet DVF.
    Convertit la date pour le filtrage.
    """
    try:
        df = pd.read_parquet(path_parquet)

        # Vérification colonnes
        required = ['latitude', 'longitude', 'prix_m2', 'type_local', 'date_mutation', 'valeur_fonciere',
                    'surface_reelle_bati']
        if not all(c in df.columns for c in required):
            st.error("Colonnes DVF manquantes.")
            return pd.DataFrame()

        # Conversion Date pour le filtre temporel
        if not pd.api.types.is_datetime64_any_dtype(df['date_mutation']):
            df['date_mutation'] = pd.to_datetime(df['date_mutation'], errors='coerce')

        # Extraction Année pour faciliter les filtres
        df['annee'] = df['date_mutation'].dt.year

        return df
    except FileNotFoundError:
        st.warning(f"Fichier DVF introuvable : {path_parquet}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erreur chargement DVF : {e}")
        return pd.DataFrame()


def calculer_comparatif_radar(gdf_iris, zone_geom, metriques_demandees=None, df_communes_ref=None):
    """
    Calcule les indicateurs radar avec choix des métriques et nom du département.

    Args:
        metriques_demandees (list): Liste de clés de configuration (ex: ['Revenus', 'Cadres']).
                                    Si None, utilise tout.
        df_communes_ref (DataFrame): Pour traduire le code dept (33) en nom (Gironde).

    Returns:
        tuple: (DataFrame des stats, String nom_departement)
    """
    # 1. Sécurités de base
    if gdf_iris is None or gdf_iris.empty or zone_geom is None:
        return None, "Données Manquantes"

    # --- CONFIGURATION CENTRALE DES MÉTRIQUES ---
    # Format : "Clé": ("Label Affiché", Colonne_Num, Colonne_Denom, Is_Revenu)
    CONFIG_METRIQUES_DB = {
        "Revenus": ("Revenus (Médian)", "Revenu_median", None, True),
        "Jeunes": ("Jeunes (<25 ans)", "Pop_15_24_ans", "Population_totale", False),
        "Actifs": ("Actifs (25-54 ans)", "Pop_25_54_ans", "Population_totale", False),
        "Seniors": ("Seniors (>55 ans)", ["Pop_55_79_ans", "Pop_80_ans_plus"], "Population_totale", False),
        "Cadres": ("Cadres (CSP+)", "Menages_cadres_prof_intelectuelles_CS3", "Nb_menages_total", False),
        "Ouvriers": ("Ouvriers (CSP-)", "Menages_ouvriers_CS6", "Nb_menages_total", False),
        "Familles": ("Ménages avec Enfants", "Menages_couple_avec_enfant", "Nb_menages_total", False),
        "Monoparental": ("Familles Monoparentales", "Menages_monoparental", "Nb_menages_total", False),
        "Retraités": ("Retraités", "Menages_retraites_CS7", "Nb_menages_total", False)
    }

    # Si aucune sélection (premier chargement), on prend un set par défaut
    if not metriques_demandees:
        metriques_demandees = ["Revenus", "Jeunes", "Actifs", "Seniors", "Cadres"]

    # --- 2. INTERSECTION SPATIALE (Moteur Géographique) ---
    try:
        # Création GeoDataFrame pour la zone
        gdf_zone_analyse = gpd.GeoDataFrame({'geometry': [zone_geom]}, crs="EPSG:4326")

        # Alignement CRS (Projection GPS)
        gdf_iris_work = gdf_iris.copy()
        if gdf_iris_work.crs is None:
            gdf_iris_work.set_crs("EPSG:4326", inplace=True)
        elif gdf_iris_work.crs.to_string() != "EPSG:4326":
            gdf_iris_work = gdf_iris_work.to_crs("EPSG:4326")

        # Jointure Spatiale (On garde les IRIS qui touchent la zone)
        iris_zone = gpd.sjoin(gdf_iris_work, gdf_zone_analyse, how="inner", predicate="intersects")

        if iris_zone.empty:
            return None, "Hors Zone"

    except Exception as e:
        print(f"Erreur Radar: {e}")
        return None, "Erreur Géom"

    # --- 3. IDENTIFICATION DU DÉPARTEMENT ---
    # Création de la colonne CODE_DEPT si absente
    if 'CODE_DEPT' not in iris_zone.columns:
        iris_zone['CODE_DEPT'] = iris_zone['IRIS'].astype(str).str[:2]
        gdf_iris_work['CODE_DEPT'] = gdf_iris_work['IRIS'].astype(str).str[:2]

    # Trouver le département majoritaire
    if iris_zone['CODE_DEPT'].mode().empty:
        return None, "Inconnu"

    code_dept_ref = iris_zone['CODE_DEPT'].mode()[0]

    # Traduction Code -> Nom (ex: 33 -> Gironde)
    nom_dept_display = f"Département {code_dept_ref}"
    if df_communes_ref is not None and not df_communes_ref.empty:
        # On cherche le nom dans le référentiel commune chargé
        # On s'assure que le type (str/int) correspond
        df_communes_ref['Num_Dep'] = df_communes_ref['Num_Dep'].astype(str)
        match = df_communes_ref[df_communes_ref['Num_Dep'] == str(code_dept_ref)]
        if not match.empty:
            nom_reel = match.iloc[0]['Nom_Dep']
            nom_dept_display = f"{nom_reel} ({code_dept_ref})"

    # Création du DataFrame de référence (Tout le département)
    df_dept = gdf_iris_work[gdf_iris_work['CODE_DEPT'] == code_dept_ref].copy()

    # --- 4. CALCUL DES RATIOS (Dynamique) ---
    stats = []

    for key in metriques_demandees:
        if key not in CONFIG_METRIQUES_DB:
            continue

        label, num_col, den_col, is_revenu = CONFIG_METRIQUES_DB[key]
        vals = {}

        for scope_name, df_scope in [("Zone", iris_zone), ("Departement", df_dept)]:
            valeur = 0

            # A. Cas REVENUS (Moyenne)
            if is_revenu:
                if num_col in df_scope.columns:
                    valeur = df_scope[num_col].mean()

            # B. Cas RATIOS (%)
            else:
                # B1. Calcul Dénominateur
                total_den = 0
                if den_col and den_col in df_scope.columns:
                    total_den = df_scope[den_col].sum()
                elif den_col == "Population_totale":
                    # Reconstruction de secours si colonne absente
                    cols_pop = ['Pop_15_24_ans', 'Pop_25_54_ans', 'Pop_55_79_ans', 'Pop_80_ans_plus']
                    cols_exist = [c for c in cols_pop if c in df_scope.columns]
                    total_den = df_scope[cols_exist].sum().sum()

                # B2. Calcul Numérateur
                total_num = 0
                if isinstance(num_col, list):
                    # Somme de plusieurs colonnes (ex: Seniors)
                    cols_ok = [c for c in num_col if c in df_scope.columns]
                    total_num = df_scope[cols_ok].sum().sum()
                else:
                    if num_col in df_scope.columns:
                        total_num = df_scope[num_col].sum()

                # B3. Pourcentage
                if total_den > 0:
                    valeur = (total_num / total_den) * 100

            vals[scope_name] = valeur

        # Calcul Indice 100
        val_z = vals["Zone"]
        val_d = vals["Departement"]
        indice = 100
        if pd.notnull(val_d) and val_d > 0:
            indice = (val_z / val_d) * 100

        stats.append({
            'Metrique': label,
            'Zone': val_z if pd.notnull(val_z) else 0,
            'Departement': val_d if pd.notnull(val_d) else 0,
            'Indice_100': indice if pd.notnull(indice) else 0
        })

    return pd.DataFrame(stats), nom_dept_display


def calculer_cannibalisation(zone_analysee_geom, gdf_reseau_existant, buffer_existant_m=2000):
    """
    Calcule le taux de chevauchement entre la nouvelle zone et le réseau existant.
    """
    if zone_analysee_geom is None or gdf_reseau_existant.empty:
        return 0, None

    # 1. On crée les zones du réseau existant (Buffers simples pour aller vite)
    # Idéalement, on ferait des isochrones, mais le buffer est un excellent proxy rapide
    try:
        gdf_reseau_buffers = gdf_reseau_existant.to_crs("EPSG:2154").buffer(buffer_existant_m)
        zone_reseau_union = gdf_reseau_buffers.unary_union

        # On repasse en GPS pour l'intersection avec la zone analysée (si elle est en GPS)
        # Attention : zone_analysee_geom doit être un objet Shapely, on le met dans un GDF pour gérer les CRS
        gdf_zone_new = gpd.GeoDataFrame({'geometry': [zone_analysee_geom]}, crs="EPSG:4326").to_crs("EPSG:2154")
        area_new_total = gdf_zone_new.area.iloc[0]

        # 2. Calcul de l'intersection (Recouvrement)
        # Intersection géométrique
        intersection = gdf_zone_new.intersection(zone_reseau_union)

        if intersection.is_empty.all():
            return 0, None

        area_intersection = intersection.area.iloc[0]

        # 3. Ratio
        ratio_cannibalisation = (area_intersection / area_new_total) * 100

        return ratio_cannibalisation, intersection.to_crs("EPSG:4326").iloc[0]

    except Exception as e:
        print(f"Erreur Cannibalisation : {e}")
        return 0, None


def calculer_score_global(kpis_socio, kpis_immo, kpis_risques, kpis_concurrence):
    """
    Génère un score sur 100 basé sur 4 piliers.
    Les inputs sont des dictionnaires ou des valeurs simples.
    """
    score_total = 0
    details = {}

    # --- PILIER 1 : POTENTIEL (Population & Argent) ---
    # On vise une population dense et avec du pouvoir d'achat
    pop = kpis_socio.get('population', 0)
    revenu = kpis_socio.get('revenu_median', 0)

    # Logique : Plus c'est haut, mieux c'est, mais avec un plafond (saturation)
    score_pop = min(pop / 5000, 1) * 20  # Max 20 pts si > 5000 hab
    score_rev = min(revenu / 25000, 1) * 20  # Max 20 pts si > 25k€

    details['Potentiel'] = round(score_pop + score_rev, 1)
    score_total += details['Potentiel']

    # --- PILIER 2 : DYNAMISME (Immo & POI) ---
    nb_ventes = kpis_immo.get('nb_ventes', 0)
    nb_poi = kpis_socio.get('nb_poi', 0)  # Si vous avez compté les POI

    score_immo = min(nb_ventes / 20, 1) * 15  # Max 15 pts si > 20 ventes
    score_poi = min(nb_poi / 5, 1) * 15  # Max 15 pts si > 5 POI majeurs

    details['Dynamisme'] = round(score_immo + score_poi, 1)
    score_total += details['Dynamisme']

    # --- PILIER 3 : RISQUES (Malus) ---
    # Ici on part de 15 et on enlève des points
    score_risk = 15
    if kpis_risques.get('inondation'): score_risk -= 10
    if kpis_risques.get('secheresse'): score_risk -= 5
    score_risk = max(0, score_risk)

    details['Sûreté'] = score_risk
    score_total += score_risk

    # --- PILIER 4 : CONCURRENCE (Opportunité ou Saturation) ---
    # C'est subtil : un peu de concurrence = bon signe (zone commerciale). Trop = mauvais.
    nb_concurrents = kpis_concurrence.get('nb_concurrents', 0)

    if nb_concurrents == 0:
        score_conc = 5  # Bof, zone déserte ?
    elif 1 <= nb_concurrents <= 3:
        score_conc = 15  # Top ! Zone active mais prenable
    else:
        score_conc = 5  # Saturé

    details['Concurrence'] = score_conc
    score_total += score_conc

    # Note Finale
    note_finale = min(100, round(score_total, 0))

    # Label
    if note_finale >= 80:
        label = "A+ (Excellent)"
    elif note_finale >= 60:
        label = "B (Bon)"
    elif note_finale >= 40:
        label = "C (Moyen)"
    else:
        label = "D (Risqué)"

    return note_finale, label, details