"""
NYC Infrastructure Stress Dashboard — Plotly Dash MVP

How to run (from nyc-infrastructure-stress/):
  python dashboard/app.py
  # or: ./run_dashboard.sh  (kills any existing server on 8050 first)

Then open: http://127.0.0.1:8050/

Required files (relative to project root = parent of dashboard/):
  - data_processed/baseline_index.csv
  - arcgis_exports/2020_Neighborhood_Tabulation_Areas_(NTAs)_20260303.geojson
"""

from pathlib import Path
import json
import os
import socket
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, dcc, html, dash_table, callback, Input, Output, State

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = PROJECT_ROOT / "data_processed" / "baseline_index.csv"
GEOJSON_PATH = PROJECT_ROOT / "arcgis_exports" / "2020_Neighborhood_Tabulation_Areas_(NTAs)_20260303.geojson"

# -----------------------------------------------------------------------------
# Dark theme — MIT Sensible City Lab aesthetic
# -----------------------------------------------------------------------------
BG_DARK = "#0d1117"
BG_CARD = "#161b22"
BG_HOVER = "#21262d"
TEXT_PRIMARY = "#e6edf3"
TEXT_MUTED = "#8b949e"
ACCENT_CYAN = "#58a6ff"
ACCENT_TEAL = "#39d353"
ACCENT_ORANGE = "#d29922"
BORDER = "#30363d"

# Color scale for stress (dark-mode friendly)
COLOR_SCALE = ["#0d47a1", "#1565c0", "#1976d2", "#42a5f5", "#64b5f6", "#ffb74d", "#ff9800", "#f57c00", "#e65100"]

# Map style: uses MapLibre (choropleth_map) - more stable zoom than deprecated choropleth_mapbox
MAP_STYLE = "carto-darkmatter"


def _norm(s):
    """Normalize string for join: strip whitespace, uppercase."""
    if pd.isna(s):
        return ""
    return str(s).strip().upper()


def detect_nta_property(geojson):
    """Inspect GeoJSON features and detect which property holds the NTA code."""
    candidates = ["nta2020", "NTACode", "ntacode", "NTA2020", "nta_code", "NTA_CODE"]
    if not geojson.get("features"):
        return None, []
    props = geojson["features"][0].get("properties", {})
    keys = list(props.keys())
    for c in candidates:
        if c in props:
            return c, keys
    for k in keys:
        if "nta" in k.lower() or "code" in k.lower():
            return k, keys
    return None, keys


def load_and_join():
    """Load baseline CSV and GeoJSON, perform robust join."""
    df = pd.read_csv(BASELINE_PATH)
    df["nta2020_norm"] = df["nta2020"].apply(_norm)

    if not GEOJSON_PATH.exists():
        raise FileNotFoundError(
            f"GeoJSON not found at {GEOJSON_PATH}. "
            "Ensure arcgis_exports/2020_Neighborhood_Tabulation_Areas_(NTAs)_20260303.geojson exists."
        )

    with open(GEOJSON_PATH, "r") as f:
        geojson = json.load(f)

    n_features = len(geojson.get("features", []))
    featureidkey, all_keys = detect_nta_property(geojson)
    if not featureidkey:
        raise ValueError(
            f"Could not detect NTA code property. Feature keys: {all_keys}. "
            "Expected one of: nta2020, NTACode, ntacode, NTA2020"
        )

    norm_to_geo = {}
    for feat in geojson["features"]:
        val = feat.get("properties", {}).get(featureidkey)
        if val is not None:
            norm_to_geo[_norm(val)] = val

    df["_join_key"] = df["nta2020_norm"]
    df["_choropleth_loc"] = df["_join_key"].map(norm_to_geo)
    matched = df["_choropleth_loc"].notna()
    n_matched = matched.sum()
    n_total = len(df)
    join_pct = 100 * n_matched / n_total if n_total else 0

    if join_pct < 95:
        print(
            "\n⚠️  WARNING: Join rate < 95%\n"
            f"  featureidkey: {featureidkey}\n"
            f"  Example GeoJSON values: {list(norm_to_geo.values())[:5]}\n"
            f"  Example baseline nta2020: {df['nta2020'].head().tolist()}\n"
            f"  Matched: {n_matched}/{n_total} ({join_pct:.1f}%)\n"
        )

    for col in ["stress_score", "z_heat", "z_nonheat"]:
        if col in df.columns:
            df[col] = df[col].fillna(0)

    return df, geojson, featureidkey, join_pct, n_total, n_features


