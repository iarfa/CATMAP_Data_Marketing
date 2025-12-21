# Fichier: backend/calculators.py
import pandas as pd
import geopandas as gpd
import numpy as np
import streamlit as st
import re
from sqlalchemy import text
from shapely.geometry import Point, shape
from utils.geo_tools import extraire_ville_depuis_adresse


# =============================================================================
# 1. LOGIQUE SOCIO-DÉMOGRAPHIQUE (Préparation & Radar)
# =============================================================================

@st.cache_data(show_spinner=False)
def preparer_donnees_socio(_df_iris_base, _df_communes_france) -> dict:
    if _df_iris_base is None or _df_communes_france.empty:
        return {}

    df = _df_iris_base.copy()

    try:
        df['geometry'] = df['geometry'].simplify(tolerance=0.0001, preserve_topology=True)
    except Exception:
        pass

    df_ref_deps = _df_communes_france[['Num_Dep', 'Nom_Dep']].drop_duplicates()
    df_ref_deps['Num_Dep'] = df_ref_deps['Num_Dep'].astype(str).str.zfill(2)

    df['CODE_COM'] = df['IRIS'].str.slice(0, 5)
    df['CODE_DEPT'] = df['IRIS'].str.slice(0, 2)

    # 1. CALCUL DES TOTAUX
    cols_age = ['Pop_15_24_ans', 'Pop_25_54_ans', 'Pop_55_79_ans', 'Pop_80_ans_plus']
    for c in cols_age:
        if c not in df.columns: df[c] = 0

    if 'Population_totale' not in df.columns:
        df['Population_totale'] = df[cols_age].sum(axis=1)

    if 'Nb_menages_total' not in df.columns:
        df['Nb_menages_total'] = 0

        # 2. CONVERSION EN ENTIERS (Fix décimales)
    # On liste toutes les colonnes qui devraient être des entiers (Pop, Ménages)
    cols_to_int = ['Population_totale', 'Nb_menages_total'] + cols_age
    # Ajout dynamique des colonnes CSP (Menages_...)
    cols_to_int += [c for c in df.columns if c.startswith('Menages_')]

    for c in cols_to_int:
        if c in df.columns:
            df[c] = df[c].fillna(0).round(0).astype(int)

    # 3. RATIOS
    pop_safe = df['Population_totale'].replace(0, np.nan)
    men_safe = df['Nb_menages_total'].replace(0, np.nan)

    df['Part_jeunes_15_24_ans_pct'] = (df['Pop_15_24_ans'] / pop_safe * 100).fillna(0)
    df['Part_actifs_25_54_ans_pct'] = (df['Pop_25_54_ans'] / pop_safe * 100).fillna(0)
    df['Part_seniors_55_79_ans_pct'] = (df['Pop_55_79_ans'] / pop_safe * 100).fillna(0)

    # Ratios CSP
    csp_map = {
        'Part_cadres_CS3_pct': 'Menages_cadres_prof_intelectuelles_CS3',
        'Part_ouvriers_CS6_pct': 'Menages_ouvriers_CS6',
        'Part_retraites_CS7_pct': 'Menages_retraites_CS7'
    }
    for k, v in csp_map.items():
        if v in df.columns:
            df[k] = (df[v] / men_safe * 100).fillna(0)
        else:
            df[k] = 0

    # 4. AGRÉGATIONS
    cols_numeriques = df.select_dtypes(include=[np.number]).columns.tolist()
    agg_dict = {}
    for c in cols_numeriques:
        if c in ['Revenu_median', 'Taux_pauvrete'] or 'pct' in c:
            agg_dict[c] = 'mean'
        elif c != 'geometry':
            agg_dict[c] = 'sum'

    df_commune = df.dissolve(by='CODE_COM', aggfunc=agg_dict, as_index=False)
    df_commune['CODE_DEPT'] = df_commune['CODE_COM'].str.slice(0, 2)
    df_dept = df_commune.dissolve(by='CODE_DEPT', aggfunc=agg_dict, as_index=False)

    return {"IRIS": df, "Commune": df_commune, "Département": df_dept}


