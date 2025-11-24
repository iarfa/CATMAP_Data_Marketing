# Fichier: main.py
import streamlit as st

# 1. Configuration Globale (doit être la 1ère commande Streamlit)
st.set_page_config(
    page_title="CATMAP Data",
    page_icon="🌍",
    layout="wide"
)

# 2. Définition des Pages (C'est ici qu'on renomme !)
# On mappe le fichier physique -> vers -> le Nom affiché dans le menu

page_accueil = st.Page(
    "pages/00_Home.py",       # Fichier réel
    title="Accueil",          # Nom affiché dans le menu 👈
    icon="🏠",                # Icône du menu
    default=True              # C'est la page par défaut
)

page_concurrence = st.Page(
    "pages/01_Analyse_Concurrence.py",
    title="Analyse Concurrence",
    icon="📊"
)

page_implantation = st.Page(
    "pages/02_Zone_Implantation.py",
    title="Zone d'Implantation",
    icon="📍"
)

page_enrichissement = st.Page(
    "pages/03_Enrichissement_Data.py",
    title="Enrichissement Data",
    icon="💾"
)

# 3. Création de la Navigation
pg = st.navigation({
    "Menu Principal": [page_accueil],
    "Outils d'Analyse": [page_concurrence, page_implantation, page_enrichissement]
})

# 4. Lancement
pg.run()