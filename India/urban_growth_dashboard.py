from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import streamlit as st


MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_LAYERS_PATH = MODULE_DIR / "data/processing/output/processing_layers.parquet"
DEFAULT_LINKS_PATH = MODULE_DIR / "data/processing/output/structure_processing_links.parquet"
DEFAULT_METRICS_PATH = MODULE_DIR / "data/processing/output/processing_metrics.json"


APP_CSS = """
<style>
    :root {
        --ink: #15211f;
        --muted: #5f6f6a;
        --line: #dbe5df;
        --surface: #f7faf8;
        --panel: #ffffff;
        --teal: #0d7c73;
        --teal-soft: #d9f0ec;
        --amber: #c57d1f;
        --amber-soft: #f8ead6;
        --danger: #b84531;
    }
    .block-container {
        padding-top: 1.25rem;
        padding-bottom: 2rem;
        max-width: 1500px;
    }
    [data-testid="stSidebar"] {
        background: #f2f7f4;
        border-right: 1px solid var(--line);
    }
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        color: var(--ink);
    }
    .app-shell {
        background:
            linear-gradient(135deg, rgba(13,124,115,0.08), rgba(197,125,31,0.06)),
            var(--surface);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 18px 18px 14px;
        margin-bottom: 18px;
    }
    .topbar {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 18px;
    }
    .eyebrow {
        color: var(--teal);
        font-size: 0.74rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-bottom: 4px;
    }
    .title {
        color: var(--ink);
        font-size: 2rem;
        font-weight: 760;
        line-height: 1.05;
        margin: 0;
    }
    .subtitle {
        color: var(--muted);
        font-size: 0.98rem;
        margin-top: 8px;
        max-width: 840px;
    }
    .status-row {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        justify-content: flex-end;
    }
    .chip {
        border: 1px solid var(--line);
        border-radius: 999px;
        padding: 7px 10px;
        color: var(--ink);
        background: var(--panel);
        font-size: 0.78rem;
        font-weight: 650;
        white-space: nowrap;
    }
    .chip.teal {
        border-color: rgba(13,124,115,0.28);
        background: var(--teal-soft);
        color: #07514b;
    }
    .chip.amber {
        border-color: rgba(197,125,31,0.28);
        background: var(--amber-soft);
        color: #714713;
    }
    .metric-card {
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 14px 15px;
        background: var(--panel);
        min-height: 92px;
    }
    .metric-label {
        color: var(--muted);
        font-size: 0.77rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 9px;
    }
    .metric-value {
        color: var(--ink);
        font-size: 1.65rem;
        font-weight: 780;
        line-height: 1;
    }
    .metric-note {
        color: var(--muted);
        font-size: 0.78rem;
        margin-top: 8px;
    }
    .panel {
        border: 1px solid var(--line);
        border-radius: 8px;
        background: var(--panel);
        padding: 16px;
        margin-bottom: 14px;
    }
    .panel-title {
        color: var(--ink);
        font-size: 1rem;
        font-weight: 760;
        margin-bottom: 4px;
    }
    .panel-caption {
        color: var(--muted);
        font-size: 0.82rem;
        margin-bottom: 12px;
    }
    .legend-row {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin: 10px 0 2px;
    }
    .legend-item {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        color: var(--muted);
        font-size: 0.78rem;
        border: 1px solid var(--line);
        border-radius: 999px;
        padding: 6px 9px;
        background: #fbfdfc;
    }
    .dot {
        width: 8px;
        height: 8px;
        border-radius: 999px;
        display: inline-block;
    }
    .dot.teal { background: var(--teal); }
    .dot.amber { background: var(--amber); }
    .dot.red { background: var(--danger); }
    .stack-item {
        border-top: 1px solid var(--line);
        padding: 11px 0;
    }
    .stack-name {
        color: var(--ink);
        font-weight: 720;
        font-size: 0.86rem;
        overflow-wrap: anywhere;
    }
    .stack-meta {
        color: var(--muted);
        font-size: 0.76rem;
        margin-top: 3px;
    }
    .source-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
    }
    .source-tile {
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 10px;
        background: #fbfdfc;
    }
    .source-title {
        color: var(--ink);
        font-size: 0.82rem;
        font-weight: 720;
        overflow-wrap: anywhere;
    }
    .source-count {
        color: var(--teal);
        font-size: 1.05rem;
        font-weight: 780;
        margin-top: 5px;
    }
    div[data-testid="stTabs"] button p {
        font-weight: 650;
    }
    .stButton > button {
        border-radius: 7px;
        background: var(--teal);
        color: white;
        border: 1px solid var(--teal);
        font-weight: 700;
    }
    .stButton > button:hover {
        background: #09635c;
        border-color: #09635c;
        color: white;
    }
</style>
"""


