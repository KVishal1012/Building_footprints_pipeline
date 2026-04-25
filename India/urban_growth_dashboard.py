from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
import streamlit as st


MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_LAYERS_PATH = MODULE_DIR / "data/processing/output/processing_layers.parquet"
DEFAULT_LINKS_PATH = MODULE_DIR / "data/processing/output/structure_processing_links.parquet"


@st.cache_data(show_spinner=False)
def load_layers(path: str) -> gpd.GeoDataFrame:
    return gpd.read_parquet(path)


@st.cache_data(show_spinner=False)
def load_links(path: str) -> pd.DataFrame:
    return pd.read_parquet(path)


def format_number(value: int | float) -> str:
    return f"{value:,.0f}"


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


def main() -> None:
    st.set_page_config(
        page_title="India Urban Growth Dashboard",
        page_icon="🏙️",
        layout="wide",
    )
    st.title("India Urban Growth Scenario Dashboard")
    st.caption("Real OSM context + derived scenario indicators")

    st.warning(
        "These layers combine real OSM context data (for example transit, water, wetlands) "
        "with derived scenario indicators. They are planning-support inputs, not statutory authority layers."
    )

    with st.sidebar:
        st.header("Data")
        layers_path = st.text_input("Processing layers parquet", str(DEFAULT_LAYERS_PATH))
        links_path = st.text_input("Structure links parquet", str(DEFAULT_LINKS_PATH))
        display_mode = st.selectbox(
            "Display Mode",
            ["Scenario", "LayerType", "SourceName"],
            index=0,
        )
        max_map_features = st.slider("Map feature sample", 500, 10000, 2500, step=500)
        st.caption("The map samples high-score features to keep the dashboard responsive.")

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

    layers = load_layers(str(layers_file)).copy()
    links = load_links(str(links_file)).copy()
    group_column = mode_column(display_mode)
    options = sorted(
        layers[group_column].dropna().astype("string").unique().tolist()
    )

    with st.sidebar:
        selected = st.multiselect(display_mode, options, default=options)

    filtered_layers = layers[layers[group_column].astype("string").isin(selected)].copy()
    filtered_links = links[links[group_column].astype("string").isin(selected)].copy()

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric(display_mode, format_number(filtered_layers[group_column].nunique()))
    kpi2.metric("Layer Rows", format_number(len(filtered_layers)))
    kpi3.metric("Structure Links", format_number(len(filtered_links)))
    kpi4.metric("Linked Structures", format_number(filtered_links["StructureID"].nunique()))

    st.divider()
    left, right = st.columns([1.15, 0.85])

    with left:
        st.subheader(f"{display_mode} Map")
        if filtered_layers.empty:
            st.info("Select at least one scenario.")
        else:
            sample = map_sample(filtered_layers, max_map_features, display_mode)
            st.map(sample[["lat", "lon"]], latitude="lat", longitude="lon", size=18)

    with right:
        st.subheader(f"{display_mode} Summary")
        summary = mode_summary(filtered_layers, filtered_links, display_mode)
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

    st.divider()
    tab_layers, tab_links, tab_sources = st.tabs(["Layer Rows", "Structure Links", "Sources"])

    with tab_layers:
        st.dataframe(
            filtered_layers[
                [
                    group_column,
                    "Label",
                    "Score",
                    "Value",
                    "SourceName",
                    "SourceAuthority",
                    "RunID",
                ]
            ].sort_values([group_column, "Score"], ascending=[True, False]),
            width="stretch",
            hide_index=True,
        )

    with tab_links:
        st.dataframe(
            filtered_links[
                [
                    group_column,
                    "StructureID",
                    "Label",
                    "Score",
                    "MatchMethod",
                    "MatchArea_m2",
                    "StructureCoverage",
                    "LayerCoverage",
                ]
            ].sort_values([group_column, "Score"], ascending=[True, False]),
            width="stretch",
            hide_index=True,
        )

    with tab_sources:
        source_table = (
            filtered_layers[
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
            ]
            .drop_duplicates()
            .sort_values(group_column)
        )
        st.dataframe(source_table, width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