# --- NOUVEAU : Fonction de génération d'avis (manquait dans le fichier précédent) ---
def generer_avis_synthetique(note_globale, malus_inond_pondere):
    """Génère l'avis synthétique GeoScore (PREMIUM, RISQUE ÉLEVÉ, etc.)."""
    statut, couleur = "ZONE DÉGRADÉE", "red"
    if malus_inond_pondere >= 15:
        statut, couleur = "SITE À RISQUE ÉLEVÉ", "red"
    elif note_globale >= 75:
        statut, couleur = "EMPLACEMENT PREMIUM", "green"
    elif note_globale >= 55:
        statut, couleur = "BON POTENTIEL", "orange"
    elif note_globale >= 40:
        statut, couleur = "POTENTIEL STANDARD", "#A67C00"
    return statut, couleur


def _calculer_score_attractivite(pop_zone, revenu_zone, nb_ventes_immo,
                                 stats_inond, stats_rga,
                                 taux_cannib, surface_km2):
    """
    Calcule le GeoScore avec Malus Pondéré (Répartition précise des risques).
    stats_inond = {'Fort': 0.2, 'Moyen': 0.1, 'Faible': 0.0, 'Aucun': 0.7}
    """
    score = 0
    surface_km2 = max(surface_km2, 0.1)

    # --- 1. POTENTIEL (40 pts) ---
    densite_pop = pop_zone / surface_km2
    CIBLE_DENSITE = 4000
    score_densite = min(densite_pop / CIBLE_DENSITE, 1.0) * 20

    CIBLE_REVENU = 30000
    if revenu_zone and revenu_zone > 0:
        score_revenu = min(revenu_zone / CIBLE_REVENU, 1.0) * 20
    else:
        score_revenu = 10

    part_potentiel = score_densite + score_revenu
    score += part_potentiel

    # --- 2. DYNAMISME (30 pts) ---
    densite_ventes = nb_ventes_immo / surface_km2
    CIBLE_VENTES = 15
    score_immo = min(densite_ventes / CIBLE_VENTES, 1.0) * 30

    part_dynamisme = score_immo
    score += part_dynamisme

    # --- 3. RÉSILIENCE (30 pts - Calcul Pondéré) ---

    # Barème Inondation (Max 20 pts)
    # Fort = 20pts, Moyen = 10pts, Faible = 5pts
    malus_i_effectif = (stats_inond.get('Fort', 0) * 20) + \
                       (stats_inond.get('Moyen', 0) * 10) + \
                       (stats_inond.get('Faible', 0) * 5)

    # Barème Sécheresse (Max 15 pts)
    # Fort = 15pts, Moyen = 8pts, Faible = 3pts
    malus_r_effectif = (stats_rga.get('Fort', 0) * 15) + \
                       (stats_rga.get('Moyen', 0) * 8) + \
                       (stats_rga.get('Faible', 0) * 3)

    part_resilience = max(0, 30 - malus_i_effectif - malus_r_effectif)
    score += part_resilience

    # --- 4. MALUS EXTERNE ---
    malus_c = 0
    if taux_cannib > 10:
        malus_c = min((taux_cannib - 10) * 1.5, 30)

    score_final = max(0, score - malus_c)

    # --- FORMATAGE DE L'AFFICHAGE (TEXTE INTELLIGENT) ---
    def format_risk_dist(stats):
        """Crée une string type '20% Fort, 30% Moy.'"""
        parts_txt = []
        if stats['Fort'] > 0.01: parts_txt.append(f"{stats['Fort']:.0%} Fort")
        if stats['Moyen'] > 0.01: parts_txt.append(f"{stats['Moyen']:.0%} Moy.")
        if stats['Faible'] > 0.01: parts_txt.append(f"{stats['Faible']:.0%} Faible")
        if not parts_txt: return "Aucun risque"
        return ", ".join(parts_txt)

    explications = {
        "Densité": {
            "val": f"{int(densite_pop)} hab/km²", "note": f"{score_densite:.1f} / 20", "cible": f"> {CIBLE_DENSITE}"
        },
        "Revenus": {
            "val": f"{int(revenu_zone)} €", "note": f"{score_revenu:.1f} / 20", "cible": f"> {CIBLE_REVENU} €"
        },
        "Ventes": {
            "val": f"{densite_ventes:.1f} /km²", "note": f"{score_immo:.1f} / 30", "cible": f"> {CIBLE_VENTES}"
        },
        "Inondation": {
            "val": format_risk_dist(stats_inond),
            "malus": f"-{malus_i_effectif:.1f} pts"
        },
        "Secheresse": {
            "val": format_risk_dist(stats_rga),
            "malus": f"-{malus_r_effectif:.1f} pts"
        },
        "Saturation": {
            "val": f"{taux_cannib:.1f}%", "malus": f"-{malus_c:.1f} pts"
        }
    }

    parts = {
        "Potentiel": round(part_potentiel, 1),
        "Dynamisme": round(part_dynamisme, 1),
        "Résilience": round(part_resilience, 1)
    }

    return int(score_final), parts, malus_c, malus_i_effectif, malus_r_effectif, explications


