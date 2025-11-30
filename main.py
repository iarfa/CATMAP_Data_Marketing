import streamlit as st

# 1. Configuration Globale (doit être la 1ère commande Streamlit)
st.set_page_config(
    page_title="CATMAP Data",
    page_icon="🌍",
    layout="wide"
)

# 2. Définition des Pages
# On déclare chaque fichier ici

page_accueil = st.Page(
    "pages/00_Home.py",
    title="Accueil",
    icon="🏠",
    default=True
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


page_stress_test = st.Page(
    "pages/04_Stress_Test_Climat.py",  # Le chemin exact de votre fichier
    title="Stress Test Climat",        # Le titre dans le menu
    icon="📉"                          # Icône pertinente
)

# 3. Création de la Navigation
# On ajoute la variable 'page_stress_test' dans la liste
pg = st.navigation({
    "Menu Principal": [page_accueil],
    "Outils d'Analyse": [
        page_concurrence,
        page_implantation,
        page_enrichissement,
        page_stress_test  # <--- C'EST ICI QU'ON L'ACTIVE
    ]
})

# 4. Lancement
pg.run()