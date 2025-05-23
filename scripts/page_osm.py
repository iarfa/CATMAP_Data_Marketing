# =======================
# 📦 Imports & Librairies
# =======================
import streamlit as st
from fonctions_basiques import extraction_adresse_OSM, choix_centre_OSM
from fonctions_cartographie import (
    interface_recherche_osm,
    transfo_geodataframe,
    choix_carte_osm
)

# Page OSM
def page_osm():
    """
    Page dédiée à l'affichage des cartes OSM.
    """
    st.header("🗺️ Analyse via OpenStreetMap")

    # Appel unique de la recherche (gère automatiquement session_state)
    df_etablissements_osm = interface_recherche_osm()

    if df_etablissements_osm is not None and not df_etablissements_osm.empty:

        # Affichage du tableau
        st.dataframe(df_etablissements_osm)

        # Traitements
        df_etablissements_osm[["adresse_simplifiee", "precision_geocodage"]] = df_etablissements_osm.apply(
            extraction_adresse_OSM, axis=1
        )

        lat_centre_OSM, lon_centre_OSM = choix_centre_OSM(df_etablissements_osm)

        gdf_etablissements_osm = transfo_geodataframe(
            df_etablissements_osm,
            longitude_col="longitude",
            latitude_col="latitude",
            crs="EPSG:4326"
        )

        # Affichage carte
        choix_carte_osm(df_etablissements_osm, lat_centre_OSM, lon_centre_OSM)

    else:
        st.info("Veuillez effectuer une recherche pour afficher les établissements sur la carte.")