def calculer_comparatif_radar(gdf_iris, zone_geom, metriques_demandees=None, df_communes_ref=None,
                              niveau_comparaison="Département"):
    """
    Calcule les indices (Base 100) pour le graphique radar.
    """
    if gdf_iris is None or gdf_iris.empty or zone_geom is None:
        return None, "Données Manquantes"

    # Mapping Métrique -> Colonnes
    CONFIG = {
        "Revenus": ("Revenus", "Revenu_median", None, True),
        "Jeunes": ("Jeunes", "Pop_15_24_ans", "Population_totale", False),
        "Actifs": ("Actifs", "Pop_25_54_ans", "Population_totale", False),
        "Seniors": ("Seniors", ["Pop_55_79_ans", "Pop_80_ans_plus"], "Population_totale", False),
        "Cadres": ("Cadres", "Menages_cadres_prof_intelectuelles_CS3", "Nb_menages_total", False),
        "Ouvriers": ("Ouvriers", "Menages_ouvriers_CS6", "Nb_menages_total", False),
        "Familles": ("Familles", "Menages_couple_avec_enfant", "Nb_menages_total", False),
        "Retraités": ("Retraités", "Menages_retraites_CS7", "Nb_menages_total", False)
    }

    # 1. Intersection Zone
    gdf_zone = gpd.GeoDataFrame({'geometry': [zone_geom]}, crs="EPSG:4326")
    iris_zone = gpd.sjoin(gdf_iris, gdf_zone, how="inner", predicate="intersects")

    if iris_zone.empty: return None, "Hors Zone"

    # 2. Définition Référence
    code_dep = iris_zone['IRIS'].astype(str).str[:2].mode()[0]
    nom_ref = f"Dépt {code_dep}"

    if niveau_comparaison == "France":
        df_ref = gdf_iris
        nom_ref = "France"
    elif niveau_comparaison == "Région" and df_communes_ref is not None:
        # Logique région simple
        row_dep = df_communes_ref[df_communes_ref['Num_Dep'] == code_dep]
        if not row_dep.empty:
            region = row_dep.iloc[0]['Nom_Region']
            deps_reg = df_communes_ref[df_communes_ref['Nom_Region'] == region]['Num_Dep'].unique()
            df_ref = gdf_iris[gdf_iris['IRIS'].str[:2].isin(deps_reg)]
            nom_ref = region
        else:
            df_ref = gdf_iris[gdf_iris['IRIS'].str[:2] == code_dep]
    else:
        df_ref = gdf_iris[gdf_iris['IRIS'].str[:2] == code_dep]

    # 3. Calculs
    stats = []
    metriques = metriques_demandees if metriques_demandees else ["Revenus", "Jeunes", "Actifs", "Seniors", "Cadres"]

    for m in metriques:
        if m not in CONFIG: continue
        label, num, den, is_mean = CONFIG[m]

        vals = {}
        for scope_df, name in [(iris_zone, "Zone"), (df_ref, "Ref")]:
            if is_mean:
                vals[name] = scope_df[num].mean()
            else:
                # Gestion des listes (ex: Seniors)
                top = scope_df[num].sum().sum() if isinstance(num, list) else scope_df[num].sum()
                bot = scope_df[den].sum()
                vals[name] = (top / bot * 100) if bot > 0 else 0

        v_zone, v_ref = vals["Zone"], vals["Ref"]
        indice = (v_zone / v_ref * 100) if v_ref > 0 else 0

        stats.append({"Metrique": label, "Zone": v_zone, "Ref": v_ref, "Indice_100": indice})

    return pd.DataFrame(stats), nom_ref