# -----------------------------------------------------------------------------
# Load data
# -----------------------------------------------------------------------------
df, geojson, featureidkey, join_pct, n_baseline, n_geojson = load_and_join()

df_sorted = df.sort_values("stress_score", ascending=False).reset_index(drop=True)
df_sorted["rank"] = range(1, len(df_sorted) + 1)
df_map = df_sorted[df_sorted["_choropleth_loc"].notna()].copy()
loc_to_nta = dict(zip(df_map["_choropleth_loc"], df_map["nta2020"]))
default_nta = df_sorted.iloc[0]["nta2020"]
default_name = df_sorted.iloc[0].get("ntaname", df_sorted.iloc[0].get("NTAName", default_nta))
name_col = "NTAName" if "NTAName" in df_sorted.columns else "ntaname"

print(
    f"\n📊 Dashboard startup:\n"
    f"  baseline_index: {n_baseline} rows\n"
    f"  GeoJSON features: {n_geojson}\n"
    f"  Join match: {join_pct:.1f}%\n"
)

# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = Dash(__name__, suppress_callback_exceptions=True)

# IBM Plex Sans for MIT Sensible City Lab aesthetic
app.index_string = """<!DOCTYPE html>
<html>
    <head>
        <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
        {%metas%}
        <title>NYC Infrastructure Stress</title>
        {%favicon%}
        {%css%}
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
        dcc.Store(id="selected-nta", data=default_nta),
        # Header
        html.Header(
            [
                html.H1(
                    "NYC Infrastructure Stress Index",
                    style={
                        "fontFamily": "'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif",
                        "fontWeight": 600,
                        "fontSize": "1.75rem",
                        "letterSpacing": "-0.02em",
                        "marginBottom": "0.25rem",
                        "color": TEXT_PRIMARY,
                    },
                ),
                html.P(
                    "Identify neighborhoods with the highest infrastructure stress. "
                    "Explore heat vs. non-heat service drivers across NYC.",
                    style={
                        "fontFamily": "'IBM Plex Sans', system-ui, sans-serif",
                        "color": TEXT_MUTED,
                        "fontSize": "0.95rem",
                        "marginTop": 0,
                        "maxWidth": "560px",
                    },
                ),
            ],
            style={
                "marginBottom": "1.5rem",
                "paddingBottom": "1.25rem",
                "borderBottom": f"1px solid {BORDER}",
            },
        ),
        # Main content: map left, table right
        html.Div(
            [
                # Left: Map
                html.Div(
                    [
                        html.Div(
                            "Stress by Neighborhood",
                            style={
                                "fontFamily": "'IBM Plex Sans', system-ui, sans-serif",
                                "fontSize": "0.7rem",
                                "fontWeight": 600,
                                "color": TEXT_MUTED,
                                "textTransform": "uppercase",
                                "letterSpacing": "0.08em",
                                "marginBottom": "0.5rem",
                            },
                        ),
                        html.Div(
                            dcc.Graph(id="choropleth-map", config={"displayModeBar": True, "responsive": True}),
                            style={
                                "width": "100%",
                                "overflow": "hidden",
                                "borderRadius": "8px",
                                "border": f"1px solid {BORDER}",
                                "backgroundColor": BG_CARD,
                            },
                        ),
                    ],
                    style={"flex": "1 1 55%", "minWidth": 320, "marginRight": "1.5rem"},
                ),
                # Right: Table
                html.Div(
                    [
                        html.Div(
                            "NTA Ranking",
                            style={
                                "fontFamily": "'IBM Plex Sans', system-ui, sans-serif",
                                "fontSize": "0.7rem",
                                "fontWeight": 600,
                                "color": TEXT_MUTED,
                                "textTransform": "uppercase",
                                "letterSpacing": "0.08em",
                                "marginBottom": "0.5rem",
                            },
                        ),
                        dash_table.DataTable(
                            id="ranking-table",
                            columns=[
                                {"name": "Rank", "id": "rank", "type": "numeric"},
                                {"name": "Neighborhood", "id": name_col, "type": "text"},
                                {"name": "Stress", "id": "stress_score", "type": "numeric"},
                                {"name": "z_heat", "id": "z_heat", "type": "numeric"},
                                {"name": "z_nonheat", "id": "z_nonheat", "type": "numeric"},
                            ],
                            data=df_sorted[["rank", name_col, "stress_score", "z_heat", "z_nonheat"]]
                            .assign(
                                stress_score=df_sorted["stress_score"].round(2),
                                z_heat=df_sorted["z_heat"].round(2),
                                z_nonheat=df_sorted["z_nonheat"].round(2),
                            )
                            .to_dict("records"),
                            row_selectable="single",
                            selected_rows=[0],
                            sort_action="native",
                            sort_mode="single",
                            style_table={
                                "overflowX": "auto",
                                "width": "100%",
                                "minWidth": "100%",
                                "border": f"1px solid {BORDER}",
                                "borderRadius": "8px",
                                "backgroundColor": BG_CARD,
                            },
                            style_cell={
                                "textAlign": "left",
                                "padding": "10px 12px",
                                "fontFamily": "'IBM Plex Sans', system-ui, sans-serif",
                                "fontSize": "0.8rem",
                                "color": TEXT_PRIMARY,
                                "backgroundColor": BG_CARD,
                                "border": f"1px solid {BORDER}",
                            },
                            style_header={
                                "fontWeight": 600,
                                "backgroundColor": BG_HOVER,
                                "color": TEXT_PRIMARY,
                                "border": f"1px solid {BORDER}",
                            },
                            style_data_conditional=[
                                {"if": {"state": "selected"}, "backgroundColor": f"{ACCENT_CYAN}22"},
                                {"if": {"row_index": "odd"}, "backgroundColor": BG_HOVER},
                            ],
                            style_cell_conditional=[
                                {"if": {"column_id": "rank"}, "width": "52px"},
                                {"if": {"column_id": name_col}, "minWidth": "140px", "maxWidth": "200px"},
                                {"if": {"column_id": "stress_score"}, "width": "72px"},
                                {"if": {"column_id": "z_heat"}, "width": "72px"},
                                {"if": {"column_id": "z_nonheat"}, "width": "80px"},
                            ],
                        ),
                    ],
                    style={"flex": "1 1 40%", "minWidth": 280},
                ),
            ],
            style={"display": "flex", "flexWrap": "wrap", "gap": "1rem", "alignItems": "flex-start", "marginBottom": "1.5rem"},
        ),
        # Bottom: Selected NTA + Drivers chart
        html.Div(
            [
                html.Div(
                    id="selected-nta-label",
                    children=f"Selected: {default_name}",
                    style={
                        "fontFamily": "'IBM Plex Sans', system-ui, sans-serif",
                        "fontWeight": 600,
                        "fontSize": "1rem",
                        "marginBottom": "0.5rem",
                        "color": ACCENT_CYAN,
                    },
                ),
                html.Div(
                    "Drivers (z_heat vs z_nonheat)",
                    style={
                        "fontFamily": "'IBM Plex Sans', system-ui, sans-serif",
                        "fontSize": "0.7rem",
                        "fontWeight": 600,
                        "color": TEXT_MUTED,
                        "textTransform": "uppercase",
                        "letterSpacing": "0.08em",
                        "marginBottom": "0.5rem",
                    },
                ),
                html.Div(
                    dcc.Graph(id="drivers-chart", config={"displayModeBar": False, "responsive": True}),
                    style={
                        "borderRadius": "8px",
                        "border": f"1px solid {BORDER}",
                        "backgroundColor": BG_CARD,
                        "maxWidth": "480px",
                    },
                ),
            ],
            style={"marginTop": "0.5rem"},
        ),
    ],
    style={
        "fontFamily": "'IBM Plex Sans', system-ui, sans-serif",
        "maxWidth": "1280px",
        "margin": "0 auto",
        "padding": "2rem 1.5rem",
        "minHeight": "100vh",
        "backgroundColor": BG_DARK,
    },
)

# -----------------------------------------------------------------------------
# Callbacks
# -----------------------------------------------------------------------------
FEATUREIDKEY = f"properties.{featureidkey}"


@callback(Output("choropleth-map", "figure"), Input("selected-nta", "data"))
def update_map(selected_nta):
    fig = px.choropleth_map(
        df_map,
        geojson=geojson,
        locations="_choropleth_loc",
        featureidkey=FEATUREIDKEY,
        color="stress_score",
        color_continuous_scale=COLOR_SCALE,
        map_style=MAP_STYLE,
        center={"lat": 40.7, "lon": -73.95},
        zoom=9,
        opacity=0.75,
        hover_name=name_col,
        hover_data={"stress_score": ":.2f", "z_heat": ":.2f", "z_nonheat": ":.2f", "nta2020": False, "_choropleth_loc": False},
    )
    fig.update_layout(
        margin={"r": 12, "t": 12, "l": 12, "b": 12},
        coloraxis_colorbar_title="Stress Score",
        coloraxis_colorbar_tickfont_color=TEXT_MUTED,
        coloraxis_colorbar_title_font_color=TEXT_MUTED,
        height=420,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "'IBM Plex Sans', system-ui, sans-serif", "size": 11, "color": TEXT_PRIMARY},
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(showgrid=False, zeroline=False),
        uirevision="choropleth",
    )
    fig.update_traces(marker_line_width=0.5, marker_line_color=BORDER)
    return fig


@callback(
    Output("selected-nta", "data"),
    Input("choropleth-map", "clickData"),
    Input("ranking-table", "active_cell"),
    State("ranking-table", "data"),
    State("ranking-table", "derived_viewport_data"),
    State("selected-nta", "data"),
)
def update_selected_nta(click_data, active_cell, table_data, derived_data, current_nta):
    ctx = __import__("dash").callback_context
    if not ctx.triggered:
        return current_nta
    trigger_id = ctx.triggered[0]["prop_id"]
    if "choropleth-map" in trigger_id and click_data:
        loc = click_data.get("points", [{}])[0].get("location")
        if loc:
            return loc_to_nta.get(loc, loc)
    if "ranking-table" in trigger_id and active_cell is not None:
        data = derived_data if derived_data is not None else table_data
        if data and 0 <= active_cell["row"] < len(data):
            row = data[active_cell["row"]]
            rank_val = row.get("rank")
            match = df_sorted[df_sorted["rank"] == rank_val]
            if not match.empty:
                return match["nta2020"].iloc[0]
    return current_nta


@callback(
    Output("selected-nta-label", "children"),
    Output("ranking-table", "selected_rows"),
    Input("selected-nta", "data"),
)
def update_label_and_table_selection(selected_nta):
    if not selected_nta:
        return "Selected: —", []
    idx = df_sorted[df_sorted["nta2020"] == selected_nta].index
    if len(idx) == 0:
        return f"Selected: {selected_nta}", []
    row_idx = int(idx[0])
    name = df_sorted.iloc[row_idx].get(name_col, selected_nta)
    return f"Selected: {name}", [row_idx]


@callback(Output("drivers-chart", "figure"), Input("selected-nta", "data"))
def update_drivers_chart(selected_nta):
    if not selected_nta:
        return go.Figure().add_annotation(
            text="Select an NTA from the map or table",
            showarrow=False,
            font=dict(size=14, color=TEXT_MUTED),
        ).update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=200,
            margin=dict(t=40, b=40, l=40, r=40),
        )
    row = df_sorted[df_sorted["nta2020"] == selected_nta]
    if row.empty:
        return go.Figure().add_annotation(text="NTA not found", showarrow=False)
    row = row.iloc[0]
    z_heat = round(float(row["z_heat"]), 2)
    z_nonheat = round(float(row["z_nonheat"]), 2)
    fig = go.Figure(
        data=[
            go.Bar(name="z_heat", x=["Drivers"], y=[z_heat], marker_color="#f97316"),
            go.Bar(name="z_nonheat", x=["Drivers"], y=[z_nonheat], marker_color="#0ea5e9"),
        ]
    )
    fig.update_layout(
        barmode="group",
        xaxis_title="",
        yaxis_title="Z-Score",
        height=220,
        margin={"t": 20, "b": 50, "l": 50, "r": 20},
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=11, color=TEXT_PRIMARY),
            bgcolor="rgba(0,0,0,0)",
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "'IBM Plex Sans', system-ui, sans-serif", "size": 11, "color": TEXT_PRIMARY},
        xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(color=TEXT_MUTED)),
        yaxis=dict(showgrid=True, gridcolor=BORDER, zeroline=True, zerolinecolor=BORDER, tickfont=dict(color=TEXT_MUTED)),
    )
    return fig


def main():
    def _port_available(port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("127.0.0.1", port)) != 0

    port = int(os.environ.get("DASH_PORT", 8050))
    while not _port_available(port) and port < 8060:
        port += 1
    url = f"http://127.0.0.1:{port}/"
    print(f"\n  >>> Open in browser: {url} <<<\n")
    app.run(debug=True, host="0.0.0.0", port=port, use_reloader=False)


if __name__ == "__main__":
    main()
