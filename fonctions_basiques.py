# ==============================================
# 📦 Imports & Librairies
# ==============================================
import pandas as pd
import streamlit as st
import numpy as np
import geopandas as gpd
import sqlalchemy


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
    - type_identifiant : 'siret' ou 'siren'
    - only_siege : Si True et mode SIREN, ne garde que les sièges.

    Retourne (df_succes, df_echec_not_found, df_rejet_format)
    """
    if not _engine:
        st.error("Connexion à la base de données échouée.")
        return df, pd.DataFrame(), pd.DataFrame()

    # 1. Nettoyage préliminaire
    try:
        # Conversion string + nettoyage espaces/points/tabs
        df['clean_id'] = df[colonne_id].astype(str).str.replace(' ', '', regex=False).str.replace('.', '',
                                                                                                  regex=False).str.strip()
        # Fix pour les cas où Excel a converti en "12345.0"
        df['clean_id'] = df['clean_id'].apply(lambda x: x[:-2] if x.endswith('.0') else x)
    except KeyError:
        st.error(f"Colonne '{colonne_id}' non trouvée dans le fichier.")
        return df, pd.DataFrame(), pd.DataFrame()

    # 2. Validation du format (Longueur + Numérique)
    mask_valid = pd.Series([False] * len(df), index=df.index)

    if type_identifiant == "siret":
        mask_valid = (df['clean_id'].str.len() == 14) & (df['clean_id'].str.isdigit())
        colonne_sql_match = "siret"

        # Requête SIRET : Simple, pas de notion de "siège only" nécessaire car SIRET = Unique
        query_str = """
            SELECT 
                siret AS join_key,
                siren, denominationunitelegale, adresse, latitude, longitude,
                codepostaletablissement, libellecommuneetablissement,
                activiteprincipaleetablissement, intitules_naf_vf, numero_dep, nom_dep,
                etablissementsiege
            FROM etablissements WHERE siret IN :liste_ids
        """

    elif type_identifiant == "siren":
        mask_valid = (df['clean_id'].str.len() == 9) & (df['clean_id'].str.isdigit())
        colonne_sql_match = "siren"

        # Requête SIREN : Gestion du filtre Siège
        clause_siege = "AND etablissementsiege = True" if only_siege else ""

        query_str = f"""
            SELECT 
                siren AS join_key,
                siret, denominationunitelegale, adresse, latitude, longitude,
                codepostaletablissement, libellecommuneetablissement,
                activiteprincipaleetablissement, intitules_naf_vf, numero_dep, nom_dep,
                etablissementsiege
            FROM etablissements 
            WHERE siren IN :liste_ids {clause_siege}
        """

    # --- DataFrame 3 : REJETS DE FORMAT ---
    df_rejet_format = df[~mask_valid].copy()
    if 'clean_id' in df_rejet_format.columns:
        df_rejet_format = df_rejet_format.drop(columns=['clean_id'])

    # Liste des IDs valides à chercher
    ids_valides_uniques = df.loc[mask_valid, 'clean_id'].unique().tolist()

    if not ids_valides_uniques:
        return pd.DataFrame(), pd.DataFrame(), df_rejet_format

    # 3. Exécution de la requête
    try:
        query = sqlalchemy.text(query_str)
        params = {"liste_ids": tuple(ids_valides_uniques)}
        with _engine.connect() as conn:
            resultats_df = pd.read_sql_query(query, conn, params=params)
    except Exception as e:
        st.error(f"Erreur SQL : {e}")
        return pd.DataFrame(), pd.DataFrame(), df_rejet_format

    # 4. Fusion (Merge)
    df_valide_input = df[mask_valid].copy()

    # Left join pour garder les lignes valides même si non trouvées en base
    df_merged = pd.merge(
        df_valide_input,
        resultats_df,
        left_on='clean_id',
        right_on='join_key',
        how='left'
    )

    # Nettoyage des colonnes de jointure
    cols_to_drop = ['join_key', 'clean_id']
    df_merged = df_merged.drop(columns=[c for c in cols_to_drop if c in df_merged.columns])

    # 5. Séparation Succès vs Non Trouvé
    mask_found = df_merged['denominationunitelegale'].notna()

    # --- DataFrame 1 : SUCCÈS ---
    df_succes = df_merged[mask_found].copy()

    # --- DataFrame 2 : INTROUVABLES (Format OK mais inconnus) ---
    df_echec_not_found = df_merged[~mask_found].copy()
    # On retire les colonnes vides ajoutées par le merge dans les échecs
    cols_resultats = [c for c in resultats_df.columns if c != 'join_key']
    df_echec_not_found = df_echec_not_found.drop(columns=cols_resultats, errors='ignore')

    return df_succes, df_echec_not_found, df_rejet_format

# ==================================================================
# NOUVEAU : Logique de concurrence (Pour Goal 3 / P4)
# ==================================================================
@st.cache_data(show_spinner="Récupération des détails de l'établissement...")
def get_etab_details_for_concurrence(_engine, siret):
    """
    Trouve un SIRET et retourne ses infos clés pour une recherche de concurrence,
    y compris l'intitulé NAF pour la lisibilité.
    """
    if not _engine:
        return None

    siret = str(siret).strip().replace(" ", "")
    if not siret.isdigit() or len(siret) != 14:
        st.warning("SIRET invalide. Veuillez entrer un numéro à 14 chiffres.", icon="⚠️")
        return None

    # MODIFIÉ : Ajout de 'intitules_naf_vf' pour avoir la description humaine du code NAF
    query = sqlalchemy.text("""
        SELECT 
            denominationunitelegale, 
            activiteprincipaleetablissement,
            intitules_naf_vf,
            libellecommuneetablissement,
            numero_dep,
            nom_dep
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