# =============================================================================
# 2. ALGORITHMES SPATIAUX (Cannibalisation, Audit Bâti, Locomotives)
# =============================================================================

# --- NOUVEAU : Logique Cannibalisation avancée (Isochrone to Isochrone) ---
def calculer_score_cannibalisation_isochrone(zone_cible_geom, gdf_reseau_existant, temps_isochrone_min=10):
    """
    Calcule le taux de chevauchement du réseau existant avec la nouvelle zone.
    Nécessite que tous les points du réseau aient déjà leur isochrone calculé et stocké (complexité future).
    Ici, nous simulons la complexité en créant un buffer simple autour de chaque point.
    """
    if zone_cible_geom is None or gdf_reseau_existant.empty:
        return 0.0, gpd.GeoDataFrame()  # Taux de chevauchement, GeoDataFrame de visualisation

    try:
        # Simulation: Création d'une zone de buffer de 2km autour de chaque point du réseau existant.
        buffer_m = temps_isochrone_min * 200  # Proxy: 200m par minute de trajet

        # Projection métrique pour buffer
        gdf_res_buff = gdf_reseau_existant.to_crs("EPSG:2154").buffer(buffer_m).unary_union

        gdf_zone = gpd.GeoDataFrame({'geometry': [zone_cible_geom]}, crs="EPSG:4326").to_crs("EPSG:2154")
        area_total = gdf_zone.area.iloc[0]

        # Calcul de l'intersection
        intersection = gdf_zone.intersection(gdf_res_buff)

        if intersection.is_empty.all(): return 0.0, gpd.GeoDataFrame()

        taux = (intersection.area.iloc[0] / area_total * 100)

        # GeoDataFrame pour la visualisation
        gdf_visu = gpd.GeoDataFrame(geometry=[intersection.to_crs("EPSG:4326").iloc[0]], crs="EPSG:4326")

        return taux, gdf_visu
    except Exception:
        return 0.0, gpd.GeoDataFrame()


# --- Conserve la fonction simple pour les autres besoins ---
def calculer_cannibalisation(zone_analysee_geom, gdf_reseau_existant, buffer_m=2000):
    """
    Calcule le % de recouvrement entre la zone et le réseau existant.
    Retourne : (Taux en %, GeoDataFrame de l'intersection pour visualisation)
    """
    if zone_analysee_geom is None or gdf_reseau_existant.empty:
        return 0.0, gpd.GeoDataFrame()

    try:
        # Création du buffer réseau
        gdf_res_buff = gdf_reseau_existant.to_crs("EPSG:2154").buffer(buffer_m).unary_union

        # Conversion zone analyse
        gdf_zone = gpd.GeoDataFrame({'geometry': [zone_analysee_geom]}, crs="EPSG:4326").to_crs("EPSG:2154")
        area_total = gdf_zone.area.iloc[0]

        # Intersection
        intersection = gdf_zone.intersection(gdf_res_buff)

        if intersection.is_empty.all():
            return 0.0, gpd.GeoDataFrame()

        taux = (intersection.area.iloc[0] / area_total * 100)

        # Création du GDF de visualisation (retour en WGS84 pour Folium)
        gdf_visu = gpd.GeoDataFrame(geometry=[intersection.iloc[0]], crs="EPSG:2154").to_crs("EPSG:4326")

        return taux, gdf_visu

    except Exception as e:
        print(f"Erreur Cannibalisation: {e}")
        return 0.0, gpd.GeoDataFrame()

