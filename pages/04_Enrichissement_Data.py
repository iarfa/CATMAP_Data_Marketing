# Fichier: pages/04_Enrichissement_Data.py
import streamlit as st
import pandas as pd
from backend.database import connect_to_db
from backend.calculators import enrichir_dataframe_siren

st.title("💾 Enrichissement Massif (SIRENE)")

engine = connect_to_db()

up = st.file_uploader("Fichier CSV (avec colonne SIRET ou SIREN)", type=["csv"])

if up:
    df = pd.read_csv(up)

    c1, c2 = st.columns(2)
    col_id = c1.selectbox("Colonne ID", df.columns)
    type_id = c2.radio("Type", ["siret", "siren"])

    if st.button("Lancer l'enrichissement"):
        if engine:
            found, not_found, rejected = enrichir_dataframe_siren(
                engine, df, col_id, type_id
            )

            st.success(f"{len(found)} lignes enrichies !")
            st.warning(f"{len(not_found)} introuvables.")

            st.download_button(
                "Télécharger Résultat",
                found.to_csv(index=False).encode('utf-8'),
                "enrichi.csv"
            )
        else:
            st.error("Base de données déconnectée.")