import streamlit as st


def page_insee(path_etablissement, path_centres_departements):
    """
    Cette page est désactivée car elle dépendait d'un ancien fichier parquet.
    La nouvelle logique se trouve dans la page 'Analyse Géospatiale'
    et se connecte à la base de données PostGIS.
    """
    st.header("📊 Page Données INSEE (Désactivée)")
    st.warning("Cette page est actuellement désactivée.")
    st.info("""
        Toute la logique d'analyse des établissements (SIREN/SIRET) a été déplacée 
        vers la page 'Analyse Géospatiale', qui utilise la base de données SIREN 
        que vous avez importée.

        Veuillez sélectionner 'Analyse Géospatiale' dans le menu de gauche.
    """)