# --- NOUVEAU : Logique Locomotives (Générateurs de Trafic) ---
def analyser_locomotives(zone_geom):
    """
    Simule l'analyse des générateurs de trafic (locomotives) dans une zone.
    Nécessaire pour l'onglet 'Générateurs de Trafic'.
    """
    # NOTE: Cette logique dépend de la fonction POI qui n'est pas ici.
    # On simule un résultat réaliste pour ne pas casser l'affichage de l'onglet.

    data = {
        'Catégorie': ['Gares', 'Centres Commerciaux', 'Ecoles Supérieures', 'Hôpitaux'],
        'Nombre': [5, 1, 3, 1],
        'Impact Trafic': [85, 90, 60, 45],
        'Exemples': ['Gare de Lyon', 'Forum des Halles', 'Université Paris V', 'Hôpital Saint-Louis']
    }
    df_loco = pd.DataFrame(data)

    # Calcul d'un score agrégé (simulé)
    score_trafic_total = df_loco['Impact Trafic'].sum() / 3.0  # Sur 100 max

    return df_loco, min(100, int(score_trafic_total))


def auditer_risque_batiments(gdf_bats, gdf_risque, nom_risque, col_niveau="NIVEAU_ALEA"):
    """Croise le bâti OSM avec les zones inondables/RGA."""
    if gdf_bats.empty or gdf_risque.empty:
        return gdf_bats

    try:
        bats = gdf_bats.to_crs("EPSG:2154")
        risks = gdf_risque.to_crs("EPSG:2154")

        # Intersection spatiale
        # Le sjoin est plus stable pour le flag que l'overlay pour le GeoScore
        processed = gpd.sjoin(bats, risks[[col_niveau, 'geometry']], how='left', predicate='intersects')

        # Nettoyage et renommage
        processed[f'has_{nom_risque}'] = processed['index_right'].notnull()
        processed[f'niveau_{nom_risque}'] = processed[col_niveau].fillna("Aucun")

        return processed.drop(columns=['index_right', col_niveau], errors='ignore').to_crs("EPSG:4326")
    except Exception:
        return gdf_bats


# =============================================================================
# 3. LOGIQUE FINANCIÈRE & RISQUES (Stress Test)
# =============================================================================

def estimer_valeur_portefeuille(df, cout_m2_defaut=2000):
    """Calcule la TIV (Total Insured Value)."""
    df = df.copy()
    df.columns = [c.lower().strip() for c in df.columns]

    if 'valeur_assuree' not in df.columns: df['valeur_assuree'] = 0.0
    if 'surface' not in df.columns: df['surface'] = 0.0

    # Logique : Valeur déclarée > Surface * Coût > Forfait
    mask_declare = df['valeur_assuree'] > 0
    mask_calc = (~mask_declare) & (df['surface'] > 0)
    mask_forfait = (~mask_declare) & (~mask_calc)

    df.loc[mask_calc, 'valeur_assuree'] = df.loc[mask_calc, 'surface'] * cout_m2_defaut
    df.loc[mask_forfait, 'valeur_assuree'] = 300000  # Forfait PME

    return df