@st.cache_data(show_spinner="Recherche des concurrents...")
def find_concurrents(_engine, siret_origine, code_naf, scope, scope_value):
    """
    Trouve les concurrents (même NAF) dans une zone donnée (ville, dep).
    EXCLUT les établissements ayant le même SIREN que l'établissement d'origine (réseau interne).
    """
    if not _engine:
        return gpd.GeoDataFrame()

    # On extrait le SIREN (9 premiers chiffres) du SIRET d'origine pour l'exclusion
    siret_origine = str(siret_origine).strip()
    siren_origine = siret_origine[:9]

    # On construit la clause WHERE pour la zone
    if scope == 'Ville':
        where_clause = "libellecommuneetablissement = :scope_value"
    elif scope == 'Département':
        where_clause = "numero_dep = :scope_value"
    else:
        st.error("Scope de recherche non valide.")
        return gpd.GeoDataFrame()

    # MODIFIÉ :
    # 1. On récupère 'intitules_naf_vf'
    # 2. On filtre sur 'siren != :siren_origine' pour exclure le réseau interne
    query = sqlalchemy.text(f"""
        SELECT 
            siret,
            siren,
            denominationunitelegale,
            adresse,
            latitude,
            longitude,
            codepostaletablissement,
            libellecommuneetablissement,
            activiteprincipaleetablissement,
            intitules_naf_vf
        FROM etablissements
        WHERE 
            activiteprincipaleetablissement = :code_naf AND
            {where_clause} AND
            siren != :siren_origine; 
    """)

    params = {
        "code_naf": code_naf,
        "scope_value": scope_value,
        "siren_origine": siren_origine
    }

    try:
        with _engine.connect() as conn:
            results_df = pd.read_sql_query(query, conn, params=params)

        if results_df.empty:
            st.info("Aucun concurrent trouvé dans cette zone avec ce code NAF (hors réseau interne).")
            return gpd.GeoDataFrame()

        # On s'assure que lat/lon sont numériques avant de créer le GDF
        results_df['longitude'] = pd.to_numeric(results_df['longitude'], errors='coerce')
        results_df['latitude'] = pd.to_numeric(results_df['latitude'], errors='coerce')
        results_df = results_df.dropna(subset=['longitude', 'latitude'])

        if results_df.empty:
            st.info("Concurrents trouvés mais non géocodés. Affichage impossible.")
            return gpd.GeoDataFrame()

        # Transformer en GeoDataFrame (Import local pour éviter dépendance circulaire si besoin, ou utiliser l'import global)
        # Note: Assurez-vous que transfo_geodataframe est bien dispo, sinon importez-le de fonctions_cartographie
        from fonctions_cartographie import transfo_geodataframe

        gdf_concurrents = transfo_geodataframe(results_df, "longitude", "latitude")

        # On prépare le GDF pour la carte (similaire à OSM)
        gdf_concurrents['nom_etablissement'] = gdf_concurrents['denominationunitelegale']
        gdf_concurrents['adresse_simplifiee'] = gdf_concurrents['adresse']
        gdf_concurrents['precision_geocodage'] = 'siren_db'

        st.success(f"{len(gdf_concurrents)} concurrent(s) trouvé(s) (hors réseau interne).")
        return gdf_concurrents

    except Exception as e:
        st.error(f"Erreur lors de la recherche de concurrents : {e}")
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