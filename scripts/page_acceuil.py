# Import des librairies
import streamlit as st

# Page d'acceuil
def page_accueil():
    """
    Affiche la page d'accueil mise à jour de l'application.
    """
    st.title("🌍 Outil d'Aide à la Décision Géospatiale")

    st.markdown("""
    ### Explorez les données de territoire, analysez la concurrence et optimisez vos stratégies d'implantation.

    ---

    👋 **Bienvenue sur votre plateforme d'analyse concurrentielle.**

    Cet outil vous permet de remplacer les analyses intuitives par une approche rigoureuse, pilotée par la donnée géospatiale.

    Utilisez le menu à gauche pour accéder à l'outil principal :
    - **🗺️ Analyse Géospatiale**

    Vous pourrez y mener deux types d'études :
    1.  **Analyser la concurrence** sur une zone définie (région, département ou communes).
    2.  **Étudier une nouvelle zone d'implantation** potentielle à partir d'une adresse ou de coordonnées.
    """)