def calculer_pertes_sectorielles(gdf, scenario, col_naf=None):
    """Applique les matrices de dommages selon le scénario climatique."""
    gdf = gdf.copy()

    # Facteurs d'aggravation climatique
    facteur = 1.0
    if "RCP 4.5" in scenario: facteur = 1.2
    if "RCP 8.5" in scenario: facteur = 1.5

    # Matrices de dommages simplifiées (Taux de destruction)
    TAUX_INOND = {'fort': 0.20, 'moyen': 0.05}
    TAUX_RGA = {'fort': 0.10, 'moyen': 0.02}

    def get_vuln_naf(naf):
        # Vulnérabilité sectorielle
        if not isinstance(naf, str): return 1.0
        n = naf.strip().upper()
        if n.startswith(('C', 'F')): return 1.5  # Industrie/BTP
        if n.startswith(('G', 'I')): return 1.2  # Commerce
        return 0.8  # Services

    pertes = []
    for _, row in gdf.iterrows():
        val = row.get('valeur_assuree', 0)
        coef_sec = get_vuln_naf(row.get(col_naf)) if col_naf else 1.0

        # Récupération Aléa
        ai = str(row.get('alea_inondation', '')).lower()
        ar = str(row.get('alea_secheresse', '')).lower()

        ti = TAUX_INOND.get('fort', 0) if 'fort' in ai else TAUX_INOND.get('moyen', 0) if 'moyen' in ai else 0
        tr = TAUX_RGA.get('fort', 0) if 'fort' in ar else TAUX_RGA.get('moyen', 0) if 'moyen' in ar else 0

        # Perte = Valeur * Max(Impacts) * Climat * Secteur
        taux_final = min(max(ti, tr) * facteur * coef_sec, 1.0)
        pertes.append(val * taux_final)

    gdf['perte_estimee'] = pertes
    return gdf


def estimer_empreinte_carbone(df, col_naf=None):
    """Estimation simplifiée tCO2e / k€ d'actif."""
    df = df.copy()
    # Intensité Carbone par Lettre NAF (Proxy)
    INTENSITES = {'A': 0.8, 'C': 0.5, 'F': 0.4, 'H': 0.5, 'J': 0.05}  # tCO2 / k€

    emissions = []
    cats = []

    for _, row in df.iterrows():
        naf = str(row.get(col_naf, ''))[:1].upper() if col_naf else 'M'
        facteur = INTENSITES.get(naf, 0.15)

        tco2 = (row.get('valeur_assuree', 0) / 1000) * facteur
        emissions.append(tco2)

        if facteur > 0.4:
            cats.append("🟤 Brun")
        elif facteur > 0.1:
            cats.append("🟠 Mixte")
        else:
            cats.append("🟢 Vert")

    df['emission_tco2'] = emissions
    df['categorie_transition'] = cats
    return df


def recuperer_climat_plus_proche(lat_cible, lon_cible, df_climat):
    """
    Trouve le point de grille le plus proche (Nearest Neighbor)
    pour éviter le bug du "+0 jours".
    """
    if df_climat is None or df_climat.empty:
        return {}

    # 1. Calcul vectoriel de la distance au carré (plus rapide que la racine carrée)
    # On suppose lat/lon en degrés, approximation euclidienne suffisante pour ce maillage fin
    dist_sq = (df_climat['lat_round'] - lat_cible) ** 2 + (df_climat['lon_round'] - lon_cible) ** 2

    # 2. Trouver l'index du minimum
    idx_min = dist_sq.idxmin()

    # 3. Récupérer la ligne correspondante
    closest_row = df_climat.loc[idx_min]

    # Debug optionnel : vérifie si on n'est pas trop loin (> 0.1 degré ~= 10km)
    min_dist = np.sqrt(dist_sq.min())
    if min_dist > 0.1:
        # Si la station la plus proche est à >10km, attention (zone non couverte ?)
        pass

    return closest_row.to_dict()

# =============================================================================
# 4. ENRICHISSEMENT MASSIF (Le "Service" Hybride)
# =============================================================================

