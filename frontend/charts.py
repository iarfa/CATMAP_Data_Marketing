# Fichier: frontend/charts.py
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np  # Ajout de numpy pour les vérifications de type si nécessaire


def plot_radar_comparatif(df_stats, nom_ref):
    """
    Génère un graphique Radar (fonction inchangée).
    """
    if df_stats is None or df_stats.empty:
        return go.Figure()

    cols_std = ['Metrique', 'Zone', 'Indice_100', 'delta', 'delta_abs', 'Unit']
    col_ref = next((c for c in df_stats.columns if c not in cols_std), 'Reference')

    if 'Unit' not in df_stats.columns:
        df_stats['Unit'] = df_stats['Metrique'].apply(lambda x: "€" if "Revenu" in x else "%")

    fig = go.Figure()

    vals_ref = df_stats[col_ref] if col_ref in df_stats.columns else [0] * len(df_stats)

    fig.add_trace(go.Scatterpolar(
        r=[100] * len(df_stats),
        theta=df_stats['Metrique'],
        fill=None,
        name=f"Ref ({nom_ref})",
        line_color='gray',
        line_dash='dot',
        hoverinfo='text',
        text=[f"Ref: {v:.0f}{u}" for v, u in zip(vals_ref, df_stats['Unit'])]
    ))

    fig.add_trace(go.Scatterpolar(
        r=df_stats['Indice_100'],
        theta=df_stats['Metrique'],
        fill='toself',
        name='Zone Étudiée',
        line_color='#E63946',
        hoverinfo='text',
        text=[f"Zone: {v:.0f}{u} (Indice {i:.0f})" for v, u, i in
              zip(df_stats['Zone'], df_stats['Unit'], df_stats['Indice_100'])]
    ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, max(140, df_stats['Indice_100'].max() + 10)]
            )
        ),
        showlegend=True,
        height=400,
        margin=dict(t=20, b=20, l=40, r=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5)
    )

    return fig

def plot_evolution_prix_dvf(df_original, type_local_filtre="Tous"):
    """
    Combo Chart DVF, avec filtre par type de local.
    """
    if df_original.empty: return None

    df = df_original.copy()

    # --- FILTRAGE CRITIQUE PAR TYPE ---
    if type_local_filtre != "Tous":
        df = df[df['type_local'] == type_local_filtre]
        if df.empty: return None

    # --- SÉCURITÉ DATE ---
    if not pd.api.types.is_datetime64_any_dtype(df['date_mutation']):
        df['date_mutation'] = pd.to_datetime(df['date_mutation'], errors='coerce')
        df = df.dropna(subset=['date_mutation'])
        if df.empty: return None

    # Agrégation trimestrielle
    df_trend = df.groupby(pd.Grouper(key='date_mutation', freq='Q')).agg(
        prix=('prix_m2', 'median'),
        volume=('valeur_fonciere', 'count')
    ).reset_index()

    fig = go.Figure()

    # Barres (Volume)
    fig.add_trace(go.Bar(
        x=df_trend['date_mutation'], y=df_trend['volume'],
        name="Volume Ventes", marker_color='rgba(200, 200, 200, 0.5)', yaxis='y'
    ))

    # Ligne (Prix)
    fig.add_trace(go.Scatter(
        x=df_trend['date_mutation'], y=df_trend['prix'],
        name="Prix m² Médian", line=dict(color='#B8860B', width=3), yaxis='y2'
    ))

    fig.update_layout(
        title=f"Tendance Prix & Volume ({type_local_filtre})",
        yaxis=dict(title="Volume"),
        yaxis2=dict(title="Prix (€/m²)", overlaying='y', side='right'),
        margin=dict(l=0, r=0, t=40, b=0),
        legend=dict(orientation="h", y=-0.2)
    )
    return fig

def plot_repartition_risques(df_bats, col_niveau, title):
    """Pie Chart des niveaux de risques bâtiments (inchangée)."""
    if df_bats.empty: return None

    counts = df_bats[col_niveau].fillna('Aucun').value_counts().reset_index()
    counts.columns = ['Niveau', 'Nombre']

    colors = {'Aléa fort': '#d62728', 'Aléa moyen': '#ff7f0e', 'Aléa faible': '#fecb52', 'Aucun': '#2ca02c'}

    fig = px.pie(
        counts, values='Nombre', names='Niveau', hole=0.4,
        color='Niveau', color_discrete_map=colors,
        title=title
    )
    fig.update_layout(margin=dict(t=30, b=0, l=0, r=0), height=250)
    return fig

def plot_locomotives_histogram(df_loc):
    """
    Génère un histogramme Plotly pour les pôles d'attraction (Locomotives).
    (Fonction inchangée)
    """
    if df_loc.empty:
        return go.Figure()

    df_plot = df_loc.sort_values("Impact Trafic", ascending=True)

    fig = px.bar(
        df_plot,
        x="Impact Trafic",
        y="Catégorie",
        orientation='h',
        color="Impact Trafic",
        color_continuous_scale=px.colors.sequential.Plotly3,
        title="Impact des Pôles d'Attraction Locaux"
    )

    fig.update_layout(
        yaxis_title=None,
        margin=dict(l=0, r=0, t=40, b=0),
        height=350
    )
    return fig