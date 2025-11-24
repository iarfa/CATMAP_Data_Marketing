# Fichier: pages/00_Home.py
import streamlit as st
from database import connect_to_db

def afficher_accueil():
    # =============================================================================
    # STYLES CSS
    # =============================================================================
    st.markdown("""
    <style>
        .main-header {font-size: 2.5rem; color: #1f77b4; text-align: center; margin-bottom: 0.5rem;}
        .sub-text {font-size: 1.2rem; text-align: center; color: #555; margin-bottom: 1.5rem;}
        .status-text {text-align: center; font-weight: bold; font-size: 1rem; margin-bottom: 1rem;}
        .card-icon {font-size: 3rem; margin-bottom: 10px; text-align: center;}
        .card-title {font-size: 1.5rem; font-weight: bold; color: #333; margin-bottom: 10px; text-align: center;}
    </style>
    """, unsafe_allow_html=True)

    # =============================================================================
    # HEADER & STATUT BDD (Version Épurée)
    # =============================================================================

    st.markdown('<div class="main-header">🌍 CATMAP Data Marketing</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-text">Plateforme d\'Intelligence Géospatiale & Analyse de Réseau</div>', unsafe_allow_html=True)

    # Check de santé du système (Affichage minimaliste)
    try:
        engine = connect_to_db()
        if engine:
            st.markdown(
                '<div class="status-text" style="color: green;">🟢 Base de Données : Connectée</div>',
                unsafe_allow_html=True
            )
    except:
        st.markdown(
            '<div class="status-text" style="color: red;">🔴 Base de Données : Déconnectée</div>',
            unsafe_allow_html=True
        )

    st.markdown("---")

    # =============================================================================
    # PRÉSENTATION DES MODULES (3 Colonnes)
    # =============================================================================

    col1, col2, col3 = st.columns(3)

    with col1:
        with st.container(border=True):
            st.markdown('<div class="card-icon">📊</div>', unsafe_allow_html=True)
            st.markdown('<div class="card-title">Analyse Concurrence</div>', unsafe_allow_html=True)
            st.write("""
            Étudiez votre environnement concurrentiel.

            * **Recherche par Enseigne (OSM)**
            * **Recherche par Code NAF (SIREN)**
            * Visualisation des zones de couverture.
            """)
            st.info("👉 Utilisez le menu à gauche : **Analyse Concurrence**")

    with col2:
        with st.container(border=True):
            st.markdown('<div class="card-icon">📍</div>', unsafe_allow_html=True)
            st.markdown('<div class="card-title">Zone d\'Implantation</div>', unsafe_allow_html=True)
            st.write("""
            Analysez le potentiel d'une adresse précise.

            * **Isochrones & Zones de chalandise**
            * **Données Socio-Démographiques (INSEE)**
            * **Risques (Inondation/Sécheresse)**
            * **Emprise des Bâtiments**
            """)
            st.info("👉 Utilisez le menu à gauche : **Zone d'Implantation**")

    with col3:
        with st.container(border=True):
            st.markdown('<div class="card-icon">💾</div>', unsafe_allow_html=True)
            st.markdown('<div class="card-title">Enrichissement Data</div>', unsafe_allow_html=True)
            st.write("""
            Qualifiez vos fichiers clients ou prospects.

            * Import de fichiers CSV (SIRET ou SIREN).
            * **Récupération automatique** : Adresses, Lat/Lon, NAF.
            * Détection des erreurs de format.
            """)
            st.info("👉 Utilisez le menu à gauche : **Enrichissement Data**")

    # =============================================================================
    # FOOTER / MÉTHODOLOGIE
    # =============================================================================
    st.markdown("---")
    with st.expander("ℹ️ Méthodologie & Sources de Données"):
        st.markdown("""
        Cette application croise plusieurs sources de données officielles et Open Data :

        1.  **Base SIRENE (INSEE)** : Stockée localement (PostgreSQL/PostGIS) pour une recherche exhaustive des entreprises françaises (~14 millions d'établissements).
        2.  **OpenStreetMap (OSM)** : Utilisé pour la géolocalisation des enseignes, les fonds de carte et l'emprise des bâtiments.
        3.  **Données Socio-Démographiques (INSEE)** : Données carroyées au niveau IRIS (Revenus, Population, CSP).
        4.  **Données Risque Physique** : Zones inondables (TRI) et Risque Argile (RGA).
        5.  **OpenRouteService** : Calcul des temps de trajet (Isochrones) en voiture.
        """)

# Si le fichier est exécuté directement (optionnel si appelé via main.py)
if __name__ == "__main__":
    afficher_accueil()