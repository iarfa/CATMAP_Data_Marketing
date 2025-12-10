# Fichier: pages/04_Stress_Test_Climat.py

import streamlit as st
import pandas as pd
import geopandas as gpd
import plotly.express as px
import folium
from streamlit_folium import st_folium
from shapely.geometry import shape, box

# --- IMPORTS MÉTIERS (BACKEND) ---
from fonctions_basiques import (
    charger_zones_inondables,
    charger_donnees_rga,
    estimer_valeur_portefeuille,
    calculer_pertes_sectorielles,
    estimer_empreinte_carbone,
    projeter_climat_2050  # Import du simulateur
)
from fonctions_cartographie import (
    geocoder_adresse_nominatim_ui,
    analyser_locomotives  # Import pour l'onglet business
)

# --- CONFIGURATION ---
PATH_ZONES_INONDABLES = "data/zones_inondables_v2.parquet"
PATH_RGA_SECHERESSE = "data/rga_secheresse_v2.parquet"

# =============================================================================
# EN-TÊTE
# =============================================================================
st.title("📉 Stress Test Climatique & Business")
st.markdown("""
**Risk Pricing Engine :** Analyse d'impact financier, projection physique 2050 et audit business des actifs critiques.
""")

# =============================================================================
# SIDEBAR
# =============================================================================
with st.sidebar:
    st.header("1. Import Portefeuille")
    st.info("Format : CSV/Excel (Adresses ou GPS).")
    uploaded_file = st.file_uploader("Charger le fichier", type=["csv", "xlsx"])

    st.divider()

    st.header("2. Hypothèses")
    cout_construction = st.number_input("Coût Reconstruction (€/m²)", 500, 10000, 2000, step=100)
    prix_tonne_co2 = st.number_input("Taxe Carbone (€/tCO2)", 0, 1000, 100, step=10)

    st.divider()

    st.header("3. Scénarios GIEC")
    scenario_climat = st.radio(
        "Horizon de Projection :",
        ["Reference (Actuel)", "RCP 4.5 (2050)", "RCP 8.5 (Extrême)"]
    )

    if "4.5" in scenario_climat:
        scen_key = "RCP 4.5"
    elif "8.5" in scenario_climat:
        scen_key = "RCP 8.5"
    else:
        scen_key = "Reference"

