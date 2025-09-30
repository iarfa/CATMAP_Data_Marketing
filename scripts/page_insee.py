# =======================
# 📦 Imports & Librairies
# =======================
import streamlit as st
from streamlit_folium import st_folium
from fonctions_basiques import (
    charger_etablissements,
    charger_centres_departements,
    filtrer_donnees
)
from fonctions_cartographie import (
    creer_carte_insee
)
from interface import (
    interface_apercu_donnees,
    interface_filtres_insee,
    interface_choix_departement_insee,
    interface_choix_affichage_insee
)


# =======================
# 📄 Fonction principale de la page INSEE
# =======================
def page_insee(path_etablissement, path_centres_departements):
    """
    Orchestre l'affichage de la page d'analyse des données INSEE.
    Le flux est séquentiel : chargement, filtrage, puis cartographie.
    """

    st.header("📊 Analyse des données INSEE")

    # --- Étape 1 : Chargement des données ---
    df_etablissements = charger_etablissements(path_etablissement)
    df_centres_dep = charger_centres_departements(path_centres_departements)

    if df_etablissements.empty or df_centres_dep.empty:
        st.warning("Le chargement d'un ou plusieurs fichiers de données a échoué. Impossible d'afficher la page.")
        return

    # --- Étape 2 : Aperçu des données brutes ---
    interface_apercu_donnees(df_etablissements, 3)

    # --- Étape 3 : Interface de filtrage ---
    choix_categories, choix_villes = interface_filtres_insee(df_etablissements)

    # --- Étape 4 : Logique de filtrage ---
    df_etablissements_filtre = filtrer_donnees(df_etablissements, choix_categories, choix_villes)

    # Affichage d'un résumé des données filtrées
    st.write(f"Résultat du filtrage : **{len(df_etablissements_filtre)} établissement(s)** trouvé(s).")
    if st.checkbox("Afficher le tableau des données filtrées"):
        st.dataframe(df_etablissements_filtre)

    st.markdown("---")

    # --- Étape 5 : Interface et logique de la carte ---
    if not df_etablissements_filtre.empty:
        departement_choisi, lat_centre, lon_centre = interface_choix_departement_insee(
            df_etablissements_filtre, df_centres_dep
        )

        mode, rayon, temps = interface_choix_affichage_insee()

        carte_insee = creer_carte_insee(
            data=df_etablissements_filtre,
            lat_centre=lat_centre,
            lon_centre=lon_centre,
            mode_affichage=mode,
            rayon_m=rayon,
            temps_min=temps
        )

        # --- Étape 6 : Affichage de la carte ---
        if carte_insee:
            st_folium(carte_insee, width=800, height=600)
    else:
        st.info("Aucun établissement ne correspond à vos filtres. La carte ne peut pas être affichée.")