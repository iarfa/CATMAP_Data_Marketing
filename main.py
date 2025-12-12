# Fichier: main.py
import streamlit as st

# 1. Configuration Globale (doit être la 1ère commande)
st.set_page_config(page_title="CATMAP Data", page_icon="🌍", layout="wide")

# 2. Définition des Pages
page_accueil = st.Page("pages/00_Home.py", title="Accueil", icon="🏠", default=True)

page_concurrence = st.Page("pages/01_Analyse_Concurrence.py", title="Analyse Concurrence", icon="📊")
page_implantation = st.Page("pages/02_Zone_Implantation.py", title="Zone d'Implantation", icon="📍")
page_stress_test = st.Page("pages/03_Stress_Test_Climat.py", title="Stress Test Climat", icon="🌪️")
page_enrichissement = st.Page("pages/04_Enrichissement_Data.py", title="Enrichissement Data", icon="💾")

# 3. Création de la Navigation
pg = st.navigation({
    "Menu Principal": [page_accueil],
    "Outils d'Analyse": [
        page_concurrence,
        page_implantation,
        page_stress_test,
        page_enrichissement
    ]
})

pg.run()