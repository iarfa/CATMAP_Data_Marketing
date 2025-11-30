# Fichier: pages/04_Stress_Test_Climat.py

import streamlit as st
import pandas as pd
import geopandas as gpd
import plotly.express as px
import folium
from streamlit_folium import st_folium
import numpy as np

# --- IMPORTS MÉTIERS (BACKEND) ---
from fonctions_basiques import (
    charger_zones_inondables,
    charger_donnees_rga,
    estimer_valeur_portefeuille,
    calculer_pertes_sectorielles,
    estimer_empreinte_carbone
)
from fonctions_cartographie import geocoder_adresse_nominatim_ui

# --- CONFIGURATION ---
PATH_ZONES_INONDABLES = "data/zones_inondables_v2.parquet"
PATH_RGA_SECHERESSE = "data/rga_secheresse_v2.parquet"

# =============================================================================
# EN-TÊTE : PLATEFORME INTEGRÉE
# =============================================================================
st.title("📉 Stress Test Climatique & Financier")
st.markdown("""
**Plateforme de Quantification des Risques (Physical Risk Pricing Engine)**
Analyse d'impact financier selon les projections climatiques du GIEC (Scénarios DRIAS-2020).
""")

# =============================================================================
# SIDEBAR : HYPOTHÈSES DE SCÉNARIO
# =============================================================================
with st.sidebar:
    st.header("1. Import Portefeuille")
    st.info("Format : CSV/Excel (Adresses ou GPS).")
    uploaded_file = st.file_uploader("Charger le fichier", type=["csv", "xlsx"])

    st.divider()

    st.header("2. Hypothèses Financières")
    cout_construction = st.number_input("Coût Reconstruction (€/m²)", 500, 10000, 2000, step=100)

    # Vocabulaire adapté : "Taxe Carbone Simulée" au lieu de Shadow Price
    prix_tonne_co2 = st.number_input(
        "Taxe Carbone Simulée (€/tCO2)",
        min_value=0, max_value=1000, value=100, step=10,
        help="Prix interne du carbone pour anticiper le risque réglementaire."
    )

    st.divider()

    st.header("3. Scénarios Climatiques")
    scenario_climat = st.radio(
        "Horizon de Projection (IPCC) :",
        ["Reference (Actuel)", "RCP 4.5 (2050)", "RCP 8.5 (Extrême)"],
        help="Projection des aléas Inondation, Sécheresse et Indice Forêt Météo (IFM)."
    )

    # Légende scientifique dynamique
    if "Reference" in scenario_climat:
        st.info("✅ **Baseline 2024**\nCartographie réglementaire actuelle.")
    elif "RCP 4.5" in scenario_climat:
        st.warning("⚠️ **Horizon 2050 (+2°C)**\nAggravation Inondation (+20%) et Risque Feu (+30%).")
    else:
        st.error("🚨 **Horizon 2080 (+4°C)**\nExtension Crues, Sécheresse généralisée et Risque Méga-feux (+60%).")

# =============================================================================
# MAIN : RISK ENGINE
# =============================================================================

