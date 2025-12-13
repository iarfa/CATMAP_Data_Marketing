# Fichier: pages/00_Home.py
import streamlit as st

# =============================================================================
# HEADER : POSITIONNEMENT
# =============================================================================

st.title("🌍 GeoRisk")
st.subheader("Intelligence Géospatiale & Risques Climatiques")

st.markdown("---")

st.markdown("""
**Bienvenue sur la plateforme décisionnelle.**

Cet outil fusionne l'analyse **Géomarketing** (Potentiel commercial) et l'analyse de **Risques** (Physiques & Transition) pour sécuriser vos investissements.

Il repose sur une architecture modulaire connectée à la base SIRENE et aux référentiels climatiques (DRIAS/GIEC).
""")

# =============================================================================
# ACCÈS RAPIDE (MODULES)
# =============================================================================

st.markdown("### 🚀 Modules d'Analyse")

col1, col2, col3, col4 = st.columns(4)

with col1:
    with st.container(border=True):
        st.markdown("#### 👥 Concurrence")
        st.caption("Analyse de Marché")
        st.write("Exploration du tissu économique (OSM & SIRENE).")
        st.page_link("pages/01_Analyse_Concurrence.py", label="Explorer", icon="📊")

with col2:
    with st.container(border=True):
        st.markdown("#### 📍 Implantation")
        st.caption("Diagnostic Local")
        st.write("Audit 360° d'un site : Socio, Bâti et Risques.")
        st.page_link("pages/02_Zone_Implantation.py", label="Auditer", icon="📍")

with col3:
    with st.container(border=True):
        st.markdown("#### 🌪️ Stress Test")
        st.caption("Horizon 2050")
        st.write("Modélisation des pertes financières (RCP 4.5 / 8.5).")
        st.page_link("pages/03_Stress_Test_Climat.py", label="Simuler", icon="📉")

with col4:
    with st.container(border=True):
        st.markdown("#### 💾 Données")
        st.caption("Utilitaire Data")
        st.write("Enrichissement massif de fichiers SIRET/SIREN.")
        st.page_link("pages/04_Enrichissement_Data.py", label="Enrichir", icon="✨")

st.markdown("---")

# =============================================================================
# FOOTER : MÉTHODOLOGIE & STATUS
# =============================================================================

with st.expander("ℹ️ Sources & Architecture Technique"):
    st.markdown("""
    **Stack Technique :**
    * **Backend :** Python 3.10, SQLAlchemy, Pandas (Optimized IO).
    * **Géo :** PostGIS, OpenRouteService (Docker), Geopandas.

    **Données Utilisées :**
    * 🛒 **Marché :** Base SIRENE (INSEE), DVF (Etalab).
    * 🌪️ **Risques :** Géorisques (MTE), Scénarios DRIAS 2020.
    """)