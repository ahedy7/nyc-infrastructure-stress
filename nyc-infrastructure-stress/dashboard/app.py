"""NYC Infrastructure Stress Index — Plotly Dash dashboard."""

from __future__ import annotations

import json
import os
from typing import Optional

import geopandas as gpd
import pandas as pd
import plotly.express as px
from dash import Dash, Input, Output, callback, dcc, html

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data_processed")
STRESS_PATH = os.path.join(DATA_DIR, "nta_stress_index.csv")
SHP_PATH = os.path.join(BASE_DIR, "data_raw", "nta_2020", "geo_export.shp")
GITHUB_URL = "https://github.com/ahedy7/nyc-infrastructure-stress"

BG_DARK = "#1a1a2e"
BG_CARD = "#23233a"
TEXT_PRIMARY = "#f5f5f5"
TEXT_MUTED = "#b8b8c8"
BORDER = "#3a3a52"
ACCENT_RED = "#e74c3c"
ACCENT_ORANGE = "#f39c12"

BASELINE_CONTEXT = (
    "Baseline stress measures chronic infrastructure strain across four dimensions: "
    "311 complaint density, MTA delay density, utility outage density, and flood zone "
    "exposure. Scores are z-score standardized and equally weighted. Higher scores "
    "indicate neighborhoods where multiple infrastructure systems are under persistent "
    "pressure."
)

EVENT_CONTEXT = (
    "Event delta measures how much more stressed a neighborhood becomes during "
    "high-stress weeks relative to its own baseline. Positive delta = more brittle "
    "during events than baseline suggests. Negative delta = more resilient than "
    "expected. Computed via Monte Carlo simulation over annual aggregates."
)

GRAPH_CONFIG = {"displayModeBar": False, "responsive": True}


def load_merged_geodata() -> tuple[gpd.GeoDataFrame, dict]:
    stress = pd.read_csv(STRESS_PATH)
    if not os.path.exists(SHP_PATH):
        raise FileNotFoundError(f"NTA shapefile not found at {SHP_PATH}")

    boundaries = gpd.read_file(SHP_PATH)
    if "NTACode" not in boundaries.columns:
        for candidate in ("nta2020", "NTA2020", "ntacode"):
            if candidate in boundaries.columns:
                boundaries = boundaries.rename(columns={candidate: "NTACode"})
                break

    boundaries = boundaries[["NTACode", "geometry"]].to_crs("EPSG:4326")
    merged = boundaries.merge(stress, on="NTACode", how="inner")
    if merged.empty:
        raise ValueError("No NTA polygons matched stress index rows on NTACode.")

    geojson = json.loads(merged.to_json())
    return merged, geojson


GDF, GEOJSON = load_merged_geodata()

app = Dash(__name__)
app.title = "NYC Infrastructure Stress Index"

app.index_string = """<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>NYC Infrastructure Stress Index</title>
        {%favicon%}
        {%css%}
        <style>
            html, body {
                margin: 0;
                padding: 0;
                background: #1a1a2e;
            }
            .toggle-buttons .dash-radio-item {
                display: inline-flex;
                margin: 0;
            }
            .toggle-buttons label {
                cursor: pointer;
                margin: 0;
                padding: 0.55rem 1rem;
                border: 1px solid #3a3a52;
                background: #23233a;
                color: #b8b8c8;
                font-size: 0.9rem;
                font-weight: 500;
            }
            .toggle-buttons label:first-of-type {
                border-radius: 8px 0 0 8px;
            }
            .toggle-buttons label:last-of-type {
                border-radius: 0 8px 8px 0;
            }
            .toggle-buttons input {
                display: none;
            }
            .toggle-buttons input:checked + label,
            .toggle-buttons label:has(input:checked) {
                background: #f5f5f5;
                color: #1a1a2e;
                border-color: #f5f5f5;
            }
            @media (max-width: 960px) {
                .main-columns {
                    flex-direction: column !important;
                }
                .map-column, .side-column {
                    flex: 1 1 100% !important;
                    max-width: 100% !important;
                }
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>"""

