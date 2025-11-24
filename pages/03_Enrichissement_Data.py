# Fichier: pages/03_Enrichissement_Data.py

import streamlit as st
import time
import pandas as pd

# Imports Métiers
from fonctions_basiques import connect_to_db, enrichir_dataframe_siren
from interface import interface_enrichissement_fichier, interface_telechargement_fichier

# =============================================================================
# CONFIGURATION
# =============================================================================
# (Note: Pas de set_page_config ici car géré par main.py)

st.title("💾 Enrichissement de Fichiers")
st.markdown("""
Cet outil vous permet de croiser un fichier CSV contenant des SIREN ou SIRET avec la base de données officielle.
Il récupère automatiquement les adresses, codes NAF, coordonnées GPS, etc.
""")

# =============================================================================
# MAIN EXECUTION
# =============================================================================

engine = connect_to_db()

if not engine:
    st.error("Connexion à la base de données SIREN échouée. Impossible d'utiliser cette fonctionnalité.")
else:
    # 1. Récupération des paramètres
    df_original, colonne_id, type_identifiant, only_siege = interface_enrichissement_fichier()

    if df_original is not None and colonne_id is not None:

        start_time = time.time()

        # 2. Appel de la fonction d'enrichissement
        df_succes, df_not_found, df_bad_format = enrichir_dataframe_siren(
            engine,
            df_original,
            colonne_id,
            type_identifiant,
            only_siege
        )

        end_time = time.time()
        duree = end_time - start_time

        # --- TABLEAU 1 : SUCCÈS ---
        if not df_succes.empty:
            nb_trouves = len(df_succes)
            vitesse = nb_trouves / duree if duree > 0 else 0

            # NOUVEAU : TOAST (Notification éphémère)
            st.toast(f"Enrichissement terminé ! {nb_trouves} lignes traitées.", icon="✅")

            # On garde un message discret pour les infos techniques
            message_succes = (
                f"✅ **{nb_trouves}** établissements trouvés.\n"
                f"⏱️ Vitesse : **{vitesse:.0f} req/s**."
            )

            st.markdown("---")
            interface_telechargement_fichier(
                df=df_succes,
                titre_section="📂 Données Enrichies (Succès)",
                nom_fichier_csv="resultats_enrichis.csv",
                message_info=message_succes,
                couleur_info="success"
            )
        else:
            if df_not_found.empty and df_bad_format.empty:
                pass
            else:
                st.warning("Aucun résultat trouvé dans la base pour les identifiants valides fournis.")

        # --- TABLEAU 2 : FORMAT INVALIDE (Rejets) ---
        if not df_bad_format.empty:
            nb_bad = len(df_bad_format)
            target_len = 14 if type_identifiant == "siret" else 9

            # Toast d'alerte
            st.toast(f"Attention : {nb_bad} erreurs de format détectées.", icon="⚠️")

            message_bad = (
                f"⚠️ **{nb_bad} lignes ont un format incorrect.**\n"
                f"Critère : {target_len} caractères numériques."
            )

            st.markdown("---")
            interface_telechargement_fichier(
                df=df_bad_format,
                titre_section=f"🚫 Rejets : Format {type_identifiant.upper()} Invalide",
                nom_fichier_csv="lignes_format_incorrect.csv",
                message_info=message_bad,
                couleur_info="error"
            )

        # --- TABLEAU 3 : INTROUVABLES (Format OK, mais pas en base) ---
        if not df_not_found.empty:
            nb_not_found = len(df_not_found)

            contexte_filtre = " (Filtre Siège actif)" if (type_identifiant == "siren" and only_siege) else ""

            message_not_found = (
                f"🤷‍♂️ **{nb_not_found}** identifiants valides mais introuvables.{contexte_filtre}"
            )

            st.markdown("---")
            interface_telechargement_fichier(
                df=df_not_found,
                titre_section="🔍 Rejets : Identifiants Inconnus en Base",
                nom_fichier_csv="lignes_introuvables.csv",
                message_info=message_not_found,
                couleur_info="warning"
            )