if uploaded_file:
    # --- A. CHARGEMENT ---
    try:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
        df.columns = [c.lower().strip() for c in df.columns]
    except Exception as e:
        st.error(f"Erreur : {e}"); st.stop()

    # --- B. MAPPING ---
    with st.expander("🛠️ Configuration des Données", expanded=False):
        c1, c2, c3 = st.columns(3)
        cols = list(df.columns)


        def get_idx(patterns):
            for i, col in enumerate(cols):
                if any(p in col for p in patterns): return i
            return 0


        col_lat = c1.selectbox("Latitude", [None] + cols, index=get_idx(['lat']) + 1 if get_idx(['lat']) else 0)
        col_lon = c2.selectbox("Longitude", [None] + cols, index=get_idx(['lon']) + 1 if get_idx(['lon']) else 0)
        col_naf = c3.selectbox("Code NAF", [None] + cols,
                               index=get_idx(['naf', 'ape']) + 1 if get_idx(['naf', 'ape']) else 0,
                               help="Sert à la pondération sectorielle (Vulnérabilité).")

        col_addr = next((c for c in cols if 'adress' in c or 'rue' in c), None)
        col_nom = next((c for c in cols if 'nom' in c or 'societe' in c), None)

        # Mapping Optionnel pour l'Incendie
        col_dist_foret = st.selectbox("Distance Forêt (Optionnel)", [None] + cols,
                                      index=get_idx(['foret', 'bois']) + 1 if get_idx(['foret', 'bois']) else 0)

    # --- C. VALORISATION ---
    df = estimer_valeur_portefeuille(df, cout_m2_defaut=cout_construction)
    tiv_totale = df['valeur_assuree'].sum()

    # --- D. GÉOCODAGE ---
    if not (col_lat and col_lon):
        if col_addr:
            with st.status("Géocodage en cours...", expanded=True):
                lats, lons = [], []
                for i, row in df.iterrows():
                    res = geocoder_adresse_nominatim_ui(str(row[col_addr]))
                    if res:
                        lats.append(res['latitude']); lons.append(res['longitude'])
                    else:
                        lats.append(None); lons.append(None)
                df['latitude'], df['longitude'] = lats, lons
                df = df.dropna(subset=['latitude'])
        else:
            st.error("Pas de coordonnées."); st.stop()
    else:
        df = df.rename(columns={col_lat: 'latitude', col_lon: 'longitude'})

    # --- E. PROJECTION ALÉAS (SPATIAL JOIN) ---
    with st.spinner(f"Modélisation des impacts ({scenario_climat})..."):
        gdf_points = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.longitude, df.latitude), crs="EPSG:4326")

        gdf_inond = charger_zones_inondables(PATH_ZONES_INONDABLES)
        gdf_rga = charger_donnees_rga(PATH_RGA_SECHERESSE)

        # Simulation Extension RCP 8.5 (Physique)
        if "RCP 8.5" in scenario_climat and not gdf_inond.empty:
            gdf_inond['geometry'] = gdf_inond.buffer(0.001)  # Buffer ~100m

        if not gdf_inond.empty:
            gdf_points = gpd.sjoin(gdf_points, gdf_inond[['NIVEAU_ALEA', 'geometry']], how='left', predicate='within')
            gdf_points = gdf_points.rename(columns={'NIVEAU_ALEA': 'alea_inondation'})
            gdf_points = gdf_points[~gdf_points.index.duplicated(keep='first')]
        else:
            gdf_points['alea_inondation'] = None

        if not gdf_rga.empty:
            if 'index_right' in gdf_points.columns: gdf_points = gdf_points.drop(columns=['index_right'])
            gdf_points = gpd.sjoin(gdf_points, gdf_rga[['NIVEAU_ALEA', 'geometry']], how='left', predicate='within')
            gdf_points = gdf_points.rename(columns={'NIVEAU_ALEA': 'alea_secheresse'})
            gdf_points = gdf_points[~gdf_points.index.duplicated(keep='first')]
        else:
            gdf_points['alea_secheresse'] = None

    # --- F. CALCUL FINANCIER COMPLET ---

    # 1. Base Inondation/Sécheresse (avec Vulnérabilité NAF)
    gdf_res = calculer_pertes_sectorielles(gdf_points, scenario_climat, col_naf=col_naf)

    # 2. Moteur Incendie (Indexé sur RCP)
    taux_base_feu = 0.50
    facteur_fwi = 1.0
    if "RCP 4.5" in scenario_climat: facteur_fwi = 1.3
    if "RCP 8.5" in scenario_climat: facteur_fwi = 1.6

    pertes_incendie_liste = []
    causes_principales = []

    for idx, row in gdf_res.iterrows():
        val = row['valeur_assuree']
        perte_existante = row['perte_estimee']
        coef_vuln = row.get('coef_vulnerabilite', 1)

        # Calcul Feu
        perte_feu = 0
        is_exposed_fire = False
        if col_dist_foret and col_dist_foret != "None" and pd.notnull(row.get(col_dist_foret)):
            try:
                if float(row[col_dist_foret]) < 50: is_exposed_fire = True
            except:
                pass

        if is_exposed_fire:
            # Perte = Valeur * (Taux Base * Aggravation Climat * Vulnérabilité Secteur)
            perte_feu = val * min(taux_base_feu * facteur_fwi * coef_vuln, 1.0)

        pertes_incendie_liste.append(perte_feu)

        # Arbitrage "Max Loss"
        perte_finale = max(perte_existante, perte_feu)
        gdf_res.at[idx, 'perte_estimee'] = perte_finale

        # Identification de la cause
        if perte_finale == 0:
            causes_principales.append("Sain")
        elif perte_finale == perte_feu:
            causes_principales.append("🔥 Incendie")
        elif perte_finale == row.get('perte_inondation', 0):
            causes_principales.append("🌊 Inondation")
        else:
            causes_principales.append("☀️ Sécheresse")

    gdf_res['Cause_Dominante'] = causes_principales

    # 3. Transition (Carbone)
    gdf_res = estimer_empreinte_carbone(gdf_res, col_naf=col_naf)

    # Totaux
    el_physique = gdf_res['perte_estimee'].sum()
    cout_carbone = gdf_res['emission_tco2'].sum() * prix_tonne_co2
    ratio_sinistre = (el_physique / tiv_totale * 100) if tiv_totale > 0 else 0

    # =============================================================================
    # DASHBOARD
    # =============================================================================
    st.divider()

    # KPI
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Exposition (TIV)", f"{tiv_totale / 1e6:.1f} M€")
    k2.metric("Pertes Physiques (EL)", f"{el_physique / 1e6:.2f} M€", help="Inondation + Sécheresse + Incendie")
    k3.metric("Ratio Sinistralité", f"{ratio_sinistre:.2f} %", delta="Impact Bilan", delta_color="inverse")
    k4.metric("Coût Total Risque", f"{(el_physique + cout_carbone) / 1e6:.2f} M€",
              help="Physique + Taxe Carbone Simulée")

    # Feu Tricolore
    col_dec, _ = st.columns([1, 1])
    with col_dec:
        if ratio_sinistre < 2:
            st.success("✅ **RISQUE FAIBLE** - Octroi Standard")
        elif ratio_sinistre < 10:
            st.warning("🟠 **RISQUE MODÉRÉ** - Mitigation requise")
        else:
            st.error("🚨 **RISQUE CRITIQUE** - Escalade Comité")

    st.markdown("---")

    tab_phys, tab_trans = st.tabs(["🌪️ Risque Physique (Multi-Périls)", "🌍 Risque de Transition (Carbone)"])

    # --- ONGLET 1 : PHYSIQUE ---
    with tab_phys:
        # Ligne 1 : Carte + Camembert
        c_map, c_data = st.columns([1.5, 1])

        with c_map:
            st.subheader("Cartographie des Aléas")
            lat_c = gdf_res.latitude.mean()
            lon_c = gdf_res.longitude.mean()
            m = folium.Map(location=[lat_c, lon_c], zoom_start=5, tiles="CartoDB positron")

            for _, row in gdf_res.iterrows():
                loss = row['perte_estimee']
                label = str(row[col_nom]) if col_nom and pd.notnull(row[col_nom]) else "Site"
                cause = row['Cause_Dominante']

                if loss > 0:
                    color = '#d62728'
                    if "Incendie" in cause:
                        color = '#d65f5f'
                    elif "Inondation" in cause:
                        color = '#1f77b4'
                    elif "Sécheresse" in cause:
                        color = '#e377c2'

                    folium.CircleMarker(
                        [row.geometry.y, row.geometry.x], radius=6, color=color, fill=True, fill_opacity=0.8,
                        popup=f"<b>{label}</b><br>Perte: {loss:,.0f}€<br>Cause: {cause}"
                    ).add_to(m)
                else:
                    folium.CircleMarker([row.geometry.y, row.geometry.x], radius=3, color='#2ca02c', fill=True).add_to(
                        m)
            st_folium(m, width=None, height=400)

        with c_data:
            st.subheader("Répartition par Péril")
            df_loss = gdf_res[gdf_res['perte_estimee'] > 0]
            if not df_loss.empty:
                fig_cause = px.pie(df_loss, values='perte_estimee', names='Cause_Dominante', hole=0.4,
                                   color_discrete_map={"🔥 Incendie": "#d65f5f", "🌊 Inondation": "#1f77b4",
                                                       "☀️ Sécheresse": "#e377c2"})
                fig_cause.update_layout(showlegend=False, margin=dict(t=0, b=0, l=0, r=0), height=250)
                st.plotly_chart(fig_cause, use_container_width=True)

                st.info(f"**Péril Dominant :** {df_loss.groupby('Cause_Dominante')['perte_estimee'].sum().idxmax()}")
            else:
                st.success("Aucun sinistre modélisé.")

        # Ligne 2 : TABLEAU DÉTAILLÉ (DANS UN EXPANDER)
        st.markdown("---")
        with st.expander("📋 Voir le détail des Actifs Critiques (Tableau)", expanded=True):
            df_risk = gdf_res[gdf_res['perte_estimee'] > 0].sort_values('perte_estimee', ascending=False)

            if not df_risk.empty:
                df_show = df_risk.copy()
                df_show['Actif'] = df_show.apply(
                    lambda r: str(r[col_nom]) if col_nom and pd.notnull(r[col_nom]) else str(r[col_addr]), axis=1)
                df_show['% Destruction'] = (df_show['perte_estimee'] / df_show['valeur_assuree'] * 100).round(1)

                # Sélection et renommage
                df_final = df_show[[
                    'Actif', 'Cause_Dominante', 'valeur_assuree',
                    'coef_vulnerabilite', '% Destruction', 'perte_estimee'
                ]].rename(columns={
                    'valeur_assuree': 'Valeur (€)',
                    'Cause_Dominante': 'Péril',
                    'coef_vulnerabilite': 'Vuln. Secteur',
                    'perte_estimee': 'Perte (€)'
                })

                # Configuration Dataframe riche
                st.dataframe(
                    df_final,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Valeur (€)": st.column_config.NumberColumn(format="%.0f €"),
                        "Perte (€)": st.column_config.NumberColumn(format="%.0f €"),
                        "% Destruction": st.column_config.ProgressColumn(
                            format="%.1f%%", min_value=0, max_value=100,
                            help="Taux de destruction du bâti."
                        ),
                        "Péril": st.column_config.TextColumn(width="small"),
                        "Vuln. Secteur": st.column_config.NumberColumn(format="x %.1f")
                    }
                )
            else:
                st.info("Le portefeuille est sain. Aucun actif ne dépasse le seuil de perte.")

        # --- AJOUT NOTE METHODOLOGIQUE (NAF) ---
        st.markdown("---")
        with st.expander("ℹ️ Note Méthodologique : Comprendre la Vulnérabilité Sectorielle (NAF)"):
            st.markdown("""
            **Pourquoi pondérer le risque par le secteur d'activité ?**
            L'impact financier d'un aléa climatique ne dépend pas uniquement de l'exposition géographique, mais aussi de la sensibilité de l'activité.

            Notre modèle applique un **Coefficient de Vulnérabilité** basé sur le Code NAF :

            | Typologie d'Activité | Code NAF (Exemples) | Coefficient | Justification Économique |
            | :--- | :--- | :--- | :--- |
            | **🔴 Industrie / BTP** | 10-33, 41-43 | **x 1.5** (Aggravant) | Présence de machines lourdes, stocks matières, dépendance au site. |
            | **🟠 Commerce / Logistique** | 45-47, 49-53 | **x 1.2** (Modéré) | Perte de stocks, fermeture obligatoire, interruption logistique. |
            | **🟢 Services / Tertiaire** | 64-66, 69-70 | **x 0.8** (Atténuant) | Actifs immatériels, possibilité de télétravail (PCA). |

            *Formule : Perte (€) = Valeur Actif × Taux Destruction Physique × Coef. Vulnérabilité*
            """)

    # --- ONGLET 2 : TRANSITION ---
    with tab_trans:
        c_t1, c_t2 = st.columns(2)
        with c_t1:
            st.subheader("Green vs Brown")
            if 'categorie_transition' in gdf_res.columns:
                df_cat = gdf_res.groupby('categorie_transition')['valeur_assuree'].sum().reset_index()
                colors = {'🟤 Brun (Intensif)': '#8c564b', '🟠 Mixte (Standard)': '#ff7f0e',
                          '🟢 Vert (Bas Carbone)': '#2ca02c'}
                fig_pie = px.pie(df_cat, values='valeur_assuree', names='categorie_transition',
                                 color='categorie_transition', color_discrete_map=colors, hole=0.4)
                st.plotly_chart(fig_pie, use_container_width=True)
                st.info(f"Coût Latent (Taxe) : **{cout_carbone:,.0f} €**")
            else:
                st.warning("Données manquantes.")

        with c_t2:
            st.subheader("Émissions par Secteur")
            if col_naf:
                df_sec = gdf_res.groupby(col_naf)[['emission_tco2', 'valeur_assuree']].sum().reset_index()
                fig_bar = px.bar(df_sec.sort_values('emission_tco2'), x='emission_tco2', y=col_naf, orientation='h',
                                 title="tCO2e")
                st.plotly_chart(fig_bar, use_container_width=True)
            else:
                st.info("Sélecteur NAF requis.")

    # EXPORT
    st.divider()
    csv = gdf_res.drop(columns='geometry').to_csv(index=False, sep=';').encode('utf-8-sig')
    st.download_button("📥 Télécharger le Rapport Audit", csv, "audit_risk.csv", "text/csv", type="primary")

else:
    st.info("👋 Chargez un portefeuille pour l'analyse multi-périls.")