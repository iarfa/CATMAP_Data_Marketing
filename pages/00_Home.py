# Fichier: pages/00_Home.py

import streamlit as st

# =============================================================================
# HEADER : POSITIONNEMENT HYBRIDE
# =============================================================================

st.title("🌍 GeoMarket & Risk")
st.subheader("L'intelligence géographique au service de la performance et de la résilience")

st.markdown("---")

# Pitch : L'équilibre entre Business et Risque
st.markdown("""
**Bienvenue sur votre plateforme d'aide à la décision.**

Dans un environnement incertain, la réussite d'une implantation ne dépend plus seulement de son potentiel commercial, mais aussi de sa durabilité.
**GeoMarket & Risk** réconcilie ces deux enjeux :

1.  **L'Offensive (Géomarketing)** : Détecter les meilleures opportunités de marché.
2.  **La Défensive (Risques)** : Anticiper les impacts climatiques et sécuriser la valeur des actifs.
""")

# =============================================================================
# LES PILIERS DE LA SOLUTION
# =============================================================================

st.markdown("### 🎯 Une vision à 360°")

c1, c2, c3 = st.columns(3)

with c1:
    st.image("https://img.icons8.com/fluency/96/bullish.png", width=70)
    st.markdown("#### 1. Potentiel Marché")
    st.write("""
    Analysez la dynamique locale pour valider vos choix d'implantation.
    * **Concurrence & Cannibalisation**
    * **Sociodémographie (INSEE)**
    * **Marché Immobilier (DVF)**
    """)

with c2:
    st.image("https://img.icons8.com/fluency/96/shield.png", width=70)
    st.markdown("#### 2. Maîtrise des Risques")
    st.write("""
    Identifiez les vulnérabilités physiques de chaque emplacement.
    * **Inondation & Sécheresse**
    * **Risques Incendie & Chaleur**
    * **Audit à la parcelle**
    """)

with c3:
    st.image("https://img.icons8.com/fluency/96/money-bag-euro.png", width=70)
    st.markdown("#### 3. Impact Financier")
    st.write("""
    Traduisez les risques climatiques en indicateurs économiques.
    * **Valorisation de Portefeuille (TIV)**
    * **Coût des Dommages (Expected Loss)**
    * **Risque de Transition (Carbone)**
    """)

st.markdown("---")

# =============================================================================
# MENU D'ACCÈS RAPIDE (4 MODULES)
# =============================================================================

st.subheader("🚀 Lancer une analyse")

# On passe à 4 colonnes pour inclure l'Enrichissement
col1, col2, col3, col4 = st.columns(4)

with col1:
    with st.container(border=True):
        st.markdown("#### 📊 Concurrence")
        st.caption("Analyse de marché")
        st.write("Exploration du tissu économique local.")
        st.page_link("pages/01_Analyse_Concurrence.py", label="Explorer", icon="👥")

with col2:
    with st.container(border=True):
        st.markdown("#### 📍 Diagnostic")
        st.caption("Site Unique")
        st.write("Audit complet d'une adresse (Potentiel & Risque).")
        st.page_link("pages/02_Zone_Implantation.py", label="Auditer", icon="🛡️")

with col3:
    with st.container(border=True):
        st.markdown("#### 📉 Stress Test")
        st.caption("Portefeuille")
        st.write("Quantification financière des risques climatiques.")
        st.page_link("pages/04_Stress_Test_Climat.py", label="Simuler", icon="🌪️")

with col4:
    with st.container(border=True):
        st.markdown("#### 💾 Données")
        st.caption("Utilitaire")
        st.write("Enrichissement, SIRETisation et Géocodage.")
        st.page_link("pages/03_Enrichissement_Data.py", label="Enrichir", icon="✨")

st.markdown("---")

# =============================================================================
# FOOTER : MÉTHODOLOGIE
# =============================================================================

with st.expander("ℹ️ Sources de Données & Transparence"):
    st.markdown("""
    **Une approche basée sur la donnée souveraine (Open Data) :**

    * **Marché :** Base SIRENE (INSEE), Valeurs Foncières (Etalab).
    * **Territoire :** Données carroyées (INSEE), OpenStreetMap (Bâti/Forêt).
    * **Climat :** Géorisques (MTE), Scénarios DRIAS (Météo-France).
    """)