# =============================================================================
# MAIN : MOTEUR DE CALCUL
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
        st.error(f"Erreur : {e}");
        st.stop()

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
                               index=get_idx(['naf', 'ape']) + 1 if get_idx(['naf', 'ape']) else 0)
        col_nom = next((c for c in cols if 'nom' in c or 'societe' in c or 'ville' in c), None)
        col_addr = next((c for c in cols if 'adress' in c or 'rue' in c), None)
        col_dist_foret = st.selectbox("Distance Forêt (Optionnel)", [None] + cols,
                                      index=get_idx(['foret', 'bois']) + 1 if get_idx(['foret', 'bois']) else 0)

    # --- B. PRÉPARATION ---
    df = estimer_valeur_portefeuille(df, cout_m2_defaut=cout_construction)
    tiv_totale = df['valeur_assuree'].sum()

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
            st.error("Pas de coordonnées.");
            st.stop()
    else:
        df = df.rename(columns={col_lat: 'latitude', col_lon: 'longitude'})

    # --- C. CALCULS ---
    with st.spinner(f"Modélisation des impacts ({scenario_climat})..."):
        gdf_points = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.longitude, df.latitude), crs="EPSG:4326")

        gdf_inond = charger_zones_inondables(PATH_ZONES_INONDABLES)
        gdf_rga = charger_donnees_rga(PATH_RGA_SECHERESSE)

        if "RCP 8.5" in scenario_climat and not gdf_inond.empty:
            gdf_inond['geometry'] = gdf_inond.buffer(0.001)

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
                perte_feu = val * min(taux_base_feu * facteur_fwi * coef_vuln, 1.0)

            pertes_incendie_liste.append(perte_feu)

            perte_finale = max(perte_existante, perte_feu)
            gdf_res.at[idx, 'perte_estimee'] = perte_finale

            if perte_finale == 0:
                causes_principales.append("Sain")
            elif perte_finale == perte_feu:
                causes_principales.append("🔥 Incendie")
            elif perte_finale == row.get('perte_inondation', 0):
                causes_principales.append("🌊 Inondation")
            else:
                causes_principales.append("☀️ Sécheresse")

        gdf_res['Cause_Dominante'] = causes_principales
        gdf_res = estimer_empreinte_carbone(gdf_res, col_naf=col_naf)

        # 3. PROJECTION PHYSIQUE 2050 (Simulateur)
        liste_climat = []
        for idx, row in gdf_res.iterrows():
            if scen_key != "Reference":
                projections = projeter_climat_2050(row.geometry.y, row.geometry.x)
                liste_climat.append(projections.get(scen_key, {}))
            else:
                liste_climat.append({"Jours Canicule": 0, "Nuits Tropicales": 0, "Sécheresse Sol": 0})

        df_climat = pd.DataFrame(liste_climat)
        gdf_res = pd.concat([gdf_res.reset_index(drop=True), df_climat.reset_index(drop=True)], axis=1)

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
    k2.metric("Pertes Financières", f"{el_physique / 1e6:.2f} M€", help="Perte annuelle estimée")
    k3.metric("Ratio Sinistralité", f"{ratio_sinistre:.2f} %", delta_color="inverse")
    k4.metric("Coût Carbone", f"{cout_carbone / 1e6:.2f} M€")

    # KPIs Physiques (Moyennes)
    if scen_key != "Reference":
        st.caption(f"Impacts Physiques Moyens ({scen_key})")
        p1, p2, p3 = st.columns(3)
        p1.metric("🌡️ Canicule", f"+{gdf_res['Jours Canicule'].mean():.0f} j/an", delta="Surchauffe")
        p2.metric("🌙 Nuits Trop.", f"+{gdf_res['Nuits Tropicales'].mean():.0f} j/an", delta="Confort")
        p3.metric("🌵 Sécheresse Sol", f"+{gdf_res['Sécheresse Sol'].mean():.0f} %", delta="Déficit Eau")

    st.markdown("---")

    # ONGLETS (RESTAURÉS + NOUVEAU)
    tab_phys, tab_trans, tab_audit = st.tabs(
        ["🌪️ Risque Physique", "🌍 Transition (Carbone)", "🚨 Audit Business (Locomotives)"])

    # --- ONGLET 1 : PHYSIQUE (RESTAURÉ) ---
    with tab_phys:
        c_map, c_data = st.columns([1.5, 1])
        with c_map:
            st.subheader("Cartographie des Aléas")
            lat_c, lon_c = gdf_res.latitude.mean(), gdf_res.longitude.mean()
            m = folium.Map(location=[lat_c, lon_c], zoom_start=5, tiles="CartoDB positron")
            for _, row in gdf_res.iterrows():
                loss = row['perte_estimee']
                label = str(row[col_nom]) if col_nom else "Site"
                cause = row['Cause_Dominante']

                # Couleur selon cause
                color = '#2ca02c'  # Vert (Sain)
                if loss > 0:
                    if "Incendie" in cause:
                        color = '#d65f5f'
                    elif "Inondation" in cause:
                        color = '#1f77b4'
                    elif "Sécheresse" in cause:
                        color = '#e377c2'

                # Popup enrichie (Climat 2050)
                popup_txt = f"""
                <b>{label}</b><br>
                💰 Perte: {loss:,.0f}€<br>
                🌡️ Canicule: +{row.get('Jours Canicule', 0)}j
                """
                folium.CircleMarker(
                    [row.geometry.y, row.geometry.x], radius=6 if loss > 0 else 3,
                    color=color, fill=True, fill_opacity=0.8, popup=popup_txt
                ).add_to(m)
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
            else:
                st.success("Aucun sinistre modélisé.")

        st.markdown("---")
        with st.expander("📋 Voir le détail des Actifs Critiques (Tableau)", expanded=True):
            df_risk = gdf_res[gdf_res['perte_estimee'] > 0].sort_values('perte_estimee', ascending=False)
            if not df_risk.empty:
                df_show = df_risk.copy()
                df_show['Actif'] = df_show.apply(lambda r: str(r[col_nom]) if col_nom else str(r[col_addr]), axis=1)
                df_show['% Destruction'] = (df_show['perte_estimee'] / df_show['valeur_assuree'] * 100).round(1)

                st.dataframe(
                    df_show[['Actif', 'Cause_Dominante', 'valeur_assuree', 'perte_estimee', 'Jours Canicule']],
                    column_config={
                        "perte_estimee": st.column_config.ProgressColumn("Perte €", format="%d €",
                                                                         max_value=int(gdf_res['perte_estimee'].max())),
                        "Jours Canicule": st.column_config.NumberColumn("Chaleur (+j)", format="%d j")
                    },
                    hide_index=True, use_container_width=True
                )
            else:
                st.info("Portefeuille sain.")

        with st.expander("ℹ️ Note Méthodologique (Vulnérabilité Sectorielle)"):
            st.markdown("Coefficient de vulnérabilité appliqué selon le Code NAF (Industrie x1.5, Services x0.8).")

    # --- ONGLET 2 : TRANSITION (RESTAURÉ) ---
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

        with c_t2:
            st.subheader("Émissions par Secteur")
            if col_naf:
                df_sec = gdf_res.groupby(col_naf)[['emission_tco2', 'valeur_assuree']].sum().reset_index()
                fig_bar = px.bar(df_sec.sort_values('emission_tco2'), x='emission_tco2', y=col_naf, orientation='h',
                                 title="tCO2e")
                st.plotly_chart(fig_bar, use_container_width=True)

    # --- ONGLET 3 : BUSINESS LOCOMOTIVES (NOUVEAU) ---
    with tab_audit:
        st.markdown("#### 🕵️ Audit Business des Actifs à Risque")
        st.info(
            "Le système analyse automatiquement l'environnement commercial (Gares, Écoles...) des **3 sites les plus exposés**.")

        top_risks = gdf_res[gdf_res['perte_estimee'] > 0].sort_values("perte_estimee", ascending=False).head(3)

        if top_risks.empty:
            st.success("✅ Aucun actif critique à auditer.")
        else:
            for i, row in top_risks.iterrows():
                nom_site = str(row.get(col_nom, row.get(col_addr, f"Site {i}")))
                perte = row['perte_estimee']

                with st.expander(f"🚩 {nom_site} (Impact : -{perte:,.0f} €)", expanded=True):
                    c_ctx, c_flux = st.columns([1, 2])

                    with c_ctx:
                        st.write("**Diagnostic Risque**")
                        st.markdown(f"- **Inondation :** {row.get('alea_inondation', 'Non')}")
                        st.markdown(f"- **Canicule 2050 :** +{row.get('Jours Canicule', 0)} jours")
                        st.metric("Perte", f"{perte:,.0f} €", delta_color="inverse")

                    with c_flux:
                        st.write("**Potentiel Commercial (Locomotives)**")
                        # Buffer 1.5km
                        buffer_geom = row.geometry.buffer(0.015)

                        # Appel Fonction Locomotives
                        with st.spinner("Analyse des flux..."):
                            df_loc, score_loc = analyser_locomotives(buffer_geom)

                        if not df_loc.empty:
                            top_driver = df_loc.sort_values("Impact Trafic", ascending=False).iloc[0]['Catégorie']
                            k1, k2 = st.columns(2)
                            k1.metric("Score Flux", score_loc)
                            k2.metric("Moteur", top_driver)

                            if score_loc > 60:
                                st.error("🚨 **DOUBLE PEINE :** Site stratégique (Gros Flux) ET fortement menacé.")
                            else:
                                st.warning("🔸 **Risque Modéré :** Site exposé mais commercialement secondaire.")

                            st.dataframe(df_loc[['Catégorie', 'Nombre', 'Exemples']].head(3), hide_index=True,
                                         use_container_width=True)
                        else:
                            st.info("📉 Aucun générateur de trafic majeur détecté.")

    # EXPORT
    st.divider()
    csv = gdf_res.drop(columns='geometry').to_csv(index=False, sep=';').encode('utf-8-sig')
    st.download_button("📥 Télécharger Rapport Complet (Risque + Climat 2050)", csv, "stress_test_climat.csv",
                       "text/csv", type="primary")

else:
    st.info("👋 Chargez un portefeuille pour l'analyse multi-périls.")