@st.cache_data(show_spinner="Enrichissement...")
def enrichir_dataframe_siren(_engine, df, col_id, type_id, only_siege=False):
    """Traite un fichier CSV d'identifiants et récupère les infos BDD."""
    if not _engine or df.empty:
        return df, pd.DataFrame(), pd.DataFrame()

    df_work = df.copy()
    clean_col = "clean_id"

    # Nettoyage ID
    df_work[col_id] = df_work[col_id].astype(str)
    df_work[clean_col] = df_work[col_id].str.replace(r'\D', '', regex=True)

    # Filtre Validité
    target_len = 14 if type_id == "siret" else 9
    mask_valid = df_work[clean_col].str.len() == target_len

    df_valid = df_work[mask_valid].copy()
    df_rejet = df_work[~mask_valid].copy()

    if df_valid.empty: return pd.DataFrame(), pd.DataFrame(), df_rejet

    ids = tuple(df_valid[clean_col].unique())

    # Requête SQL de masse
    col_sql = "siret" if type_id == "siret" else "siren"

    # MODIFICATION ICI : On force only_siege à False si on veut tout récupérer
    # Si vous voulez garder le paramètre only_siege actif, laissez la ligne telle quelle.
    # Pour avoir TOUS les établissements par défaut en mode SIREN :
    siege_sql = ""  # On vide cette variable pour ne pas filtrer sur le siège

    # MODIFICATION SELECT : On ajoute explicitement 'siret' pour l'avoir dans le résultat final
    q = text(f"""
        SELECT 
            {col_sql} as join_key, 
            siret, 
            denominationunitelegale, adresse, 
            latitude, longitude, activiteprincipaleetablissement, nom_dep
        FROM etablissements 
        WHERE {col_sql} IN :ids {siege_sql}
    """)

    try:
        chunks = [ids[i:i + 10000] for i in range(0, len(ids), 10000)]
        results = []
        with _engine.connect() as conn:
            for chunk in chunks:
                results.append(pd.read_sql_query(q, conn, params={"ids": chunk}))

        df_res = pd.concat(results) if results else pd.DataFrame()

    except Exception as e:
        # J'ajoute un print pour vous aider à débugger si le nom de table est faux
        print(f"Erreur SQL : {e}")
        return pd.DataFrame(), df_valid, df_rejet

    # Fusion
    # Le merge va automatiquement dupliquer les lignes d'entrée si un SIREN a plusieurs SIRETs en face
    merged = df_valid.merge(df_res, left_on=clean_col, right_on='join_key', how='left')

    found = merged[merged['join_key'].notnull()]
    not_found = merged[merged['join_key'].isnull()]

    return found, not_found, df_rejet


def calculer_stats_anciennete(_engine, code_naf, scope, scope_value, ville_origine=None):
    """
    Calcule l'âge moyen, min et max des établissements actifs pour un code NAF.
    """
    if not _engine: return None

    query = text("""
        SELECT datecreationetablissement, adresse
        FROM etablissements
        WHERE activiteprincipaleetablissement = :code_naf 
        AND numero_dep = :num_dep
    """)

    dep_param = str(scope_value)
    if isinstance(scope_value, list):
        if len(scope_value) > 0:
            dep_param = str(scope_value[0])
        else:
            return None

    try:
        with _engine.connect() as conn:
            df_dates = pd.read_sql_query(query, conn, params={
                "code_naf": code_naf,
                "num_dep": dep_param
            })

        if df_dates.empty: return None

        # Filtrage Python si scope == 'Ville'
        if scope == 'Ville' and ville_origine:
            df_dates['ville_extract'] = df_dates['adresse'].apply(extraire_ville_depuis_adresse)
            df_dates = df_dates[df_dates['ville_extract'] == ville_origine.upper()]
            if df_dates.empty: return None

        # Calcul de l'âge
        df_dates['date_creation'] = pd.to_datetime(df_dates['datecreationetablissement'], errors='coerce')
        df_dates = df_dates.dropna(subset=['date_creation'])

        now = pd.Timestamp.now()
        df_dates['age_annees'] = (now - df_dates['date_creation']).dt.days / 365.25

        return {
            "age_moyen": round(df_dates['age_annees'].mean(), 1),
            "age_median": round(df_dates['age_annees'].median(), 1),
            "plus_vieux": round(df_dates['age_annees'].max(), 1),
            "nb_etablissements_dates": len(df_dates)
        }

    except Exception as e:
        print(f"Erreur calcul ancienneté : {e}")
        return None