app.layout = html.Div(
    [
        html.Header(
            [
                html.H1(
                    "NYC Infrastructure Stress Index",
                    style={
                        "margin": "0 0 0.35rem 0",
                        "fontSize": "clamp(1.6rem, 3vw, 2.2rem)",
                        "fontWeight": 600,
                        "color": TEXT_PRIMARY,
                    },
                ),
                html.P(
                    (
                        "Neighborhood-level infrastructure strain across four dimensions: "
                        "service delivery, mobility, utilities, and climate vulnerability"
                    ),
                    style={
                        "margin": "0 0 16px 0",
                        "maxWidth": "760px",
                        "color": TEXT_MUTED,
                        "fontSize": "1rem",
                        "lineHeight": 1.5,
                    },
                ),
                dcc.RadioItems(
                    id="metric-toggle",
                    options=[
                        {"label": "Baseline Stress", "value": "baseline"},
                        {"label": "Event Week Delta", "value": "event"},
                    ],
                    value="baseline",
                    inline=True,
                    className="toggle-buttons",
                    inputStyle={"marginRight": "0"},
                    labelStyle={"marginRight": "0"},
                ),
            ],
            style={
                "padding": "1.75rem 1.5rem 1.25rem",
                "borderBottom": f"1px solid {BORDER}",
                "overflow": "hidden",
            },
        ),
        html.Div(
            [
                html.Div(
                    [
                        dcc.Graph(
                            id="choropleth-map",
                            config=GRAPH_CONFIG,
                            style={"width": "100%", "height": "100%"},
                        ),
                    ],
                    className="map-column",
                    style={
                        "flex": "1 1 60%",
                        "minWidth": "320px",
                        "minHeight": "520px",
                        "display": "flex",
                        "flexDirection": "column",
                    },
                ),
                html.Div(
                    [
                        dcc.Graph(
                            id="top-nta-bar",
                            config=GRAPH_CONFIG,
                            style={"width": "100%", "height": "100%"},
                        ),
                        html.Div(
                            id="metric-context",
                            style={
                                "marginTop": "1rem",
                                "padding": "1rem 1.1rem",
                                "borderRadius": "10px",
                                "border": f"1px solid {BORDER}",
                                "backgroundColor": BG_CARD,
                                "color": TEXT_MUTED,
                                "fontSize": "0.95rem",
                                "lineHeight": 1.55,
                            },
                        ),
                    ],
                    className="side-column",
                    style={
                        "flex": "1 1 40%",
                        "minWidth": "280px",
                        "minHeight": "520px",
                        "display": "flex",
                        "flexDirection": "column",
                    },
                ),
            ],
            className="main-columns",
            style={
                "display": "flex",
                "flexWrap": "wrap",
                "gap": "1.25rem",
                "padding": "1.25rem 1.5rem",
                "alignItems": "stretch",
            },
        ),
        html.Footer(
            [
                html.P(
                    "Data sources: NYC Open Data 311, MTA, Power Outage Complaints, FEMA Flood Hazard Zones",
                    style={"margin": "0 0 0.35rem 0", "color": TEXT_MUTED, "fontSize": "0.9rem"},
                ),
                html.P(
                    [
                        "Built by Arvin Hedy | McGill University | 2026 | ",
                        html.A(
                            "GitHub",
                            href=GITHUB_URL,
                            target="_blank",
                            rel="noopener noreferrer",
                            style={"color": TEXT_PRIMARY},
                        ),
                    ],
                    style={"margin": 0, "color": TEXT_MUTED, "fontSize": "0.9rem"},
                ),
            ],
            style={
                "padding": "1.25rem 1.5rem 1.75rem",
                "borderTop": f"1px solid {BORDER}",
            },
        ),
    ],
    style={
        "minHeight": "100vh",
        "fontFamily": "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        "backgroundColor": BG_DARK,
        "color": TEXT_PRIMARY,
    },
)


def _chart_layout(title: str, *, height: int = 420, margin: Optional[dict] = None) -> dict:
    return {
        "title": {"text": title, "font": {"color": TEXT_PRIMARY, "size": 16}, "x": 0},
        "margin": margin or {"l": 20, "r": 20, "t": 50, "b": 20},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": "system-ui, sans-serif", "color": TEXT_PRIMARY},
        "autosize": True,
        "height": height,
        "uirevision": "dashboard",
    }


@callback(
    Output("choropleth-map", "figure"),
    Output("top-nta-bar", "figure"),
    Output("metric-context", "children"),
    Input("metric-toggle", "value"),
)
def update_dashboard(metric: str):
    baseline_mode = metric != "event"
    color_field = "baseline_stress_score" if baseline_mode else "event_delta"
    color_scale = "RdYlGn_r" if baseline_mode else "RdYlBu_r"
    colorbar_title = "Baseline Stress" if baseline_mode else "Event Week Delta"

    map_df = GDF.copy()
    map_df["baseline_stress_score"] = map_df["baseline_stress_score"].round(2)
    map_df["event_delta"] = map_df["event_delta"].round(2)

    map_fig = px.choropleth_mapbox(
        map_df,
        geojson=GEOJSON,
        locations="NTACode",
        featureidkey="properties.NTACode",
        color=color_field,
        color_continuous_scale=color_scale,
        mapbox_style="open-street-map",
        center={"lat": 40.7128, "lon": -73.9760},
        zoom=11,
        opacity=0.82,
        custom_data=[
            "NTAName",
            "baseline_stress_score",
            "event_delta",
            "baseline_rank",
            "delta_rank",
        ],
    )
    map_fig.update_traces(
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Baseline stress: %{customdata[1]:.2f}<br>"
            "Event delta: %{customdata[2]:.2f}<br>"
            "Baseline rank: %{customdata[3]}<br>"
            "Delta rank: %{customdata[4]}<extra></extra>"
        )
    )
    map_fig.update_layout(
        **_chart_layout(
            "NYC Neighborhood Stress Map",
            height=520,
            margin={"l": 0, "r": 0, "t": 40, "b": 0},
        ),
        coloraxis_colorbar={
            "title": "Baseline Stress" if baseline_mode else "Event Week Delta",
            "tickfont": {"color": TEXT_MUTED},
        },
        mapbox={"style": "open-street-map", "center": {"lat": 40.7128, "lon": -73.9760}, "zoom": 11},
    )

    top_df = (
        map_df.sort_values(color_field, ascending=False)
        .head(10)
        .iloc[::-1]
        .copy()
    )
    bar_title = (
        "Top 10 Neighborhoods by Baseline Stress"
        if baseline_mode
        else "Top 10 Neighborhoods by Event Week Delta"
    )
    bar_color = ACCENT_RED if baseline_mode else ACCENT_ORANGE
    bar_fig = px.bar(
        top_df,
        x=color_field,
        y="NTAName",
        orientation="h",
        title=bar_title,
        color_discrete_sequence=[bar_color],
    )
    bar_fig.update_layout(
        **_chart_layout(bar_title, height=320),
        xaxis_title=colorbar_title,
        yaxis_title="",
        showlegend=False,
    )
    bar_fig.update_traces(marker_line_width=0)

    context = BASELINE_CONTEXT if baseline_mode else EVENT_CONTEXT
    return map_fig, bar_fig, context


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8050)), debug=False)
