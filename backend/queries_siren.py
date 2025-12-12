# Fichier: backend/queries_siren.py

import pandas as pd
from sqlalchemy import text
import re
from datetime import datetime
import streamlit as st
from utils.geo_tools import extraire_ville_depuis_adresse

# =============================================================================
# 1. INFO ÉTABLISSEMENT UNIQUE (SIRET - 14 chiffres)
# =============================================================================
def get_etablissement_par_siret(engine, siret):
    """
    Récupère les infos d'un établissement spécifique.
    """
    if not engine: return None

    siret = str(siret).strip().replace(" ", "")
    query = text("""
        SELECT 
            siret, siren, denominationunitelegale, 
            activiteprincipaleetablissement, adresse,
            numero_dep, nom_dep, latitude, longitude,
            datecreationetablissement, etablissementsiege
        FROM etablissements
        WHERE siret = :siret
        LIMIT 1;
    """)

    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"siret": siret}).fetchone()
            if result:
                return dict(result._mapping)
    except Exception as e:
        print(f"Erreur SQL SIRET: {e}")
    return None


# =============================================================================
# 2. LISTE ÉTABLISSEMENTS D'UNE ENTREPRISE (SIREN - 9 chiffres)
# =============================================================================
def get_etablissements_par_siren(engine, siren):
    """
    Récupère TOUS les établissements liés à un SIREN (9 chiffres).
    Retourne un DataFrame.
    """
    if not engine: return pd.DataFrame()

    siren = str(siren).strip().replace(" ", "")
    # Sécurité format
    if len(siren) != 9: return pd.DataFrame()

    query = text("""
        SELECT 
            siret, siren, denominationunitelegale, 
            activiteprincipaleetablissement, adresse,
            numero_dep, nom_dep, latitude, longitude,
            datecreationetablissement, etablissementsiege
        FROM etablissements
        WHERE siren = :siren
        ORDER BY etablissementsiege DESC; -- Siège en premier
    """)

    try:
        with engine.connect() as conn:
            df = pd.read_sql(query, conn, params={"siren": siren})
            return df
    except Exception as e:
        print(f"Erreur SQL SIREN: {e}")
        return pd.DataFrame()


# =============================================================================
# 3. LISTE CONCURRENTS (NAF + DEPT)
# =============================================================================
def get_concurrents_sql(engine, code_naf, num_dep, siret_exclu="0"):
    """
    Récupère la liste des concurrents (Même NAF, Même Dept).
    """
    if not engine: return pd.DataFrame()

    # On nettoie le SIREN à exclure (les 9 premiers chiffres du SIRET)
    siren_exclu = str(siret_exclu)[:9]

    query = text("""
        SELECT 
            siret, siren, denominationunitelegale, adresse,
            latitude, longitude, activiteprincipaleetablissement,
            datecreationetablissement
        FROM etablissements
        WHERE 
            activiteprincipaleetablissement = :code_naf AND
            numero_dep = :num_dep AND
            siren != :siren_exclu; 
    """)

    try:
        with engine.connect() as conn:
            df = pd.read_sql(query, conn, params={
                "code_naf": code_naf,
                "num_dep": str(num_dep),
                "siren_exclu": siren_exclu
            })
            return df
    except Exception as e:
        print(f"Erreur SQL Concurrents: {e}")
        return pd.DataFrame()


# =============================================================================
# 4. STATISTIQUES ANCIENNETÉ
# =============================================================================
def calculer_stats_anciennete(engine, code_naf, scope, code_dep, ville_nom=None):
    """
    Calcule l'âge moyen des concurrents dans la zone.
    CRITIQUE : code_dep accepte désormais une liste de départements (pour la portée Région/France).
    """
    if not engine: return None

    # Conversion en liste/tuple pour la clause IN de SQL
    if isinstance(code_dep, str):
        code_dep = [code_dep]

    if not code_dep: return None

    # 1. Requête SQL : On tire large (Département(s))
    query = text(f"""
        SELECT datecreationetablissement, adresse
        FROM etablissements
        WHERE activiteprincipaleetablissement = :code_naf AND numero_dep IN :num_dep
    """)

    try:
        with engine.connect() as conn:
            # SQLAlchemy utilise un dictionnaire pour les paramètres IN (tuple)
            df = pd.read_sql(query, conn, params={"code_naf": code_naf, "num_dep": tuple(code_dep)})

        if df.empty: return None

        # 2. Filtrage Ville (Python) si nécessaire
        if scope == "Ville" and ville_nom:
            # L'import de extraire_ville_depuis_adresse est requis et doit être géré dans ce fichier
            df['ville_extract'] = df['adresse'].apply(extraire_ville_depuis_adresse)
            df = df[df['ville_extract'] == ville_nom.upper()]

            if df.empty: return None

        # 3. Calculs Mathématiques
        df['date_creation'] = pd.to_datetime(df['datecreationetablissement'], errors='coerce')
        df = df.dropna(subset=['date_creation'])

        if df.empty: return None

        now = datetime.now()
        df['age'] = (now - df['date_creation']).dt.days / 365.25

        stats = {
            "age_moyen": round(df['age'].mean(), 1),
            "age_median": round(df['age'].median(), 1),
            "min": round(df['age'].min(), 1),
            "max": round(df['age'].max(), 1),
            "count": len(df)
        }
        return stats

    except Exception as e:
        print(f"Erreur Stats Ancienneté: {e}")
        return None