@st.cache_data(show_spinner=False)
def load_layers(path: str, file_mtime: float) -> gpd.GeoDataFrame:
    return gpd.read_parquet(path)


@st.cache_data(show_spinner=False)
def load_links(path: str, file_mtime: float) -> pd.DataFrame:
    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def load_metrics(path: str, file_mtime: float | None) -> dict:
    if not Path(path).exists():
        return {}
    return json.loads(Path(path).read_text())


def format_number(value: int | float) -> str:
    return f"{value:,.0f}"


def format_percent(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "0.00%"
    return f"{float(value):.2%}"


def unique_columns(columns: list[str]) -> list[str]:
    seen = set()
    out = []
    for column in columns:
        if column in seen:
            continue
        seen.add(column)
        out.append(column)
    return out


def readable_label(value: str) -> str:
    return str(value).replace("_", " ").title()


def mode_column(mode: str) -> str:
    lookup = {
        "Scenario": "Scenario",
        "LayerType": "LayerType",
        "SourceName": "SourceName",
    }
    return lookup[mode]


def mode_summary(
    layers: gpd.GeoDataFrame, links: pd.DataFrame, mode: str
) -> pd.DataFrame:
    group_column = mode_column(mode)
    layer_summary = (
        layers.groupby(group_column, dropna=False)
        .agg(
            layer_rows=("LayerID", "count"),
            min_score=("Score", "min"),
            mean_score=("Score", "mean"),
            max_score=("Score", "max"),
        )
        .reset_index()
    )
    link_summary = (
        links.groupby(group_column, dropna=False)
        .agg(
            structure_links=("StructureID", "count"),
            linked_structures=("StructureID", "nunique"),
        )
        .reset_index()
    )
    summary = layer_summary.merge(link_summary, on=group_column, how="left")
    summary[["structure_links", "linked_structures"]] = summary[
        ["structure_links", "linked_structures"]
    ].fillna(0)
    return summary.sort_values(group_column).reset_index(drop=True)


def source_summary(layers: gpd.GeoDataFrame) -> pd.DataFrame:
    if layers.empty:
        return pd.DataFrame(columns=["SourceName", "LayerType", "rows"])
    return (
        layers.groupby(["SourceName", "LayerType"], dropna=False)
        .agg(rows=("LayerID", "count"))
        .reset_index()
        .sort_values("rows", ascending=False)
    )


def map_sample(layers: gpd.GeoDataFrame, max_features: int, mode: str) -> gpd.GeoDataFrame:
    group_column = mode_column(mode)
    if len(layers) <= max_features:
        sample = layers.copy()
    else:
        sample = (
            layers.sort_values("Score", ascending=False)
            .groupby(group_column, group_keys=False)
            .head(max(1, max_features // max(1, layers[group_column].nunique())))
        )
        sample = sample.head(max_features)
    sample = sample.to_crs(epsg=4326).copy()
    sample["lon"] = sample.geometry.representative_point().x
    sample["lat"] = sample.geometry.representative_point().y
    return sample


def render_metric_card(label: str, value: str, note: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_scenario_stack(summary: pd.DataFrame, group_column: str, limit: int = 8) -> None:
    if summary.empty:
        st.info("No scenario rows match the current filters.")
        return
    for _, row in summary.head(limit).iterrows():
        label = readable_label(row[group_column])
        linked = int(row.get("linked_structures", 0))
        layer_rows = int(row.get("layer_rows", 0))
        mean_score = row.get("mean_score")
        score_text = "n/a" if pd.isna(mean_score) else f"{float(mean_score):.3f}"
        st.markdown(
            f"""
            <div class="stack-item">
                <div class="stack-name">{label}</div>
                <div class="stack-meta">{format_number(layer_rows)} rows | {format_number(linked)} linked structures | avg score {score_text}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_source_tiles(summary: pd.DataFrame, limit: int = 6) -> None:
    if summary.empty:
        st.info("No source rows match the current filters.")
        return
    tiles = []
    for _, row in summary.head(limit).iterrows():
        tiles.append(
            f"""
            <div class="source-tile">
                <div class="source-title">{readable_label(row['SourceName'])}</div>
                <div class="source-count">{format_number(int(row['rows']))}</div>
                <div class="metric-note">{readable_label(row['LayerType'])}</div>
            </div>
            """
        )
    st.markdown(f"<div class=\"source-grid\">{''.join(tiles)}</div>", unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(
        page_title="Urban Scenario Simulator",
        page_icon=":bar_chart:",
        layout="wide",
    )
    st.markdown(APP_CSS, unsafe_allow_html=True)

    with st.sidebar:
        st.header("Simulation Inputs")
        layers_path = st.text_input("Processing layers parquet", str(DEFAULT_LAYERS_PATH))
        links_path = st.text_input("Structure links parquet", str(DEFAULT_LINKS_PATH))
        metrics_path = st.text_input("Metrics JSON", str(DEFAULT_METRICS_PATH))
        display_mode = st.selectbox(
            "Display Mode",
            ["Scenario", "LayerType", "SourceName"],
            index=0,
        )
        max_map_features = st.slider("Map feature sample", 500, 10000, 2500, step=500)

    layers_file = Path(layers_path)
    links_file = Path(links_path)
    if not layers_file.exists() or not links_file.exists():
        st.error("Processing outputs are missing. Populate scenario layers and run processing first.")
        st.code(
            ".venv/bin/python India/populate_real_scenario_layers.py --city Chennai --state \"Tamil Nadu\" --country India\n"
            ".venv/bin/python scripts/run_india_realworld_sequence.py --config India/realworld_sequence_config.example.json --skip-osm-first --skip-full-sources",
            language="bash",
        )
        return

    metrics_file = Path(metrics_path)
    layers = load_layers(str(layers_file), layers_file.stat().st_mtime).copy()
    links = load_links(str(links_file), links_file.stat().st_mtime).copy()
    metrics = load_metrics(
        metrics_path, metrics_file.stat().st_mtime if metrics_file.exists() else None
    )
    group_column = mode_column(display_mode)
    options = sorted(
        layers[group_column].dropna().astype("string").unique().tolist()
    )

    with st.sidebar:
        city_options = sorted(layers["City"].dropna().astype("string").unique().tolist())
        city_choices = ["All cities"] + city_options
        selected_city = (
            st.selectbox("City", city_choices, index=0) if city_options else "All cities"
        )
        selected = st.multiselect(display_mode, options, default=options)
        run_requested = st.button("Run Simulation", use_container_width=True)
        st.caption("Controls filter the current pipeline outputs. The run button marks a review state in this UI.")

    if selected_city != "All cities":
        layers = layers[layers["City"].astype("string") == selected_city].copy()
        links = links[links["City"].astype("string") == selected_city].copy()
    filtered_layers = layers[layers[group_column].astype("string").isin(selected)].copy()
    filtered_links = links[links[group_column].astype("string").isin(selected)].copy()
    summary = mode_summary(filtered_layers, filtered_links, display_mode)
    sources = source_summary(filtered_layers)
    link_rate = (
        filtered_links["StructureID"].nunique() / metrics.get("total_structures", len(layers))
        if metrics.get("total_structures", len(layers)) else 0
    )

    st.markdown(
        f"""
        <section class="app-shell">
            <div class="topbar">
                <div>
                    <div class="eyebrow">Geospatial Simulation Workspace</div>
                    <h1 class="title">Urban Scenario Simulator</h1>
                    <div class="subtitle">Real OSM context and derived scenario indicators for structure-level planning review.</div>
                </div>
                <div class="status-row">
                    <span class="chip teal">{selected_city}</span>
                    <span class="chip">{display_mode}</span>
                    <span class="chip amber">Pipeline outputs</span>
                </div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if run_requested:
        st.toast("Simulation review filters applied.")

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        render_metric_card(display_mode, format_number(filtered_layers[group_column].nunique()), "active groups")
    with kpi2:
        render_metric_card("Layer Rows", format_number(len(filtered_layers)), "scenario features")
    with kpi3:
        render_metric_card("Structure Links", format_number(len(filtered_links)), "matched records")
    with kpi4:
        render_metric_card("Link Rate", format_percent(link_rate), f"{format_number(filtered_links['StructureID'].nunique())} structures")

    map_col, control_col = st.columns([1.65, 0.85], gap="large")

    with map_col:
        st.markdown(
            f"""
            <div class="panel">
                <div class="panel-title">{display_mode} Simulation Map</div>
                <div class="panel-caption">Sampled high-score outputs, rendered as geographic simulation points.</div>
                <div class="legend-row">
                    <span class="legend-item"><span class="dot teal"></span>Planning context</span>
                    <span class="legend-item"><span class="dot amber"></span>Urban planning</span>
                    <span class="legend-item"><span class="dot red"></span>Flood prediction</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if filtered_layers.empty:
            st.info("Select at least one output group.")
        else:
            sample = map_sample(filtered_layers, max_map_features, display_mode)
            st.map(sample[["lat", "lon"]], latitude="lat", longitude="lon", size=18)
        timeline_step = st.slider("Simulation timeline", 0, 100, 65, step=5)
        st.caption(f"Review frame: {timeline_step}% of selected scenario horizon")

    with control_col:
        st.markdown(
            """
            <div class="panel">
                <div class="panel-title">Scenario Stack</div>
                <div class="panel-caption">Highest-level output groups available for current filters.</div>
            """,
            unsafe_allow_html=True,
        )
        render_scenario_stack(summary, group_column)
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown(
            """
            <div class="panel">
                <div class="panel-title">Source Layers</div>
                <div class="panel-caption">Input layers feeding the simulation output.</div>
            """,
            unsafe_allow_html=True,
        )
        render_source_tiles(sources)
        st.markdown("</div>", unsafe_allow_html=True)

    tab_map, tab_sources, tab_links, tab_metrics = st.tabs(["Map", "Sources", "Links", "Metrics"])

    with tab_map:
        st.dataframe(
            summary,
            width="stretch",
            hide_index=True,
            column_config={
                "min_score": st.column_config.NumberColumn("Min Score", format="%.4f"),
                "mean_score": st.column_config.NumberColumn("Mean Score", format="%.4f"),
                "max_score": st.column_config.NumberColumn("Max Score", format="%.4f"),
            },
        )

    with tab_sources:
        source_columns = unique_columns(
            [
                group_column,
                "SourceName",
                "SourceAuthority",
                "ModelFamily",
                "ModelName",
                "ModelVersion",
                "Task",
                "RunID",
                "RunTimestamp",
            ]
        )
        source_table = (
            filtered_layers[source_columns]
            .drop_duplicates()
            .sort_values(group_column)
        )
        st.dataframe(source_table, width="stretch", hide_index=True)

    with tab_links:
        st.dataframe(
            filtered_links[
                unique_columns([
                    group_column,
                    "StructureID",
                    "Label",
                    "Score",
                    "MatchMethod",
                    "MatchArea_m2",
                    "StructureCoverage",
                    "LayerCoverage",
                ])
            ].sort_values([group_column, "Score"], ascending=[True, False]),
            width="stretch",
            hide_index=True,
        )

    with tab_metrics:
        metric_payload = {
            "total_layer_rows": metrics.get("total_layer_rows", len(layers)),
            "total_links": metrics.get("total_links", len(links)),
            "unique_linked_structures": metrics.get(
                "unique_linked_structures", links["StructureID"].nunique()
            ),
            "link_rate": metrics.get("link_rate", link_rate),
            "scenario_count": int(layers["Scenario"].nunique()),
        }
        st.json(metric_payload)
        st.dataframe(
            filtered_layers[
                unique_columns([
                    group_column,
                    "Label",
                    "Score",
                    "Value",
                    "SourceName",
                    "SourceAuthority",
                    "RunID",
                ])
            ].sort_values([group_column, "Score"], ascending=[True, False]),
            width="stretch",
            hide_index=True,
        )


if __name__ == "__main__":
    main()
