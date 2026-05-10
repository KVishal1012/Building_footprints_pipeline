from __future__ import annotations

from html import escape
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import streamlit as st
from processing_semantics import infer_prediction_kind


MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_LAYERS_PATH = MODULE_DIR / "data/processing/output/processing_layers.parquet"
DEFAULT_LINKS_PATH = MODULE_DIR / "data/processing/output/structure_processing_links.parquet"
DEFAULT_METRICS_PATH = MODULE_DIR / "data/processing/output/processing_metrics.json"
ALL_CITIES_LABEL = "All cities"


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
    .method-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
    }
    .method-card {
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 12px;
        background: #fbfdfc;
        min-height: 126px;
    }
    .method-card.active {
        border-color: rgba(13,124,115,0.38);
        background: linear-gradient(180deg, rgba(13,124,115,0.10), #fbfdfc);
    }
    .method-card.future {
        border-style: dashed;
        background: #fffaf3;
    }
    .method-status {
        display: inline-flex;
        width: fit-content;
        border-radius: 999px;
        padding: 4px 8px;
        margin-bottom: 8px;
        color: #07514b;
        background: var(--teal-soft);
        font-size: 0.72rem;
        font-weight: 760;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .method-status.future {
        color: #714713;
        background: var(--amber-soft);
    }
    .method-title {
        color: var(--ink);
        font-size: 0.92rem;
        font-weight: 780;
        margin-bottom: 6px;
    }
    .method-copy {
        color: var(--muted);
        font-size: 0.78rem;
        line-height: 1.38;
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


def safe_text(value: object) -> str:
    return escape(str(value))


def mode_column(mode: str) -> str:
    lookup = {
        "Scenario": "Scenario",
        "LayerType": "LayerType",
        "SourceName": "SourceName",
    }
    return lookup[mode]


def available_columns(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    return [column for column in unique_columns(columns) if column in frame.columns]


def non_empty_unique(frame: pd.DataFrame, column: str) -> list[str]:
    if column not in frame.columns:
        return []
    values = frame[column].dropna().astype("string").str.strip()
    return sorted(value for value in values.unique().tolist() if value)


def format_timestamp(value: object) -> str:
    if value is None or pd.isna(value):
        return "Unavailable"
    timestamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(timestamp):
        return str(value)
    return timestamp.strftime("%Y-%m-%d %H:%M UTC")


def latest_run_timestamp(layers: pd.DataFrame | pd.Series) -> str:
    if isinstance(layers, pd.Series):
        timestamps = pd.to_datetime(layers, utc=True, errors="coerce").dropna()
        if timestamps.empty:
            return "Unavailable"
        return format_timestamp(timestamps.max())
    if layers.empty or "RunTimestamp" not in layers.columns:
        return "Unavailable"
    timestamps = pd.to_datetime(layers["RunTimestamp"], utc=True, errors="coerce").dropna()
    if timestamps.empty:
        return "Unavailable"
    return format_timestamp(timestamps.max())


def prediction_kind_series(layers: pd.DataFrame) -> pd.Series:
    if layers.empty:
        return pd.Series(dtype="string")
    if "PredictionKind" in layers.columns:
        return layers["PredictionKind"].astype("string").fillna("heuristic_baseline")
    return pd.Series(
        [
            infer_prediction_kind(
                explicit_kind=None,
                source_family=layers.iloc[i]["SourceFamily"] if "SourceFamily" in layers.columns else None,
                model_family=layers.iloc[i]["ModelFamily"] if "ModelFamily" in layers.columns else None,
                model_name=layers.iloc[i]["ModelName"] if "ModelName" in layers.columns else None,
                label=layers.iloc[i]["SourceName"] if "SourceName" in layers.columns else None,
            )
            for i in range(len(layers))
        ],
        index=layers.index,
        dtype="string",
    )


def prediction_method_status(layers: pd.DataFrame) -> dict[str, object]:
    kinds = set(prediction_kind_series(layers).dropna().astype("string").tolist())
    heuristic_loaded = "heuristic_baseline" in kinds or not kinds
    authoritative_loaded = "authoritative_context" in kinds
    model_loaded = "model_prediction" in kinds
    active_label = (
        "Model prediction"
        if model_loaded
        else "Authoritative GIS context"
        if authoritative_loaded
        else "Heuristic baseline"
    )
    active_detail = (
        "Model prediction layers are present in the selected outputs."
        if model_loaded
        else "Authoritative GIS context layers are present in the selected outputs."
        if authoritative_loaded
        else (
            "Scores are deterministic scenario indicators derived from OSM/context "
            "geometry and structure density. They are not deep-learning predictions."
        )
    )
    return {
        "active_label": active_label,
        "active_status": "Loaded" if model_loaded or authoritative_loaded else "Active",
        "active_detail": active_detail,
        "heuristic_loaded": heuristic_loaded,
        "authoritative_loaded": authoritative_loaded,
        "is_model_loaded": model_loaded,
    }


def filter_by_city(
    layers: gpd.GeoDataFrame, links: pd.DataFrame, selected_city: str
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    if selected_city == ALL_CITIES_LABEL or "City" not in layers.columns:
        return layers.copy(), links.copy()
    city_layers = layers[layers["City"].astype("string") == selected_city].copy()
    if "City" not in links.columns:
        return city_layers, links.copy()
    city_links = links[links["City"].astype("string") == selected_city].copy()
    return city_layers, city_links


def filter_by_group(
    layers: gpd.GeoDataFrame,
    links: pd.DataFrame,
    group_column: str,
    selected: list[str],
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    if not selected:
        return layers.iloc[0:0].copy(), links.iloc[0:0].copy()
    selected_values = {str(value) for value in selected}
    filtered_layers = layers[
        layers[group_column].astype("string").isin(selected_values)
    ].copy()
    filtered_links = links[
        links[group_column].astype("string").isin(selected_values)
    ].copy()
    return filtered_layers, filtered_links


def city_readiness(layers: pd.DataFrame, links: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "City",
        "layer_rows",
        "linked_rows",
        "linked_structures",
        "scenarios",
        "sources",
        "latest_run",
    ]
    if layers.empty or "City" not in layers.columns:
        return pd.DataFrame(columns=columns)
    layer_summary = (
        layers.groupby("City", dropna=False)
        .agg(
            layer_rows=("LayerID", "count"),
            scenarios=("Scenario", "nunique"),
            sources=("SourceName", "nunique"),
            latest_run=("RunTimestamp", latest_run_timestamp),
        )
        .reset_index()
    )
    if links.empty or "City" not in links.columns:
        link_summary = pd.DataFrame(columns=["City", "linked_rows", "linked_structures"])
    else:
        link_summary = (
            links.groupby("City", dropna=False)
            .agg(
                linked_rows=("StructureID", "count"),
                linked_structures=("StructureID", "nunique"),
            )
            .reset_index()
        )
    readiness = layer_summary.merge(link_summary, on="City", how="left")
    readiness[["linked_rows", "linked_structures"]] = readiness[
        ["linked_rows", "linked_structures"]
    ].fillna(0)
    for column in ("layer_rows", "linked_rows", "linked_structures", "scenarios", "sources"):
        readiness[column] = readiness[column].astype(int)
    return readiness[columns].sort_values("City").reset_index(drop=True)


def link_rate_value(metrics: dict, selected_city: str) -> float | None:
    if selected_city != ALL_CITIES_LABEL:
        return None
    value = metrics.get("link_rate")
    if value is None or pd.isna(value):
        return None
    return float(value)


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
        st.info("No baseline indicator rows match the current filters.")
        return
    for _, row in summary.head(limit).iterrows():
        label = safe_text(readable_label(row[group_column]))
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
                <div class="source-title">{safe_text(readable_label(row['SourceName']))}</div>
                <div class="source-count">{format_number(int(row['rows']))}</div>
                <div class="metric-note">{safe_text(readable_label(row['LayerType']))}</div>
            </div>
            """
        )
    st.markdown(f"<div class=\"source-grid\">{''.join(tiles)}</div>", unsafe_allow_html=True)


def render_prediction_method_panel(status: dict[str, object]) -> None:
    cards = [
        (
            "Heuristic baseline",
            "Available" if status["heuristic_loaded"] else "Not loaded",
            "Deterministic scenario indicators and proxy layers for comparison and fallback.",
            "active" if status["active_label"] == "Heuristic baseline" else "future",
        ),
        (
            "Authoritative GIS context",
            "Loaded" if status["authoritative_loaded"] else "Not loaded",
            "Official or operational context layers such as NRSC, Survey of India, IUDX, or municipal GIS.",
            "active" if status["active_label"] == "Authoritative GIS context" else "future",
        ),
        (
            "Model prediction",
            "Loaded" if status["is_model_loaded"] else "Not loaded",
            "Segmentation, flood, or change model outputs normalized through the processing pipeline.",
            "active" if status["active_label"] == "Model prediction" else "future",
        ),
    ]
    cards_html = []
    for title, badge, detail, tone in cards:
        cards_html.append(
            f"""
            <div class="method-card {tone}">
                <div class="method-status {'future' if tone == 'future' else ''}">{safe_text(badge)}</div>
                <div class="method-title">{safe_text(title)}</div>
                <div class="method-copy">{safe_text(detail)}</div>
            </div>
            """
        )
    st.markdown(
        f"""
        <div class="panel">
            <div class="panel-title">Prediction Method</div>
            <div class="panel-caption">Distinguishes heuristic baselines, authoritative GIS context, and model predictions in the selected outputs.</div>
            <div class="method-grid">
                {''.join(cards_html)}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="Urban Scenario Review",
        page_icon=":bar_chart:",
        layout="wide",
    )
    st.markdown(APP_CSS, unsafe_allow_html=True)

    with st.sidebar:
        st.header("Review Inputs")
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
    readiness = city_readiness(layers, links)
    prediction_status = prediction_method_status(layers)

    with st.sidebar:
        city_options = sorted(layers["City"].dropna().astype("string").unique().tolist())
        city_choices = [ALL_CITIES_LABEL] + city_options
        selected_city = (
            st.selectbox("City", city_choices, index=0) if city_options else "All cities"
        )
        st.caption(
            f"Available cities: {', '.join(city_options) if city_options else 'none loaded'}"
        )
        layers, links = filter_by_city(layers, links, selected_city)
        options = sorted(
            layers[group_column].dropna().astype("string").unique().tolist()
        )
        selected = st.multiselect(display_mode, options, default=options)
        review_requested = st.button("Apply Review Filters", use_container_width=True)
        st.caption(
            "Controls filter existing pipeline outputs only. No model inference or new simulation run is triggered."
        )

    filtered_layers, filtered_links = filter_by_group(layers, links, group_column, selected)
    summary = mode_summary(filtered_layers, filtered_links, display_mode)
    sources = source_summary(filtered_layers)
    link_rate = link_rate_value(metrics, selected_city)
    scenario_count = int(filtered_layers["Scenario"].nunique()) if "Scenario" in filtered_layers else 0
    source_count = int(filtered_layers["SourceName"].nunique()) if "SourceName" in filtered_layers else 0
    latest_timestamp = latest_run_timestamp(filtered_layers)
    linked_structures = filtered_links["StructureID"].nunique() if "StructureID" in filtered_links else 0
    active_method = str(prediction_status["active_label"])
    loaded_mode = (
        "Model output loaded"
        if prediction_status["is_model_loaded"]
        else "Authoritative context loaded"
        if prediction_status["authoritative_loaded"]
        else "No AI model loaded"
    )

    st.markdown(
        f"""
        <section class="app-shell">
            <div class="topbar">
                <div>
                    <div class="eyebrow">Baseline Scenario Review</div>
                    <h1 class="title">Urban Scenario Review Dashboard</h1>
                    <div class="subtitle">Review structure-linked outputs across heuristic baselines, authoritative GIS context, and model predictions for urban planning analysis.</div>
                </div>
                <div class="status-row">
                    <span class="chip teal">{safe_text(selected_city)}</span>
                    <span class="chip">{safe_text(display_mode)}</span>
                    <span class="chip amber">{safe_text(active_method)}</span>
                    <span class="chip">{safe_text(loaded_mode)}</span>
                </div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if review_requested:
        st.toast("Review filters applied to existing processing outputs.")

    kpi1, kpi2, kpi3, kpi4, kpi5, kpi6 = st.columns(6)
    with kpi1:
        render_metric_card("Layer Rows", format_number(len(filtered_layers)), "processing-layer features")
    with kpi2:
        render_metric_card("Linked Structures", format_number(linked_structures), "unique matched structures")
    with kpi3:
        render_metric_card(
            "Link Rate",
            format_percent(link_rate) if link_rate is not None else "n/a",
            "requires total structures denominator" if link_rate is None else "all-city coverage",
        )
    with kpi4:
        render_metric_card("Scenarios", format_number(scenario_count), "active scenario IDs")
    with kpi5:
        render_metric_card("Sources", format_number(source_count), "active source layers")
    with kpi6:
        render_metric_card("Data Timestamp", latest_timestamp, "latest selected run")

    st.markdown(
        """
        <div class="panel">
            <div class="panel-title">City Data Readiness</div>
            <div class="panel-caption">Loaded city coverage for the current processing outputs. Chennai and Bengaluru are expected in this build.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.dataframe(
        readiness,
        width="stretch",
        hide_index=True,
        column_config={
            "layer_rows": st.column_config.NumberColumn("Layer Rows", format="%d"),
            "linked_rows": st.column_config.NumberColumn("Link Rows", format="%d"),
            "linked_structures": st.column_config.NumberColumn("Linked Structures", format="%d"),
            "scenarios": st.column_config.NumberColumn("Scenarios", format="%d"),
            "sources": st.column_config.NumberColumn("Sources", format="%d"),
        },
    )

    map_col, control_col = st.columns([1.65, 0.85], gap="large")

    with map_col:
        st.markdown(
            f"""
            <div class="panel">
                <div class="panel-title">{safe_text(display_mode)} Baseline Indicator Map</div>
                <div class="panel-caption">Sampled high-score processing outputs rendered as geographic review points. This is not a live model inference run.</div>
                <div class="legend-row">
                    <span class="legend-item"><span class="dot teal"></span>Authoritative context</span>
                    <span class="legend-item"><span class="dot amber"></span>Urban planning</span>
                    <span class="legend-item"><span class="dot red"></span>Flood / model layer</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if filtered_layers.empty:
            st.info("Select at least one city and output group to view baseline indicators.")
        else:
            sample = map_sample(filtered_layers, max_map_features, display_mode)
            st.map(sample[["lat", "lon"]], latitude="lat", longitude="lon", size=18)
        timeline_step = st.slider("Scenario horizon marker", 0, 100, 65, step=5)
        st.caption(f"Review marker: {timeline_step}% of selected scenario horizon. This control does not execute a forecast.")

    with control_col:
        render_prediction_method_panel(prediction_status)

        st.markdown(
            """
            <div class="panel">
                <div class="panel-title">Output Stack</div>
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
                <div class="panel-caption">Input layers feeding the current baseline output.</div>
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
        source_table_columns = available_columns(filtered_layers, source_columns)
        source_table = filtered_layers[source_table_columns].drop_duplicates()
        if group_column in source_table.columns:
            source_table = source_table.sort_values(group_column)
        st.dataframe(source_table, width="stretch", hide_index=True)

    with tab_links:
        link_columns = available_columns(
            filtered_links,
            [
                group_column,
                "StructureID",
                "Label",
                "Score",
                "MatchMethod",
                "MatchArea_m2",
                "StructureCoverage",
                "LayerCoverage",
            ],
        )
        link_table = filtered_links[link_columns]
        if group_column in link_table.columns and "Score" in link_table.columns:
            link_table = link_table.sort_values([group_column, "Score"], ascending=[True, False])
        st.dataframe(
            link_table,
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
            "scenario_count": scenario_count,
            "source_count": source_count,
            "selected_city": selected_city,
            "display_mode": display_mode,
            "prediction_method": active_method,
            "model_prediction_loaded": bool(prediction_status["is_model_loaded"]),
            "latest_selected_run": latest_timestamp,
            "metrics_generated_at_utc": metrics.get("generated_at_utc"),
        }
        st.json(metric_payload)
        metric_columns = available_columns(
            filtered_layers,
            [
                group_column,
                "Label",
                "Score",
                "Value",
                "SourceName",
                "SourceAuthority",
                "RunID",
            ],
        )
        metric_table = filtered_layers[metric_columns]
        if group_column in metric_table.columns and "Score" in metric_table.columns:
            metric_table = metric_table.sort_values([group_column, "Score"], ascending=[True, False])
        st.dataframe(
            metric_table,
            width="stretch",
            hide_index=True,
        )


if __name__ == "__main__":
    main()
