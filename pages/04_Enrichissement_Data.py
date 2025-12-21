# Fichier: pages/04_Enrichissement_Data.py
import streamlit as st
import pandas as pd
import time  # <--- AJOUT POUR LE CHRONO
from backend.database import connect_to_db
from backend.calculators import enrichir_dataframe_siren

# Pas de set_page_config ici car géré par le main.py

st.title("💾 Enrichissement Massif (SIREN/SIRET)")
st.markdown("""
    Cette interface permet d'enrichir une liste de **SIRET** ou **SIREN** avec les données officielles (Adresse, NAF, Effectifs, Lat/Lon...).
    Chargez votre fichier, sélectionnez la colonne identifiant, et lancez le traitement.
""")

engine = connect_to_db()

# 1. UPLOAD FICHIER (CSV ou EXCEL)
st.subheader("1. Chargement des données")
up = st.file_uploader("Glissez votre fichier ici (CSV ou Excel)", type=["csv", "xlsx", "xls"])

if up:
    try:
        # DÉTECTION DU TYPE DE FICHIER ET LECTURE
        filename = up.name.lower()
        df = pd.DataFrame()

        if filename.endswith(".csv"):
            c_sep, c_enc = st.columns(2)
            with c_sep:
                sep = st.selectbox(
                    "Séparateur (CSV)",
                    [";", ",", "\t", "|"],
                    index=0,
                    help="Si les colonnes sont mal séparées dans l'aperçu, changez cette option."
                )
            # Lecture CSV
            up.seek(0)
            df = pd.read_csv(up, sep=sep, dtype=str)

        elif filename.endswith((".xlsx", ".xls")):
            # Lecture Excel
            up.seek(0)
            df = pd.read_excel(up, dtype=str)

        # 2. APERÇU DU FICHIER
        if not df.empty:
            st.info(f"✅ Fichier chargé : {len(df)} lignes, {len(df.columns)} colonnes.")

            with st.expander("👁️ Aperçu des données (5 premières lignes)", expanded=True):
                st.dataframe(df.head())

            st.divider()

            # 3. CONFIGURATION ENRICHISSEMENT
            st.subheader("2. Configuration")

            c1, c2 = st.columns(2)
            with c1:
                col_id = st.selectbox(
                    "Quelle colonne contient l'identifiant (SIRET/SIREN) ?",
                    df.columns,
                    index=0
                )
            with c2:
                # Tentative de détection automatique
                default_type = 0
                sample_val = str(df[col_id].iloc[0]) if len(df) > 0 else ""
                if len(sample_val) == 9: default_type = 1

                type_id = st.radio(
                    "Type d'identifiant",
                    ["siret", "siren"],
                    index=default_type,
                    format_func=lambda x: x.upper()
                )

            st.caption("ℹ️ Le traitement peut prendre quelques secondes selon la taille du fichier.")

            # 4. LANCEMENT
            if st.button("🚀 Lancer l'enrichissement", type="primary"):
                if engine:
                    with st.spinner("Interrogation de la base de données en cours..."):
                        try:
                            # --- DÉBUT CHRONO ---
                            start_time = time.time()

                            # Appel de la fonction backend
                            found, not_found, rejected = enrichir_dataframe_siren(
                                engine, df, col_id, type_id
                            )

                            # --- FIN CHRONO ---
                            end_time = time.time()
                            duration = end_time - start_time

                            # RÉSULTATS
                            st.divider()
                            st.subheader("3. Résultats")

                            # On ajoute une 4ème colonne pour le temps
                            m1, m2, m3, m4 = st.columns(4)
                            m1.metric("✅ Trouvés", len(found))
                            m2.metric("❌ Introuvables", len(not_found))
                            m3.metric("⚠️ Rejetés", len(rejected))
                            m4.metric("⏱️ Temps", f"{duration:.2f} s")  # <--- AFFICHER LE TEMPS

                            if not found.empty:
                                st.success(f"Enrichissement terminé en {duration:.2f} secondes !")

                                # Préparation téléchargement
                                csv_data = found.to_csv(index=False, sep=";").encode('utf-8-sig')

                                st.download_button(
                                    label="📥 Télécharger le fichier enrichi (CSV)",
                                    data=csv_data,
                                    file_name=f"enrichi_{filename.split('.')[0]}.csv",
                                    mime="text/csv"
                                )

                                with st.expander("Voir les données enrichies"):
                                    st.dataframe(found.head(50))

                            if not not_found.empty:
                                with st.expander("Voir les identifiants introuvables"):
                                    st.dataframe(not_found)

                        except Exception as e:
                            st.error(f"Une erreur est survenue pendant l'enrichissement : {e}")
                else:
                    st.error("🚨 Base de données déconnectée. Vérifiez la connexion.")
        else:
            st.warning("Le fichier semble vide.")

    except Exception as e:
        st.error(f"Erreur de lecture du fichier : {e}")
        st.info("Vérifiez le format du fichier ou le séparateur sélectionné.")