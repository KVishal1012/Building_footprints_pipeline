from __future__ import annotations

import json
import logging
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any


PATH_FIELD_NAMES = {"data_dir", "output_dir", "raw_dir", "cache_dir", "structure_path"}


def configure_logging(level: str = "INFO") -> None:
    numeric_level = getattr(logging, str(level).upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Unsupported logging level: {level!r}")
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def parse_places(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("Config must include a non-empty 'places' list")

    places = []
    for item in value:
        if isinstance(item, str):
            if "," not in item:
                raise ValueError(f"Place string must be 'City, State': {item!r}")
            city, state = item.rsplit(",", 1)
            place = {"city": city.strip(), "state": state.strip()}
        elif isinstance(item, dict):
            place = {"city": str(item.get("city", "")).strip(), "state": str(item.get("state", "")).strip()}
        else:
            raise ValueError(f"Place must be a string or object: {item!r}")

        if not place["city"] or not place["state"]:
            raise ValueError(f"Place must include city and state: {item!r}")
        places.append(place)
    return places


def config_section(payload: dict[str, Any]) -> dict[str, Any]:
    config = payload.get("config", {})
    if not isinstance(config, dict):
        raise ValueError("'config' must be a JSON object when provided")
    return config


def logging_level(payload: dict[str, Any]) -> str:
    logging_config = payload.get("logging", {})
    if logging_config is None:
        return "INFO"
    if not isinstance(logging_config, dict):
        raise ValueError("'logging' must be a JSON object when provided")
    return str(logging_config.get("level", "INFO"))


def resolve_config_path(value: str | Path, repo_root: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return repo_root / path


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate_not_in_venv(name: str, path: Path, repo_root: Path) -> None:
    venv_path = repo_root / ".venv"
    if _is_relative_to(path, venv_path):
        raise ValueError(f"{name} must not point inside .venv: {path}")


def dataclass_config_kwargs(
    config: dict[str, Any],
    dataclass_type,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    if not is_dataclass(dataclass_type):
        raise TypeError("dataclass_config_kwargs expects a dataclass type")

    field_names = {field.name for field in fields(dataclass_type)}
    unknown = sorted(set(config) - field_names)
    if unknown:
        raise ValueError(
            f"Unknown config field(s) for {dataclass_type.__name__}: {', '.join(unknown)}"
        )

    kwargs = dict(config)
    for name in PATH_FIELD_NAMES & set(kwargs):
        kwargs[name] = resolve_config_path(kwargs[name], repo_root)
        validate_not_in_venv(name, kwargs[name], repo_root)
    return kwargs


def source_config_path(payload: dict[str, Any], repo_root: Path) -> Path:
    value = payload.get("source_config")
    if not value:
        raise ValueError("Config must include 'source_config'")
    path = resolve_config_path(value, repo_root)
    validate_not_in_venv("source_config", path, repo_root)
    return path
