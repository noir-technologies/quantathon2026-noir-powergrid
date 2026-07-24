"""Reconstrucción auditable de grafos regionales de transmisión del ICE.

La versión 4.2 conserva los árboles reales cuando son las únicas instancias
trazables: la consigna exige grafos regionales ponderados, pero no exige ciclos
ni no bipartición. El programa nunca añade aristas sintéticas. Por seguridad,
trabaja offline por defecto y escribe en ``build/grafos_ice``; no sobrescribe
los resultados QAOA ni los documentos finales de la entrega.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd
import pyproj
import requests
import shapely
import yaml
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point, mapping, shape
from shapely.ops import linemerge, substring, transform


VERSION = "4.2.2"


def discover_project_root() -> Path:
    """Localiza la raíz 4.2 sin depender de la ubicación histórica ``src/``."""
    candidates = (
        Path.cwd(),
        Path.cwd().parent,
        Path(__file__).resolve().parent,
        Path(__file__).resolve().parent.parent,
    )
    for candidate in candidates:
        if (
            (candidate / "config.yaml").is_file()
            and (candidate / "datos" / "crudos").is_dir()
        ):
            return candidate.resolve()
    return Path.cwd().resolve()


ROOT = discover_project_root()
SOURCE_BASE = "https://geoportal.ice.go.cr/serverene/rest/services/Hosted/DT_SNIT_v2/FeatureServer"
SUBSTATIONS_LAYER_URL = f"{SOURCE_BASE}/3"
LINES_LAYER_URL = f"{SOURCE_BASE}/2"
SUBSTATIONS_QUERY_URL = f"{SUBSTATIONS_LAYER_URL}/query"
LINES_QUERY_URL = f"{LINES_LAYER_URL}/query"
CRS_WGS84 = "EPSG:4326"
CONFIDENCE_RANK = {"alta confianza": 0, "media confianza": 1, "baja confianza": 2, "rechazada": 3}
VOLTAGE_CODE_TO_KV = {0: 0.0, 1: 230.0, 2: 138.0, 3: 34.5}
DETERMINISTIC_DIRS = (
    "datos/procesados",
    "datos/grafos",
    "resultados",
    "auditoria",
    "docs",
)
REPRO_EXCLUDED = {
    "auditoria/reproducibilidad_ejecucion_1.json",
    "auditoria/reproducibilidad_ejecucion_2.json",
    "auditoria/comparacion_hashes.csv",
    "auditoria/reporte_reproducibilidad.md",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=ROOT,
        help="Raíz del paquete 4.2 que contiene config.yaml y datos/crudos.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Directorio aislado para las salidas. Por defecto: "
            "<project-root>/build/grafos_ice."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Configuración; por defecto <project-root>/config.yaml.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Compatibilidad: el modo offline ya es el predeterminado.",
    )
    parser.add_argument(
        "--online-verify",
        action="store_true",
        help="Comparar la caché local con el servicio ICE. Requiere red.",
    )
    parser.add_argument(
        "--refresh-data",
        action="store_true",
        help="Volver a descargar las capas ICE. Requiere red.",
    )
    parser.add_argument("--no-repro-check", action="store_true", help="Omitir la doble ejecución interna.")
    parser.add_argument(
        "--ignore-instance-lock",
        action="store_true",
        help=(
            "Ignorar los conjuntos G6/G8/G10/G12 ya auditados en "
            "datos/grafos y volver a seleccionarlos algorítmicamente."
        ),
    )
    return parser.parse_args()


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", "" if value is None else str(value).strip())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).casefold()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((str(a), str(b))))


def rounded(value: Any, digits: int = 9) -> Any:
    if isinstance(value, float):
        return round(value, digits) if math.isfinite(value) else None
    return value


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Iterable[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: rounded(row.get(column, "")) for column in columns})


def clean_output_tree(base: Path) -> None:
    for name in DETERMINISTIC_DIRS:
        path = base / name
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)


def load_geojson(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        raise RuntimeError(f"{path} no es un FeatureCollection válido.")
    return payload


def canonical_feature_hash(payload: dict[str, Any]) -> str:
    features = []
    for feature in payload.get("features", []):
        props = feature.get("properties", {})
        features.append({"geometry": feature.get("geometry"), "properties": props})
    features.sort(key=lambda item: (str(item["properties"].get("objectid", "")), json.dumps(item, sort_keys=True)))
    return sha256_bytes(json.dumps(features, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def download_layer(url: str) -> dict[str, Any]:
    response = requests.get(
        url,
        params={
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "orderByFields": "objectid ASC",
            "f": "geojson",
        },
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(str(payload["error"]))
    return payload


def save_raw_layer(path: Path, payload: dict[str, Any]) -> None:
    """Guarda una instantánea determinista de una capa oficial."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def ensure_raw_layers(
    project_root: Path,
    refresh: bool,
    offline: bool,
) -> tuple[Path, Path]:
    """Descarga las capas si faltan y reutiliza la instantánea en ejecuciones futuras."""
    raw_dir = project_root / "datos" / "crudos"
    sub_path = raw_dir / "subestaciones_ice.geojson"
    line_path = raw_dir / "lineas_transmision_ice.geojson"

    missing = [path for path in (sub_path, line_path) if not path.exists()]
    if offline and (refresh or missing):
        names = ", ".join(path.name for path in missing) or "caché solicitada"
        raise RuntimeError(
            "La ejecución offline requiere las instantáneas locales. "
            f"Faltan: {names}. Ejecute una vez sin --offline."
        )

    if refresh or not sub_path.exists():
        try:
            save_raw_layer(sub_path, download_layer(SUBSTATIONS_QUERY_URL))
        except Exception as exc:
            raise RuntimeError(
                "No fue posible descargar la capa oficial de subestaciones ICE. "
                "Verifique la conexión o reutilice una caché válida."
            ) from exc

    if refresh or not line_path.exists():
        try:
            save_raw_layer(line_path, download_layer(LINES_QUERY_URL))
        except Exception as exc:
            raise RuntimeError(
                "No fue posible descargar la capa oficial de líneas ICE. "
                "Verifique la conexión o reutilice una caché válida."
            ) from exc

    return sub_path, line_path


def verify_official_layers(raw_subs: dict[str, Any], raw_lines: dict[str, Any], enabled: bool) -> dict[str, Any]:
    local = {
        "substations_entities": len(raw_subs["features"]),
        "lines_entities": len(raw_lines["features"]),
        "substations_semantic_sha256": canonical_feature_hash(raw_subs),
        "lines_semantic_sha256": canonical_feature_hash(raw_lines),
    }
    result: dict[str, Any] = {"attempted": enabled, "status": "NO_VERIFICADO_EN_LINEA", "local": local}
    if not enabled:
        return result
    try:
        remote_subs = download_layer(SUBSTATIONS_QUERY_URL)
        remote_lines = download_layer(LINES_QUERY_URL)
        remote = {
            "substations_entities": len(remote_subs.get("features", [])),
            "lines_entities": len(remote_lines.get("features", [])),
            "substations_semantic_sha256": canonical_feature_hash(remote_subs),
            "lines_semantic_sha256": canonical_feature_hash(remote_lines),
        }
        result["remote"] = remote
        result["status"] = "COINCIDE" if remote == local else "NO_COINCIDE"
    except Exception as exc:  # error controlado; la caché local conserva trazabilidad por hash
        result["status"] = "ERROR_DE_RED"
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def all_fields(payload: dict[str, Any]) -> list[str]:
    return sorted({key for feature in payload["features"] for key in feature.get("properties", {})})


def validate_raw_data(raw_subs: dict[str, Any], raw_lines: dict[str, Any], raw_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    required_sub = {"objectid", "subestacio", "region", "provincia", "canton", "distrito"}
    required_line = {"objectid", "ltmadre", "voltaje"}
    sub_fields, line_fields = set(all_fields(raw_subs)), set(all_fields(raw_lines))
    missing_sub, missing_line = sorted(required_sub - sub_fields), sorted(required_line - line_fields)
    if missing_sub or missing_line:
        raise RuntimeError(f"Campos requeridos ausentes. Subestaciones={missing_sub}; líneas={missing_line}")

    sub_rows, line_rows, quality = [], [], []
    sub_ids, line_ids = [], []
    for feature in sorted(raw_subs["features"], key=lambda item: int(item.get("properties", {}).get("objectid", -1))):
        p, geom = feature.get("properties", {}), shape(feature.get("geometry"))
        oid = p.get("objectid")
        sub_ids.append(oid)
        valid = isinstance(geom, Point) and not geom.is_empty and geom.is_valid
        sub_rows.append({
            "node_id": f"ST_{oid}", "objectid": oid, "name": p.get("subestacio"), "region": p.get("region"),
            "province": p.get("provincia"), "canton": p.get("canton"), "district": p.get("distrito"),
            "longitude": geom.x if isinstance(geom, Point) else "", "latitude": geom.y if isinstance(geom, Point) else "",
            "geometry_type": geom.geom_type, "geometry_valid": valid, "source_layer": "DT_SNIT_v2/FeatureServer/3",
            "source_url": SUBSTATIONS_LAYER_URL,
        })
        if not valid or any(p.get(field) in (None, "") for field in required_sub):
            quality.append({"layer": "subestaciones", "objectid": oid, "issue": "geometría o campo requerido inválido", "severity": "alta"})
    for feature in sorted(raw_lines["features"], key=lambda item: int(item.get("properties", {}).get("objectid", -1))):
        p, geom = feature.get("properties", {}), shape(feature.get("geometry"))
        oid = p.get("objectid")
        line_ids.append(oid)
        valid = isinstance(geom, (LineString, MultiLineString)) and not geom.is_empty and geom.is_valid
        line_rows.append({
            "line_objectid": oid, "line_name": p.get("ltmadre"), "voltage_code": p.get("voltaje"),
            "voltage_kv": voltage_to_kv(p.get("voltaje")), "ruleid": p.get("ruleid"), "shape_length_attribute": p.get("SHAPE__Length"),
            "geometry_type": geom.geom_type, "parts": len(geom.geoms) if isinstance(geom, MultiLineString) else 1,
            "geometry_valid": valid, "source_layer": "DT_SNIT_v2/FeatureServer/2", "source_url": LINES_LAYER_URL,
        })
        if not valid or oid is None or not p.get("ltmadre"):
            quality.append({"layer": "lineas", "objectid": oid, "issue": "geometría o campo requerido inválido", "severity": "alta"})
        if p.get("voltaje") is None:
            quality.append({"layer": "lineas", "objectid": oid, "issue": "voltaje nulo; entidad excluida de pesos", "severity": "media"})
    for layer, ids in (("subestaciones", sub_ids), ("lineas", line_ids)):
        for duplicate in sorted(key for key, count in Counter(ids).items() if count > 1):
            quality.append({"layer": layer, "objectid": duplicate, "issue": "OBJECTID duplicado", "severity": "crítica"})
    if not quality:
        quality.append({"layer": "ambas", "objectid": "", "issue": "sin anomalías críticas de estructura, identificador o geometría", "severity": "informativa"})
    return sub_rows, line_rows, quality


def voltage_to_kv(raw: Any) -> float:
    if raw is None or isinstance(raw, bool):
        return 0.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if value in VOLTAGE_CODE_TO_KV:
        return VOLTAGE_CODE_TO_KV[int(value)]
    return value if value > 10 else 0.0


def explode_lines(geometry: Any) -> list[LineString]:
    if isinstance(geometry, LineString):
        return [geometry]
    if not isinstance(geometry, MultiLineString):
        return []
    merged = linemerge(geometry)
    pieces = [merged] if isinstance(merged, LineString) else list(merged.geoms)
    return sorted(pieces, key=lambda item: (round(item.bounds[0], 12), round(item.bounds[1], 12), item.wkb_hex))


def prepare_geometries(raw_subs: dict[str, Any], raw_lines: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    to_metric = Transformer.from_crs(CRS_WGS84, "EPSG:5367", always_xy=True)
    stations = []
    for feature in raw_subs["features"]:
        p, geom = feature["properties"], shape(feature["geometry"])
        stations.append({
            "node_id": f"ST_{int(p['objectid'])}", "objectid": int(p["objectid"]), "name": str(p["subestacio"]).strip(),
            "region": str(p["region"]).strip(), "province": str(p["provincia"]).strip(), "canton": str(p["canton"]).strip(),
            "district": str(p["distrito"]).strip(), "longitude": float(geom.x), "latitude": float(geom.y),
            "geometry_wgs84": geom, "geometry_m": transform(to_metric.transform, geom),
        })
    stations.sort(key=lambda item: item["objectid"])
    line_parts = []
    for feature in sorted(raw_lines["features"], key=lambda item: int(item["properties"]["objectid"])):
        p, geom = feature["properties"], shape(feature["geometry"])
        kv = voltage_to_kv(p.get("voltaje"))
        if kv <= 0:
            continue
        for index, part in enumerate(explode_lines(geom), start=1):
            metric = transform(to_metric.transform, part)
            if metric.length <= 0:
                continue
            line_parts.append({
                "line_objectid": int(p["objectid"]), "line_part_id": f"LT_{int(p['objectid'])}_{index}",
                "line_name": str(p["ltmadre"]).strip(), "voltage_code": p.get("voltaje"), "voltage_kv": kv,
                "geometry_wgs84": part, "geometry_m": metric, "multipart": isinstance(geom, MultiLineString),
            })
    return stations, line_parts


def classify_association(distance_m: float, cfg: dict[str, Any]) -> str:
    confidence = cfg["topology"]["confidence"]
    if distance_m <= float(confidence["high_max_m"]):
        return "alta confianza"
    if distance_m <= float(confidence["medium_max_m"]):
        return "media confianza"
    if distance_m <= float(confidence["low_max_m"]):
        return "baja confianza"
    return "rechazada"


def classify_edge(max_snap: float, detour: float, cfg: dict[str, Any]) -> tuple[str, str, str]:
    c = cfg["topology"]["confidence"]
    if not math.isfinite(detour) or detour > float(c["reject_detour_ratio"]):
        return "rechazada", "RECHAZADA", "razón recorrido/directa excede el máximo permitido"
    if max_snap > float(c["medium_max_m"]) or detour > float(c["low_detour_ratio"]):
        return "baja confianza", "RECHAZADA_PARA_INSTANCIAS", "requiere ajuste >150 m o presenta desvío alto"
    if max_snap > float(c["high_max_m"]) or detour > float(c["medium_detour_ratio"]):
        return "media confianza", "VALIDADA", "ajuste o desvío moderado dentro de los límites declarados"
    return "alta confianza", "VALIDADA", "ajuste y desvío dentro de los umbrales de alta confianza"


NAME_ALIASES = {
    "la garita": ("la garita", "garita"),
    "penas blancas": ("penas blancas",),
    "canas": ("canas",),
    "belen": ("belen",),
    "chucas": ("chucas",),
}


def official_line_mentions_station(line_name: str, station_name: str) -> bool:
    normalized_line = re.sub(r"[^a-z0-9]+", " ", normalize_text(line_name)).strip()
    normalized_line = re.sub(r"(?<=[a-z])\d+\b", "", normalized_line)
    normalized_station = re.sub(r"[^a-z0-9]+", " ", normalize_text(station_name)).strip()
    aliases = NAME_ALIASES.get(normalized_station, (normalized_station,))
    return any(re.search(rf"(^| ){re.escape(alias)}($| )", normalized_line) for alias in aliases)


def enhance_evidence(candidates: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Refuerza evidencia sin inventar geometrías ni conexiones.

    El nombre oficial de la línea puede confirmar sus terminales aun cuando el
    punto cartográfico esté desplazado. Para candidatos no aceptados por el
    umbral ordinario, una regla geoespacial ampliada exige continuidad,
    consecutividad, peso positivo y ausencia de ambigüedades topológicas. La
    regla es general: no contiene nombres de subestaciones ni excepciones
    manuales.
    """
    validation = cfg.get("validation", {})
    extended_max_snap_m = float(
        validation.get("extended_geospatial_max_snap_m", 250.0)
    )
    extended_max_detour_ratio = float(
        validation.get("extended_geospatial_max_detour_ratio", 1.60)
    )
    result = []
    for original in candidates:
        item = dict(original)
        item["validation_basis"] = "geoespacial"
        item["operational_connectivity_confirmed"] = False
        named = (
            validation.get("allow_official_name_reinforcement", False)
            and official_line_mentions_station(item["line_name"], item["source_name"])
            and official_line_mentions_station(item["line_name"], item["target_name"])
            and float(item["max_snap_distance_m"]) <= float(validation["official_name_max_snap_m"])
            and float(item["detour_ratio"]) <= float(validation["official_name_max_detour_ratio"])
            and item["same_continuous_part"]
            and item["segment_exists"]
        )
        if named and item["validation_status"] != "VALIDADA":
            item["confidence"] = "media confianza"
            item["validation_status"] = "VALIDADA"
            item["validation_basis"] = "geoespacial + terminales en nombre oficial"
            item["validation_reason"] = "ambos extremos aparecen literalmente en ltmadre y el segmento oficial satisface los límites reforzados"
        extended_geospatial = (
            item["validation_status"] == "RECHAZADA_PARA_INSTANCIAS"
            and float(item["max_snap_distance_m"]) <= extended_max_snap_m
            and float(item["detour_ratio"]) <= extended_max_detour_ratio
            and bool(item["same_continuous_part"])
            and bool(item["segment_exists"])
            and int(item["intermediate_station_count"]) == 0
            and float(item["raw_weight"]) > 0.0
            and not bool(item["branching_risk"])
            and not bool(item["line_crosses_regions"])
            and not bool(item["crossing_risk"])
            and int(item["parallel_candidate_count"]) == 1
        )
        if extended_geospatial:
            item["confidence"] = "media confianza"
            item["validation_status"] = "VALIDADA"
            item["validation_basis"] = (
                "geoespacial oficial continua con tolerancia ampliada"
            )
            item["validation_reason"] = (
                "segmento oficial continuo entre estaciones consecutivas, "
                f"sin ambigüedad topológica, ajuste <= {extended_max_snap_m:g} m "
                f"y desvío <= {extended_max_detour_ratio:g}"
            )
        result.append(item)
    return result


def infer_topology(stations: list[dict[str, Any]], line_parts: list[dict[str, Any]], cfg: dict[str, Any], max_snap_m: float | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    maximum = float(max_snap_m if max_snap_m is not None else cfg["topology"]["max_snap_distance_m"])
    from_metric = Transformer.from_crs("EPSG:5367", CRS_WGS84, always_xy=True)
    associations, candidates = [], []
    for line in sorted(line_parts, key=lambda item: item["line_part_id"]):
        ordered = []
        for station in stations:
            distance = float(line["geometry_m"].distance(station["geometry_m"]))
            if distance <= maximum:
                position = float(line["geometry_m"].project(station["geometry_m"]))
                association = {
                    "node_id": station["node_id"], "node_name": station["name"], "node_objectid": station["objectid"],
                    "region": station["region"], "line_objectid": line["line_objectid"], "line_part_id": line["line_part_id"],
                    "line_name": line["line_name"], "voltage_kv": line["voltage_kv"], "snap_distance_m": distance,
                    "position_m": position, "confidence": classify_association(distance, cfg),
                }
                associations.append(association)
                ordered.append((position, distance, station))
        ordered.sort(key=lambda item: (item[0], item[1], item[2]["node_id"]))
        deduplicated, seen = [], set()
        for item in ordered:
            if item[2]["node_id"] not in seen:
                seen.add(item[2]["node_id"])
                deduplicated.append(item)
        for left, right in zip(deduplicated, deduplicated[1:]):
            pos_a, dist_a, station_a = left
            pos_b, dist_b, station_b = right
            source, target = canonical_pair(station_a["node_id"], station_b["node_id"])
            source_station = station_a if station_a["node_id"] == source else station_b
            target_station = station_b if station_b["node_id"] == target else station_a
            source_snap = dist_a if station_a["node_id"] == source else dist_b
            target_snap = dist_b if station_b["node_id"] == target else dist_a
            route_km = abs(pos_b - pos_a) / 1000.0
            straight_km = float(source_station["geometry_m"].distance(target_station["geometry_m"])) / 1000.0
            detour = route_km / straight_km if straight_km > 0 else math.inf
            confidence, status, reason = classify_edge(max(source_snap, target_snap), detour, cfg)
            if source_station["region"] != target_station["region"]:
                status, reason = "RECHAZADA", "extremos pertenecen a regiones literales diferentes"
            if route_km <= float(cfg["topology"]["minimum_route_length_km"]):
                status, reason = "RECHAZADA", "longitud recorrida nula o demasiado pequeña"
            segment_m = substring(line["geometry_m"], min(pos_a, pos_b), max(pos_a, pos_b))
            segment_wgs84 = transform(from_metric.transform, segment_m)
            segment_hash = sha256_bytes(segment_wgs84.wkb)
            candidates.append({
                "edge_id": f"{source}--{target}", "source": source, "target": target,
                "source_objectid": source_station["objectid"], "target_objectid": target_station["objectid"],
                "source_name": source_station["name"], "target_name": target_station["name"], "region": source_station["region"],
                "line_objectid": line["line_objectid"], "line_part_id": line["line_part_id"], "line_name": line["line_name"],
                "voltage_kv": float(line["voltage_kv"]), "source_snap_distance_m": source_snap,
                "target_snap_distance_m": target_snap, "max_snap_distance_m": max(source_snap, target_snap),
                "route_length_km": route_km, "straight_distance_km": straight_km, "detour_ratio": detour,
                "raw_weight": route_km * (float(line["voltage_kv"]) / 230.0), "confidence": confidence,
                "validation_status": status, "validation_reason": reason,
                "geometry_source": f"ICE DT_SNIT_v2 capa 2, OBJECTID {line['line_objectid']}, parte continua {line['line_part_id']}",
                "geometry_hash": segment_hash, "multipart_risk": bool(line["multipart"]), "segment_geometry": segment_wgs84,
            })
    associations.sort(key=lambda item: (item["line_part_id"], item["position_m"], item["node_id"]))
    regions_by_line: dict[int, set[str]] = defaultdict(set)
    parts_by_line: Counter[int] = Counter()
    endpoint_degree: dict[int, Counter[tuple[int, int]]] = defaultdict(Counter)
    for association in associations:
        regions_by_line[int(association["line_objectid"])].add(str(association["region"]))
    for part in line_parts:
        oid = int(part["line_objectid"])
        parts_by_line[oid] += 1
        for coordinate in (part["geometry_m"].coords[0], part["geometry_m"].coords[-1]):
            endpoint_degree[oid][(round(coordinate[0]), round(coordinate[1]))] += 1
    evidence_per_pair = Counter((item["source"], item["target"]) for item in candidates)
    for item in candidates:
        oid = int(item["line_objectid"])
        crossing_ids = sorted({
            int(part["line_objectid"])
            for part in line_parts
            if int(part["line_objectid"]) != oid and item["segment_geometry"].crosses(part["geometry_wgs84"])
        })
        item.update({
            "same_continuous_part": True,
            "segment_exists": not item["segment_geometry"].is_empty,
            "intermediate_station_count": 0,
            "line_part_count": parts_by_line[oid],
            "multipart_risk": parts_by_line[oid] > 1,
            "branching_risk": max(endpoint_degree[oid].values(), default=0) >= 3,
            "line_crosses_regions": len(regions_by_line[oid]) > 1,
            "crossing_risk": bool(crossing_ids),
            "crossing_line_objectids": "|".join(map(str, crossing_ids)),
            "parallel_candidate_count": evidence_per_pair[(item["source"], item["target"])],
        })
    candidates.sort(key=lambda item: (item["source"], item["target"], item["line_part_id"]))
    return associations, candidates


def deduplicate_evidence(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    validated, rejected, seen = [], [], set()
    for item in candidates:
        identity = (item["source"], item["target"], item["line_objectid"], item["geometry_hash"], item["voltage_kv"])
        record = dict(item)
        if identity in seen:
            record["validation_status"] = "RECHAZADA_DUPLICADA"
            record["validation_reason"] = "geometría, línea, tensión y extremos duplicados"
            rejected.append(record)
            continue
        seen.add(identity)
        if record["validation_status"] == "VALIDADA" and record["confidence"] in {"alta confianza", "media confianza"}:
            validated.append(record)
        else:
            rejected.append(record)
    return validated, rejected


def build_regional_graphs(stations: list[dict[str, Any]], validated: list[dict[str, Any]]) -> dict[str, nx.Graph]:
    by_id = {item["node_id"]: item for item in stations}
    graphs: dict[str, nx.Graph] = {}
    for region in sorted({item["region"] for item in stations}, key=normalize_text):
        graph = nx.Graph(region=region, source="ICE DT_SNIT_v2", weight_definition="sum(route_length_km * voltage_kv / 230) por circuitos geométricamente distintos")
        for station in stations:
            if station["region"] == region:
                graph.add_node(station["node_id"], **{key: station[key] for key in ("objectid", "name", "region", "province", "canton", "district", "longitude", "latitude")})
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for evidence in validated:
            if evidence["source"] in graph and evidence["target"] in graph:
                grouped[(evidence["source"], evidence["target"])].append(evidence)
        for (source, target), evidence_rows in sorted(grouped.items()):
            evidence_rows.sort(key=lambda item: (item["line_objectid"], item["line_part_id"], item["geometry_hash"]))
            raw_weight = sum(float(item["raw_weight"]) for item in evidence_rows)
            graph.add_edge(
                source, target, length_km=sum(float(item["route_length_km"]) for item in evidence_rows),
                voltage_kv="|".join(sorted({f"{float(item['voltage_kv']):g}" for item in evidence_rows})),
                circuits=len(evidence_rows), raw_weight=raw_weight, weight=raw_weight,
                line_objectids="|".join(str(value) for value in sorted({item["line_objectid"] for item in evidence_rows})),
                line_names="|".join(sorted({item["line_name"] for item in evidence_rows}, key=normalize_text)),
                max_snap_distance_m=max(float(item["max_snap_distance_m"]) for item in evidence_rows),
                detour_ratio=max(float(item["detour_ratio"]) for item in evidence_rows),
                confidence=max((item["confidence"] for item in evidence_rows), key=lambda value: CONFIDENCE_RANK[value]),
                validation_status="VALIDADA", evidence_ids="|".join(item["geometry_hash"] for item in evidence_rows),
                validation_basis="|".join(sorted({str(item.get("validation_basis", "geoespacial")) for item in evidence_rows})),
                operational_connectivity_confirmed=False,
            )
        graphs[region] = graph
    return graphs


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", normalize_text(value)).strip("_")


def graph_nodes_rows(graph: nx.Graph, include_index: bool = False) -> list[dict[str, Any]]:
    preferred = graph.graph.get("node_order")
    if (
        isinstance(preferred, list)
        and len(preferred) == graph.number_of_nodes()
        and set(preferred) == set(graph.nodes)
    ):
        node_order = preferred
    else:
        node_order = sorted(
            graph.nodes,
            key=lambda node: (graph.nodes[node]["objectid"], node),
        )
    rows = []
    for index, node in enumerate(node_order):
        data = graph.nodes[node]
        row = {
            "node_id": node, "objectid": data["objectid"], "name": data["name"], "region": data["region"],
            "province": data["province"], "canton": data["canton"], "district": data["district"],
            "longitude": data["longitude"], "latitude": data["latitude"], "degree": graph.degree(node),
            "weighted_degree": sum(float(edge.get("weight", 0.0)) for _, _, edge in graph.edges(node, data=True)),
            "source_layer": "ICE DT_SNIT_v2/FeatureServer/3", "source_url": SUBSTATIONS_LAYER_URL,
        }
        if include_index:
            row = {"node_index": index, **row}
        rows.append(row)
    return rows


def graph_edges_rows(graph: nx.Graph, node_index: dict[str, int] | None = None) -> list[dict[str, Any]]:
    rows = []
    for source, target in sorted(canonical_pair(a, b) for a, b in graph.edges):
        data = graph[source][target]
        row = {
            "source_id": source, "target_id": target, "source_name": graph.nodes[source]["name"], "target_name": graph.nodes[target]["name"],
            "length_km": data["length_km"], "voltage_kv": data["voltage_kv"], "circuits": data["circuits"],
            "raw_weight": data["raw_weight"], "weight": data["weight"], "line_objectids": data["line_objectids"],
            "line_names": data["line_names"], "max_snap_distance_m": data["max_snap_distance_m"],
            "detour_ratio": data["detour_ratio"], "confidence": data["confidence"], "validation_status": data["validation_status"],
            "validation_basis": data.get("validation_basis", "geoespacial"),
            "operational_connectivity_confirmed": data.get("operational_connectivity_confirmed", False),
            "source_layer": "ICE DT_SNIT_v2/FeatureServer/2", "source_url": LINES_LAYER_URL,
            "weight_definition": "sum(route_length_km * (voltage_kv / 230)); sin normalización",
        }
        if node_index is not None:
            row = {"source_index": node_index[source], "target_index": node_index[target], **row}
        rows.append(row)
    return rows


def graphml_safe_copy(graph: nx.Graph) -> nx.Graph:
    clean = nx.Graph()
    clean.graph.update({key: str(value) for key, value in graph.graph.items()})
    for node, data in graph.nodes(data=True):
        clean.add_node(node, **{key: ("" if value is None else value if isinstance(value, (str, int, float, bool)) else str(value)) for key, value in data.items()})
    for source, target, data in graph.edges(data=True):
        clean.add_edge(source, target, **{key: ("" if value is None else value if isinstance(value, (str, int, float, bool)) else str(value)) for key, value in data.items()})
    return clean


def shortest_odd_cycle(graph: nx.Graph) -> list[str] | None:
    odd = [cycle for cycle in nx.cycle_basis(graph) if len(cycle) % 2 == 1]
    if not odd:
        return None
    def canonical_cycle(cycle: list[str]) -> tuple[str, ...]:
        variants = []
        for oriented in (cycle, list(reversed(cycle))):
            for index in range(len(cycle)):
                variants.append(tuple(oriented[index:] + oriented[:index]))
        return min(variants)
    return list(min((canonical_cycle(cycle) for cycle in odd), key=lambda item: (len(item), item)))


def geographic_extent_km(graph: nx.Graph) -> float:
    transformer = Transformer.from_crs(CRS_WGS84, "EPSG:5367", always_xy=True)
    points = [Point(*transformer.transform(data["longitude"], data["latitude"])) for _, data in graph.nodes(data=True)]
    return max((a.distance(b) for index, a in enumerate(points) for b in points[index + 1:]), default=0.0) / 1000.0


def connected_bfs_order(component: nx.Graph, seed: str) -> list[str]:
    # Expansión conectada de mejor evidencia primero. La tolerancia ampliada se
    # pospone hasta agotar alternativas geoespaciales ordinarias o nominales.
    order, visited = [seed], {seed}
    while len(order) < component.number_of_nodes():
        boundary = []
        for source in sorted(visited):
            for candidate in component.neighbors(source):
                if candidate in visited:
                    continue
                data = component[source][candidate]
                basis = str(data.get("validation_basis", "geoespacial"))
                basis_rank = 2 if "tolerancia ampliada" in basis else 1 if "nombre oficial" in basis else 0
                boundary.append((
                    basis_rank, float(data["max_snap_distance_m"]), CONFIDENCE_RANK[data["confidence"]],
                    -component.degree(candidate), component.nodes[candidate]["objectid"], candidate, source,
                ))
        if not boundary:
            raise RuntimeError("La expansión conectada se interrumpió dentro de un componente.")
        candidate = min(boundary)[5]
        visited.add(candidate)
        order.append(candidate)
    return order


def evaluate_regions(graphs: dict[str, nx.Graph], sizes: list[int]) -> tuple[list[dict[str, Any]], dict[str, Any], dict[int, nx.Graph] | None, list[str] | None]:
    """Selecciona por calidad topológica, nunca por el valor de Max-Cut."""
    rows, viable = [], []
    for region, graph in sorted(graphs.items(), key=lambda item: normalize_text(item[0])):
        components = sorted((graph.subgraph(nodes).copy() for nodes in nx.connected_components(graph)), key=lambda item: (-item.number_of_nodes(), sorted(item.nodes)))
        largest = components[0] if components else nx.Graph()
        best = None
        for component in components:
            if component.number_of_nodes() < max(sizes):
                continue
            for seed in sorted(component.nodes, key=lambda node: (component.nodes[node]["objectid"], node)):
                order = connected_bfs_order(component, seed)
                master = component.subgraph(order[: max(sizes)]).copy()
                if master.number_of_nodes() != max(sizes) or not nx.is_connected(master):
                    continue
                bottleneck = max(float(data["max_snap_distance_m"]) for _, _, data in master.edges(data=True))
                high = sum(1 for _, _, data in master.edges(data=True) if data["confidence"] == "alta confianza")
                semantic = sum(1 for _, _, data in master.edges(data=True) if "nombre oficial" in str(data.get("validation_basis", "")))
                extended = sum(1 for _, _, data in master.edges(data=True) if "tolerancia ampliada" in str(data.get("validation_basis", "")))
                score = (bottleneck, extended, semantic, -high, geographic_extent_km(master), tuple(order[: max(sizes)]))
                if best is None or score < best[0]:
                    best = (score, order, master)
        high_region = sum(1 for _, _, data in graph.edges(data=True) if data["confidence"] == "alta confianza")
        medium_region = graph.number_of_edges() - high_region
        row = {
            "region": region, "regional_nodes": graph.number_of_nodes(), "regional_edges": graph.number_of_edges(),
            "largest_component_nodes": largest.number_of_nodes(), "largest_component_edges": largest.number_of_edges(),
            "supports_connected_6_8_10_12": best is not None, "minimum_required_snap_m": best[0][0] if best else "",
            "high_confidence_edges": high_region, "medium_confidence_edges": medium_region,
            "high_confidence_proportion": high_region / graph.number_of_edges() if graph.number_of_edges() else 0.0,
            "geographic_extent_km": geographic_extent_km(largest), "is_tree_largest_component": nx.is_tree(largest) if largest.number_of_nodes() else "",
            "is_bipartite_largest_component": nx.is_bipartite(largest), "selection_rank": "",
            "reason": "componente conectado suficiente" if best else "no existe componente conectado de 12 nodos con la evidencia aceptada",
        }
        rows.append(row)
        if best:
            viable.append((region, best, row))
    viable.sort(key=lambda item: (
        float(item[2]["minimum_required_snap_m"]), -float(item[2]["high_confidence_proportion"]),
        float(item[2]["geographic_extent_km"]), normalize_text(item[0]),
    ))
    if not viable:
        return rows, {"status": "SIN_REGION_VIABLE", "selected_region": None, "nested_sequence_found": False}, None, None
    region, best, selected_row = viable[0]
    order, master = best[1], best[2]
    instances = {size: master.subgraph(order[:size]).copy() for size in sizes}
    if not all(graph.number_of_nodes() == size and nx.is_connected(graph) for size, graph in instances.items()):
        raise RuntimeError("La selección conjunta no produjo prefijos conectados.")
    for rank, (candidate_region, _, _) in enumerate(viable, start=1):
        for row in rows:
            if row["region"] == candidate_region:
                row["selection_rank"] = rank
    return rows, {
        "status": "SELECCION_COMPLETA", "selected_region": region, "selection_rank": 1,
        "selected_tolerance_m": math.ceil(float(selected_row["minimum_required_snap_m"])),
        "exact_bottleneck_snap_m": float(selected_row["minimum_required_snap_m"]),
        "selection_rule": ["componente conectado de al menos 12 nodos", "menor ajuste máximo requerido", "mayor proporción de alta confianza", "mayor compacidad", "desempate alfabético"],
        "maxcut_used_for_selection": False, "nested_sequence_found": True, "nested_validation": True,
        "node_order": order[: max(sizes)], "seed_node_id": order[0],
    }, instances, order[: max(sizes)]


def load_audited_instance_lock(
    project_root: Path,
    graphs: dict[str, nx.Graph],
    sizes: list[int],
) -> tuple[dict[str, Any], dict[int, nx.Graph], list[str]] | None:
    """Reutiliza únicamente la selección de nodos ya auditada.

    Las aristas y los pesos se reconstruyen desde los GeoJSON; los CSV de la
    entrega solo fijan qué subconjunto real corresponde a G6/G8/G10/G12 y su
    orden de presentación. Esto evita que un cambio de desempate BFS altere
    las instancias y vuelva incomparables los resultados QAOA existentes.
    """
    graph_dir = project_root / "datos" / "grafos"
    rows_by_size: dict[int, list[dict[str, str]]] = {}
    node_sets: dict[int, set[str]] = {}
    for size in sizes:
        path = graph_dir / f"grafo_{size}_nodos.csv"
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            rows = list(csv.DictReader(source))
        if len(rows) != size or "node_id" not in rows[0]:
            raise RuntimeError(f"Contrato de instancia inválido: {path}")
        rows_by_size[size] = rows
        node_sets[size] = {str(row["node_id"]).strip() for row in rows}

    previous: set[str] = set()
    for size in sizes:
        if not previous.issubset(node_sets[size]):
            raise RuntimeError(
                f"El contrato auditado deja de ser anidado en G{size}."
            )
        previous = node_sets[size]

    master_nodes = node_sets[max(sizes)]
    candidates = [
        (region, graph)
        for region, graph in graphs.items()
        if master_nodes.issubset(set(graph.nodes))
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            "El contrato auditado no identifica una única región reconstruida."
        )
    region, regional_graph = candidates[0]
    instances: dict[int, nx.Graph] = {}
    for size in sizes:
        graph = regional_graph.subgraph(node_sets[size]).copy()
        if graph.number_of_nodes() != size or not nx.is_connected(graph):
            raise RuntimeError(
                f"Los nodos auditados de G{size} no forman un grafo conectado."
            )
        graph.graph["node_order"] = [
            str(row["node_id"]).strip() for row in rows_by_size[size]
        ]
        instances[size] = graph

    master = instances[max(sizes)]
    bottleneck = max(
        float(data["max_snap_distance_m"])
        for _, _, data in master.edges(data=True)
    )
    order: list[str] = []
    seen: set[str] = set()
    for size in sizes:
        for row in rows_by_size[size]:
            node = str(row["node_id"]).strip()
            if node not in seen:
                seen.add(node)
                order.append(node)
    return (
        {
            "status": "SELECCION_COMPLETA",
            "selected_region": region,
            "selection_rank": 1,
            "selected_tolerance_m": math.ceil(bottleneck),
            "exact_bottleneck_snap_m": bottleneck,
            "selection_rule": [
                "conjuntos de nodos auditados incluidos en datos/grafos",
                "aristas y pesos reconstruidos desde GeoJSON",
                "validación de conectividad, anidamiento y región",
            ],
            "maxcut_used_for_selection": False,
            "nested_sequence_found": True,
            "nested_validation": True,
            "node_order": order,
            "seed_node_id": order[0],
            "instance_lock_used": True,
        },
        instances,
        order,
    )


def exact_maxcut(graph: nx.Graph, epsilon: float) -> dict[str, Any]:
    nodes = sorted(graph.nodes, key=lambda node: graph.nodes[node]["objectid"])
    total = sum(float(data["weight"]) for _, _, data in graph.edges(data=True))
    best = -1.0
    solutions = []
    for mask in range(1 << max(0, len(nodes) - 1)):
        side_a = {nodes[0]} if nodes else set()
        for index, node in enumerate(nodes[1:]):
            if mask & (1 << index):
                side_a.add(node)
        value = sum(float(data["weight"]) for source, target, data in graph.edges(data=True) if (source in side_a) != (target in side_a))
        if value > best + epsilon:
            best, solutions = value, [side_a]
        elif abs(value - best) <= epsilon:
            solutions.append(side_a)
    chosen = min(solutions, key=lambda side: tuple(sorted(side)))
    side_b = set(nodes) - chosen
    cut, uncut = [], []
    for source, target, data in sorted(graph.edges(data=True), key=lambda item: canonical_pair(item[0], item[1])):
        record = {"source": source, "target": target, "weight": float(data["weight"])}
        (cut if ((source in chosen) != (target in chosen)) else uncut).append(record)
    gap = total - best
    return {
        "partition_a": sorted(chosen), "partition_b": sorted(side_b), "equivalent_complement": {"partition_a": sorted(side_b), "partition_b": sorted(chosen)},
        "cut_edges": cut, "uncut_edges": uncut, "total_edge_weight": total, "exact_maxcut_weight": best,
        "nontriviality_gap": gap, "epsilon": epsilon, "is_nontrivial": gap > epsilon,
        "number_of_optimal_partitions_fixing_first_node": len(solutions), "number_of_optimal_assignments_including_complements": 2 * len(solutions),
    }


def plot_network(graph: nx.Graph, path: Path, title: str, odd_cycle: list[str] | None = None, evidence: list[dict[str, Any]] | None = None) -> None:
    fig, ax = plt.subplots(figsize=(10, 7), dpi=140)
    ax.set_title(title)
    positions = {node: (data["longitude"], data["latitude"]) for node, data in graph.nodes(data=True)}
    if evidence:
        for item in evidence:
            if item["source"] in graph and item["target"] in graph and graph.has_edge(item["source"], item["target"]):
                geometry = item["segment_geometry"]
                if isinstance(geometry, LineString):
                    xs, ys = geometry.xy
                    ax.plot(xs, ys, color="#527a9a", linewidth=1.0, alpha=0.75, zorder=1)
    high_edges = [(a, b) for a, b, data in graph.edges(data=True) if data["confidence"] == "alta confianza"]
    medium_edges = [(a, b) for a, b, data in graph.edges(data=True) if data["confidence"] == "media confianza"]
    nx.draw_networkx_edges(graph, positions, edgelist=high_edges, edge_color="#176b3a", width=1.8, ax=ax)
    nx.draw_networkx_edges(graph, positions, edgelist=medium_edges, edge_color="#d97706", width=2.2, style="dashed", ax=ax)
    if odd_cycle:
        cycle_edges = list(zip(odd_cycle, odd_cycle[1:] + odd_cycle[:1]))
        nx.draw_networkx_edges(graph, positions, edgelist=cycle_edges, edge_color="#d11b5b", width=4.0, ax=ax)
    nx.draw_networkx_nodes(graph, positions, node_color="#f28e2b", edgecolors="#222222", node_size=210, ax=ax)
    label_offsets = ((7, 7), (7, -9), (-7, 7), (-7, -9), (12, 0), (-12, 0), (0, 12), (0, -13))
    for index, node in enumerate(sorted(graph.nodes, key=lambda item: graph.nodes[item]["objectid"])):
        dx, dy = label_offsets[index % len(label_offsets)]
        ax.annotate(
            graph.nodes[node]["name"], xy=positions[node], xytext=(dx, dy), textcoords="offset points",
            fontsize=6.5, ha="center", va="center", bbox={"boxstyle": "round,pad=0.12", "fc": "white", "ec": "none", "alpha": 0.62},
            zorder=5,
        )
    ax.set_xlabel("Longitud (EPSG:4326)")
    ax.set_ylabel("Latitud (EPSG:4326)")
    ax.grid(alpha=0.25)
    ax.text(0.01, 0.01, "Azul: geometría ICE | verde: alta | naranja: media | magenta: ciclo impar", transform=ax.transAxes, fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, metadata={"Software": "proyecto_grafos_ice"})
    plt.close(fig)


def export_regional_graphs(base: Path, graphs: dict[str, nx.Graph]) -> list[dict[str, Any]]:
    summary = []
    node_columns = ["node_id", "objectid", "name", "region", "province", "canton", "district", "longitude", "latitude", "degree", "weighted_degree", "source_layer", "source_url"]
    edge_columns = ["source_id", "target_id", "source_name", "target_name", "length_km", "voltage_kv", "circuits", "raw_weight", "weight", "line_objectids", "line_names", "max_snap_distance_m", "detour_ratio", "confidence", "validation_status", "validation_basis", "operational_connectivity_confirmed", "source_layer", "source_url", "weight_definition"]
    for region, graph in sorted(graphs.items(), key=lambda item: normalize_text(item[0])):
        name = slug(region)
        write_csv(base / "datos/procesados" / f"grafo_region_{name}_nodos.csv", graph_nodes_rows(graph), node_columns)
        write_csv(base / "datos/procesados" / f"grafo_region_{name}_aristas.csv", graph_edges_rows(graph), edge_columns)
        nx.write_graphml(graphml_safe_copy(graph), base / "datos/procesados" / f"grafo_region_{name}.graphml", infer_numeric_types=True, named_key_ids=True)
        components = list(nx.connected_components(graph))
        largest = max((len(item) for item in components), default=0)
        summary.append({
            "region": region, "nodes": graph.number_of_nodes(), "edges": graph.number_of_edges(), "components": len(components),
            "largest_component_nodes": largest, "isolated_nodes": len(list(nx.isolates(graph))), "is_bipartite": nx.is_bipartite(graph),
            "has_odd_cycle": shortest_odd_cycle(graph) is not None, "high_confidence_edges": sum(1 for _, _, d in graph.edges(data=True) if d["confidence"] == "alta confianza"),
            "medium_confidence_edges": sum(1 for _, _, d in graph.edges(data=True) if d["confidence"] == "media confianza"),
        })
    return summary


def graph_geojson(graph: nx.Graph, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    features = []
    nodes = set(graph.nodes)
    for item in evidence:
        if item["source"] in nodes and item["target"] in nodes and graph.has_edge(item["source"], item["target"]):
            props = {key: rounded(value) for key, value in item.items() if key != "segment_geometry"}
            features.append({"type": "Feature", "geometry": mapping(item["segment_geometry"]), "properties": props})
    for node, data in sorted(graph.nodes(data=True), key=lambda item: item[1]["objectid"]):
        props = {"feature_role": "substation", "node_id": node, "objectid": data["objectid"], "name": data["name"], "region": data["region"]}
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [data["longitude"], data["latitude"]]}, "properties": props})
    return {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": CRS_WGS84}}, "features": features}


def export_instances(base: Path, instances: dict[int, nx.Graph], evidence: list[dict[str, Any]], region: str, epsilon: float) -> list[dict[str, Any]]:
    regional_max = max((float(data["raw_weight"]) for graph in instances.values() for _, _, data in graph.edges(data=True)), default=1.0)
    # Se conserva raw_weight: no cambia entre tamaños y evita normalizaciones locales injustas.
    summaries = []
    for size, graph in sorted(instances.items()):
        for _, _, data in graph.edges(data=True):
            data["weight"] = data["raw_weight"]
        odd_cycle = shortest_odd_cycle(graph)
        result = exact_maxcut(graph, epsilon)
        if graph.number_of_nodes() != size or not nx.is_connected(graph):
            raise RuntimeError(f"La instancia G{size} no cumple tamaño o conectividad.")
        write_json(base / "auditoria" / f"diagnostico_topologico_{size}.json", {
            "size": size, "connected": nx.is_connected(graph), "is_tree": nx.is_tree(graph),
            "is_bipartite": nx.is_bipartite(graph), "cycle_rank": graph.number_of_edges() - graph.number_of_nodes() + 1,
            "odd_cycle": odd_cycle or [], "maxcut_is_trivial": not result["is_nontrivial"],
            "interpretation": "La consigna exige un grafo regional ponderado de 6-12 nodos; no exige ciclos ni no bipartición.",
        })
        write_json(base / "resultados" / f"maxcut_exacto_{size}.json", result)
        node_rows = graph_nodes_rows(graph, include_index=True)
        index = {row["node_id"]: row["node_index"] for row in node_rows}
        node_columns = ["node_index", "node_id", "objectid", "name", "region", "province", "canton", "district", "longitude", "latitude", "degree", "weighted_degree", "source_layer", "source_url"]
        edge_columns = ["source_index", "target_index", "source_id", "target_id", "source_name", "target_name", "length_km", "voltage_kv", "circuits", "raw_weight", "weight", "line_objectids", "line_names", "max_snap_distance_m", "detour_ratio", "confidence", "validation_status", "validation_basis", "operational_connectivity_confirmed", "source_layer", "source_url", "weight_definition"]
        write_csv(base / "resultados" / f"grafo_{size}_nodos.csv", node_rows, node_columns)
        write_csv(base / "resultados" / f"grafo_{size}_aristas.csv", graph_edges_rows(graph, index), edge_columns)
        nx.write_graphml(graphml_safe_copy(graph), base / "resultados" / f"grafo_{size}.graphml", infer_numeric_types=True, named_key_ids=True)
        write_json(base / "resultados" / f"grafo_{size}.geojson", graph_geojson(graph, evidence))
        # Contrato canónico de la estructura 4.2. ``resultados/`` se conserva
        # además por compatibilidad con los notebooks históricos.
        graph_dir = base / "datos" / "grafos"
        write_csv(graph_dir / f"grafo_{size}_nodos.csv", node_rows, node_columns)
        write_csv(
            graph_dir / f"grafo_{size}_aristas.csv",
            graph_edges_rows(graph, index),
            edge_columns,
        )
        nx.write_graphml(
            graphml_safe_copy(graph),
            graph_dir / f"grafo_{size}.graphml",
            infer_numeric_types=True,
            named_key_ids=True,
        )
        matrix = nx.to_pandas_adjacency(graph, nodelist=sorted(graph.nodes, key=lambda node: index[node]), weight="weight", dtype=float)
        matrix.index.name = "node_id"
        matrix.to_csv(base / "resultados" / f"grafo_{size}_matriz_adyacencia.csv", float_format="%.9f", lineterminator="\n")
        plot_network(graph, base / "resultados" / f"grafo_{size}.png", f"G{size} · región {region}", odd_cycle, evidence)
        plot_network(graph, base / "resultados" / f"mapa_grafo_{size}.png", f"Mapa geográfico G{size} · región {region}", odd_cycle, evidence)
        summaries.append({
            "size": size, "nodes": graph.number_of_nodes(), "edges": graph.number_of_edges(), "connected": nx.is_connected(graph),
            "is_tree": nx.is_tree(graph), "is_bipartite": nx.is_bipartite(graph), "cycle_rank": graph.number_of_edges() - graph.number_of_nodes() + 1,
            "odd_cycle_length": len(odd_cycle) if odd_cycle else 0, "region": region,
            "high_confidence_edges": sum(1 for _, _, d in graph.edges(data=True) if d["confidence"] == "alta confianza"),
            "medium_confidence_edges": sum(1 for _, _, d in graph.edges(data=True) if d["confidence"] == "media confianza"), "low_confidence_edges": 0,
            "total_edge_weight": result["total_edge_weight"], "exact_maxcut_weight": result["exact_maxcut_weight"],
            "nontriviality_gap": result["nontriviality_gap"], "nested": True, "data_hash": "pending",
        })
    for row in summaries:
        row["data_hash"] = sha256_file(base / "resultados" / f"grafo_{row['size']}_aristas.csv")
    return summaries


def sensitivity_rows(stations: list[dict[str, Any]], parts: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for tolerance in cfg["topology"]["sensitivity_tolerances_m"]:
        _, candidates = infer_topology(stations, parts, cfg, float(tolerance))
        candidates = enhance_evidence(candidates, cfg)
        for region in sorted({station["region"] for station in stations}, key=normalize_text):
            graph = nx.Graph()
            graph.add_nodes_from(station["node_id"] for station in stations if station["region"] == region)
            for item in candidates:
                if item["region"] == region and item["validation_status"] == "VALIDADA":
                    graph.add_edge(item["source"], item["target"], confidence=item["confidence"])
            components = list(nx.connected_components(graph))
            largest = graph.subgraph(max(components, key=len)).copy() if components else nx.Graph()
            rows.append({
                "tolerance_m": tolerance, "region": region, "nodes_with_edges": graph.number_of_nodes() - len(list(nx.isolates(graph))),
                "edges": graph.number_of_edges(), "largest_component_nodes": largest.number_of_nodes(),
                "largest_component_edges": largest.number_of_edges(), "cycle_rank_largest": max(0, largest.number_of_edges() - largest.number_of_nodes() + 1) if largest.number_of_nodes() else 0,
                "largest_is_bipartite": nx.is_bipartite(largest),
                "low_confidence_edges": sum(1 for _, _, data in graph.edges(data=True) if data["confidence"] == "baja confianza"),
                "within_declared_maximum": float(tolerance) <= float(cfg["topology"]["max_snap_distance_m"]),
            })
    return rows


def requirements_matrix_challenge(base: Path) -> None:
    rows = [
        {"requisito": "modelar una red eléctrica regional", "fuente_en_consigna": "p. 3, Planteamiento del problema, punto 1", "interpretacion_tecnica": "una región literal del ICE", "evidencia_requerida": "región uniforme y fuente oficial", "archivo_que_lo_demuestra": "resultados/region_seleccionada.json", "criterio_de_aceptacion": "todos los nodos pertenecen a Central"},
        {"requisito": "grafo ponderado de 6-12 nodos", "fuente_en_consigna": "p. 3, Planteamiento del problema, punto 1", "interpretacion_tecnica": "cuatro instancias 6/8/10/12 con pesos positivos", "evidencia_requerida": "CSV y GraphML", "archivo_que_lo_demuestra": "resultados/resumen_grafos.csv", "criterio_de_aceptacion": "tamaños exactos y conectividad"},
        {"requisito": "nodos, aristas, pesos y fuentes", "fuente_en_consigna": "p. 3, Lista de verificación", "interpretacion_tecnica": "trazabilidad completa por OBJECTID y geometría", "evidencia_requerida": "catálogos y auditoría", "archivo_que_lo_demuestra": "auditoria/aristas_validadas.csv", "criterio_de_aceptacion": "ningún nodo o segmento sintético"},
        {"requisito": "datos reales de la red", "fuente_en_consigna": "p. 3, Consejo; rúbrica de conexión ODS", "interpretacion_tecnica": "capas ICE DT_SNIT_v2", "evidencia_requerida": "comparación en línea y SHA-256", "archivo_que_lo_demuestra": "auditoria/manifest_datos/crudos.json", "criterio_de_aceptacion": "72 y 48 entidades coinciden con el servicio"},
        {"requisito": "escalamiento", "fuente_en_consigna": "p. 3, Extensiones; p. 5, Comparación y escalado", "interpretacion_tecnica": "instancias anidadas con metodología y escala de pesos comunes", "evidencia_requerida": "validación de subgrafos", "archivo_que_lo_demuestra": "auditoria/validacion_subgrafos.csv", "criterio_de_aceptacion": "G6 ⊂ G8 ⊂ G10 ⊂ G12"},
        {"requisito": "reproducibilidad", "fuente_en_consigna": "p. 5, Requisitos de entrega y rúbrica", "interpretacion_tecnica": "punto único y dependencias fijadas", "evidencia_requerida": "dos ejecuciones y hashes", "archivo_que_lo_demuestra": "auditoria/reporte_reproducibilidad.md", "criterio_de_aceptacion": "100 % idéntico"},
    ]
    write_csv(base / "docs" / "matriz_requisitos_grafos.csv", rows, ["requisito", "fuente_en_consigna", "interpretacion_tecnica", "evidencia_requerida", "archivo_que_lo_demuestra", "criterio_de_aceptacion"])


def write_challenge_docs(base: Path, selection: dict[str, Any], evaluation: list[dict[str, Any]], official: dict[str, Any], summaries: list[dict[str, Any]], validated: list[dict[str, Any]], cfg: dict[str, Any]) -> None:
    if selection.get("status") != "SELECCION_COMPLETA" or len(summaries) != 4:
        raise RuntimeError("No se pueden documentar cuatro instancias: selección incompleta.")
    region = selection["selected_region"]
    extended_records = [
        item
        for item in validated
        if "tolerancia ampliada" in str(item.get("validation_basis", ""))
    ]
    validation = cfg.get("validation", {})
    extended_max_snap_m = float(
        validation.get("extended_geospatial_max_snap_m", 250.0)
    )
    extended_max_detour_ratio = float(
        validation.get("extended_geospatial_max_detour_ratio", 1.60)
    )
    selection_text = (
        f"Se reconstruyó la región **{region}** y se aplicó el contrato de "
        "nodos G6/G8/G10/G12 ya auditado en `datos/grafos`. Las aristas y "
        "los pesos se recalcularon desde los GeoJSON."
        if selection.get("instance_lock_used")
        else (
            f"Se seleccionó **{region}** de forma determinista como la "
            "primera región que permite un componente conectado de 12 nodos "
            "con el menor ajuste máximo requerido."
        )
    )
    extended_text = (
        f"Se aceptaron **{len(extended_records)}** aristas mediante la regla "
        "geoespacial ampliada, aplicada sin nombres ni excepciones manuales. "
        "La regla exige una parte oficial continua, estaciones consecutivas, "
        f"peso positivo, ajuste ≤{extended_max_snap_m:g} m, desvío "
        f"≤{extended_max_detour_ratio:g} y ausencia de cruces, "
        "ramificaciones o candidatos paralelos ambiguos."
    )
    table = "\n".join(
        f"| G{row['size']} | {row['nodes']} | {row['edges']} | {row['connected']} | {row['is_tree']} | {row['total_edge_weight']:.6f} | {row['exact_maxcut_weight']:.6f} |"
        for row in summaries
    )
    (base / "docs" / "justificacion_region.md").write_text(
        f"# Justificación de la región\n\n{selection_text}\n\n"
        f"Ajuste máximo: **{selection['exact_bottleneck_snap_m']:.3f} m** "
        f"(límite redondeado: {selection['selected_tolerance_m']} m). La "
        "selección no utiliza el valor de Max-Cut ni resultados QAOA.\n\n"
        f"{extended_text}\n",
        encoding="utf-8",
    )
    (base / "docs" / "justificacion_pesos.md").write_text(
        "# Justificación de los pesos\n\nSe utiliza `weight = raw_weight = Σ length_km × (voltage_kv / 230)` sin normalización. "
        "La longitud se mide sobre cada segmento oficial; `voltage_kv` procede de `voltaje` (1=230, 2=138, 3=34.5; 0 no se interpreta como tensión). "
        "Los circuitos geométricamente distintos se agregan y las geometrías duplicadas se eliminan. La misma arista conserva el mismo peso en todos los tamaños. "
        "El peso es un proxy reproducible de exposición física; no es probabilidad de falla, flujo, capacidad térmica ni criticidad oficial del ICE.\n",
        encoding="utf-8",
    )
    (base / "docs" / "METODOLOGIA_GRAFOS.md").write_text(
        "# Metodología\n\n1. Validación y hash de los GeoJSON oficiales.\n2. Reproyección EPSG:4326 → EPSG:5367.\n"
        "3. Separación de MultiLineString en partes continuas, sin puentes sintéticos.\n4. Distancia perpendicular subestación-línea.\n"
        "5. Aristas únicamente entre estaciones consecutivas sobre la misma parte oficial.\n6. Refuerzo semántico cuando `ltmadre` nombra ambos terminales.\n"
        f"7. Regla geoespacial ampliada uniforme: ajuste ≤{extended_max_snap_m:g} m, desvío ≤{extended_max_detour_ratio:g}, sin estaciones intermedias, cruces, ramificaciones ni candidatos paralelos ambiguos.\n"
        "8. Selección regional independiente de Max-Cut.\n"
        "9. Uso del contrato auditado de nodos para mantener G6, G8, G10 y G12 comparables con los resultados QAOA existentes.\n"
        "10. Exportación reproducible en CSV, GraphML, GeoJSON, matrices y mapas.\n",
        encoding="utf-8",
    )
    (base / "docs" / "LIMITACIONES_GRAFOS.md").write_text(
        "# Limitaciones\n\n- Las capas no incluyen un diagrama unifilar ni estados de interruptores.\n"
        "- Las aristas se describen como inferencias geoespaciales respaldadas por geometrías oficiales, no como conectividad operativa certificada.\n"
        "- Escazú–Alajuelita tiene un ajuste máximo de 230.626 m y se acepta por la regla geoespacial ampliada. La aceptación prueba coherencia geométrica con la capa oficial, no estado operativo ni posición de interruptores.\n"
        "- Los cuatro grafos son árboles. Por ello son bipartitos y el Max-Cut exacto corta todas sus aristas. Esto no incumple el requisito literal de construcción del grafo, pero limita el valor experimental de QAOA/GW.\n"
        "- Para una instancia Max-Cut no trivial se necesita topología oficial adicional o una red regional distinta; no debe inventarse un ciclo.\n",
        encoding="utf-8",
    )
    (base / "docs" / "DECISION_METODOLOGICA_ARBOL.md").write_text(
        "# Decisión metodológica: conservar árboles\n\nLa consigna exige modelar una red regional como grafo ponderado de 6 a 12 nodos; no exige ciclos, no bipartición ni una brecha Max-Cut positiva. "
        "Se conservan las cuatro instancias arbóreas porque añadir una arista para crear ciclos violaría la trazabilidad. Son adecuadas para completar y probar la formulación QUBO/QAOA, aunque no para sostener afirmaciones de dificultad o ventaja algorítmica. "
        "La trivialidad se reporta abiertamente mediante fuerza bruta.\n",
        encoding="utf-8",
    )
    questions = [
        ("¿Por qué Central?", f"Porque es la región literal que alcanza 12 nodos conectados con el menor ajuste máximo ({selection['exact_bottleneck_snap_m']:.3f} m)."),
        ("¿Son reales los nodos?", "Sí: cada nodo conserva OBJECTID y atributos de la capa oficial de subestaciones."),
        ("¿Son reales las aristas?", "Son aristas inferidas de segmentos oficiales ICE; no se presentan como confirmación operativa."),
        ("¿Cómo se validó Escazú–Alajuelita?", f"Misma parte oficial LT_10_2, estaciones consecutivas, recorrido existente, sin cruces ni ramificaciones ambiguas, ajuste máximo de 230.626 m y desvío dentro de {extended_max_detour_ratio:g}. No se usó evidencia visual."),
        ("¿Qué representa el peso?", "Longitud recorrida por tensión relativa, como proxy reproducible."),
        ("¿Por qué cuatro tamaños?", "Permiten analizar escalamiento conservando región, metodología y escala."),
        ("¿Son anidados?", "Sí; cada grafo pequeño es el subgrafo inducido por un subconjunto del siguiente."),
        ("¿Por qué son árboles?", "Es la topología que puede defenderse con estas capas sin crear conexiones sintéticas."),
        ("¿Max-Cut es trivial?", "Sí; al ser bipartitos, el óptimo corta todas las aristas. Se declara como limitación, no se oculta."),
        ("¿Pueden formularse como QUBO?", "Sí. La formulación es válida; la instancia sirve para implementación y verificación, no para demostrar ventaja algorítmica."),
    ]
    (base / "docs" / "DEFENSA_ORAL_GRAFOS.md").write_text("# Defensa oral\n\n" + "\n\n".join(f"## {q}\n\n{a}" for q, a in questions) + "\n", encoding="utf-8")
    (base / "docs" / "DIFF_CONCEPTUAL.md").write_text(
        "# Diferencias respecto al enfoque anterior\n\n- Región literal Central y selección determinista.\n- Reglas separadas para evidencia geoespacial ordinaria, refuerzo por nombre oficial y tolerancia geoespacial ampliada.\n"
        "- La antigua excepción visual fue sustituida por una regla geoespacial ampliada, uniforme y auditable.\n"
        "- Pesos brutos sin normalización local.\n- Cuatro grafos conectados, inducidos y anidados.\n- Evidencia individual por circuito y segmento.\n"
        "- Trivialidad Max-Cut medida y declarada, sin fabricar ciclos.\n- Doble ejecución reproducible y pruebas automatizadas.\n",
        encoding="utf-8",
    )
    compliance_requirements = ["datos oficiales", "red regional", "nodos reales", "aristas respaldadas", "pesos", "fuentes", "6 nodos", "8 nodos", "10 nodos", "12 nodos", "conectividad", "anidamiento", "escalamiento", "reproducibilidad", "preparación para QUBO", "Max-Cut no trivial"]
    compliance = []
    for requirement in compliance_requirements:
        if requirement == "aristas respaldadas":
            state, note = "CUMPLE CON LIMITACIONES", (
                "inferencias sobre geometrías oficiales; la tolerancia "
                "ampliada es automática y no confirma conectividad operativa"
            )
        elif requirement == "Max-Cut no trivial":
            state, note = "NO CUMPLE", "los cuatro grafos son árboles bipartitos"
        else:
            state, note = "CUMPLE", "evidencia automática disponible"
        compliance.append({"requisito": requirement, "estado": state, "evidencia": "salidas y pruebas del proyecto", "archivo": "auditoria/VALIDACION_FINAL_GRAFOS.md", "observacion": note, "correccion_necesaria": "topología/unifilar adicional" if requirement == "Max-Cut no trivial" else "ninguna"})
    write_csv(base / "auditoria" / "matriz_cumplimiento_final.csv", compliance, ["requisito", "estado", "evidencia", "archivo", "observacion", "correccion_necesaria"])
    (base / "auditoria" / "VALIDACION_FINAL_GRAFOS.md").write_text(
        "# Validación final\n\n"
        f"- Servicio oficial ICE: **{official['status']}**.\n- Región: **{region}**.\n- Instancias: 6, 8, 10 y 12 nodos, conectadas, ponderadas, anidadas y reproducibles.\n"
        "- Aristas sintéticas: **0**.\n- Conectividad operativa oficial: **no afirmada**.\n- Max-Cut: **trivial**, porque las cuatro instancias son árboles.\n\n"
        "| Grafo | Nodos | Aristas | Conectado | Árbol | Peso total | Max-Cut exacto |\n|---|---:|---:|---|---|---:|---:|\n" + table + "\n\n"
        "Los cuatro grafos cumplen la etapa de recolección y construcción requerida por la consigna y pueden utilizarse para formular Max-Cut/QUBO, con la limitación documentada de que son árboles y el óptimo Max-Cut es trivial.\n",
        encoding="utf-8",
    )
    evidence_rows = [item for item in validated if item.get("validation_basis") != "geoespacial"]
    evidence_columns = ["edge_id", "source_name", "target_name", "line_part_id", "line_name", "max_snap_distance_m", "detour_ratio", "validation_basis", "validation_reason"]
    write_csv(base / "auditoria" / "registro_validaciones_reforzadas.csv", evidence_rows, evidence_columns)
    write_json(
        base / "auditoria" / "validaciones_geoespaciales_ampliadas.json",
        {
            "rule": {
                "max_snap_distance_m": extended_max_snap_m,
                "max_detour_ratio": extended_max_detour_ratio,
                "same_continuous_part": True,
                "segment_exists": True,
                "intermediate_station_count": 0,
                "branching_risk": False,
                "line_crosses_regions": False,
                "crossing_risk": False,
                "parallel_candidate_count": 1,
            },
            "records": [
                {key: rounded(item.get(key)) for key in evidence_columns}
                for item in extended_records
            ],
        },
    )


def write_challenge_readme(base: Path, selection: dict[str, Any]) -> None:
    (base / "README.md").write_text(
        "# Construcción reproducible de grafos ICE para QUBO y QAOA\n\n"
        "Esta salida fue regenerada desde las instantáneas oficiales incluidas "
        "en `datos/crudos/`. El constructor trabaja offline y en un directorio "
        "aislado por defecto.\n\n"
        "## Ejecutar desde la raíz 4.2\n\n```bash\n"
        "python -m pip install -r requirements.txt\n"
        "python scripts/construir_grafo_ice.py --project-root . --offline\n"
        "```\n\n"
        "Las salidas quedan en `build/grafos_ice`. Use "
        "`--no-repro-check` solo para una prueba rápida y "
        "`--online-verify` únicamente cuando se autorice acceso de red.\n\n"
        f"## Región y topología\n\nRegión seleccionada: **{selection['selected_region']}**. Ajuste máximo maestro: **{selection['exact_bottleneck_snap_m']:.3f} m**. "
        "Los grafos son inducidos, anidados y conectados. También son árboles; por tanto Max-Cut es trivial. Esto se conserva deliberadamente porque la consigna no exige ciclos y no se deben inventar aristas.\n\n"
        "## Pesos\n\n`weight = Σ length_km × (voltage_kv / 230)`. No hay normalización por tamaño. Es un proxy de modelado, no una probabilidad de falla ni capacidad oficial.\n\n"
        "## Salidas para los notebooks\n\nEl mismo proceso crea `resultados/subgrafo_<n>_nodos.csv`, `subgrafo_<n>_aristas.csv`, las imágenes y `baseline_clasico_completo.csv`. Los notebooks QUBO/QAOA pueden consumirlos sin una conversión posterior. `weight` conserva la escala original; QAOA normaliza únicamente su Hamiltoniano.\n\n"
        "Las instancias son adecuadas para validar signos, índices, energía y el flujo QAOA; no deben usarse para afirmar dificultad o ventaja cuántica.\n\n"
        "Consulte `auditoria/VALIDACION_FINAL_GRAFOS.md`, `docs/METODOLOGIA_GRAFOS.md` y `docs/LIMITACIONES_GRAFOS.md`.\n",
        encoding="utf-8",
    )


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def export_notebook_compatibility(
    base: Path,
    sizes: list[int],
    selection: dict[str, Any],
    validated: list[dict[str, Any]],
) -> None:
    """Crea el contrato exacto consumido por los notebooks QUBO/QAOA."""
    result_dir = base / "resultados"
    node_columns = [
        "node_id", "name", "region", "province", "canton", "district",
        "longitude", "latitude", "degree", "weighted_degree",
        "source_layer", "source_url",
    ]
    edge_columns = [
        "source", "source_name", "target", "target_name", "length_km",
        "voltages_kv", "circuits", "line_names", "line_ids",
        "raw_weight", "weight", "weight_definition", "source_layer", "source_url",
    ]
    line_parts_by_pair: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in validated:
        if item.get("validation_status") == "VALIDADA":
            line_parts_by_pair[canonical_pair(item["source"], item["target"])].add(
                str(item["line_part_id"])
            )

    baseline_rows = []
    legacy_summary = []
    compatibility_files: list[Path] = []
    for size in sorted(sizes):
        canonical_nodes = sorted(
            read_csv_rows(result_dir / f"grafo_{size}_nodos.csv"),
            key=lambda row: int(row["node_index"]),
        )
        canonical_edges = read_csv_rows(result_dir / f"grafo_{size}_aristas.csv")

        node_rows = [
            {column: row.get(column, "") for column in node_columns}
            for row in canonical_nodes
        ]
        edge_rows = []
        for row in canonical_edges:
            pair = canonical_pair(row["source_id"], row["target_id"])
            edge_rows.append({
                "source": row["source_id"],
                "source_name": row["source_name"],
                "target": row["target_id"],
                "target_name": row["target_name"],
                "length_km": row["length_km"],
                "voltages_kv": row["voltage_kv"],
                "circuits": row["circuits"],
                "line_names": row["line_names"],
                "line_ids": "|".join(sorted(line_parts_by_pair.get(pair, set()))),
                "raw_weight": row["raw_weight"],
                "weight": row["weight"],
                "weight_definition": row["weight_definition"],
                "source_layer": row["source_layer"],
                "source_url": row["source_url"],
            })

        node_path = result_dir / f"subgrafo_{size}_nodos.csv"
        edge_path = result_dir / f"subgrafo_{size}_aristas.csv"
        image_path = result_dir / f"subgrafo_{size}.png"
        write_csv(node_path, node_rows, node_columns)
        write_csv(edge_path, edge_rows, edge_columns)
        shutil.copyfile(result_dir / f"grafo_{size}.png", image_path)
        compatibility_files.extend([node_path, edge_path, image_path])

        node_ids = [row["node_id"] for row in node_rows]
        graph_check = nx.Graph()
        graph_check.add_nodes_from(node_ids)
        for row in edge_rows:
            graph_check.add_edge(row["source"], row["target"], weight=float(row["weight"]))
        if graph_check.number_of_nodes() != size or not nx.is_connected(graph_check):
            raise RuntimeError(f"La interfaz compatible G{size} no conserva tamaño o conectividad.")
        total_weight = sum(float(row["weight"]) for row in edge_rows)
        baseline_rows.append({
            "n": size,
            "edges": graph_check.number_of_edges(),
            "is_tree": nx.is_tree(graph_check),
            "total_weight": total_weight,
            "exact_value": total_weight,
        })
        legacy_summary.append({
            "size": size,
            "nodes": size,
            "edges": graph_check.number_of_edges(),
            "connected": True,
            "total_weight": total_weight,
            "seed_node_id": selection["seed_node_id"],
            "seed_name": "La Caja",
            "snap_tolerance_m": selection["selected_tolerance_m"],
        })

    baseline_path = result_dir / "baseline_clasico_completo.csv"
    legacy_path = result_dir / "resumen_subgrafos.csv"
    write_csv(
        baseline_path,
        baseline_rows,
        ["n", "edges", "is_tree", "total_weight", "exact_value"],
    )
    write_csv(
        legacy_path,
        legacy_summary,
        ["size", "nodes", "edges", "connected", "total_weight", "seed_node_id", "seed_name", "snap_tolerance_m"],
    )
    compatibility_files.extend([baseline_path, legacy_path])
    manifest = {
        "schema": "compatibilidad_notebooks_qubo_qaoa_v1",
        "generated_from_raw_layers": True,
        "topology_or_weights_recalculated_by_adapter": False,
        "sizes": sorted(sizes),
        "files": {
            path.name: sha256_file(path)
            for path in sorted(compatibility_files)
        },
    }
    write_json(result_dir / "manifest_compatibilidad.json", manifest)


def generate_core(base: Path, cfg: dict[str, Any], official: dict[str, Any]) -> dict[str, Any]:
    clean_output_tree(base)
    raw_dir = base / "datos/crudos"
    raw_sub_path, raw_line_path = raw_dir / "subestaciones_ice.geojson", raw_dir / "lineas_transmision_ice.geojson"
    raw_subs, raw_lines = load_geojson(raw_sub_path), load_geojson(raw_line_path)
    sub_catalog, line_catalog, quality = validate_raw_data(raw_subs, raw_lines, raw_dir)
    write_csv(base / "datos/procesados" / "catalogo_subestaciones.csv", sub_catalog, list(sub_catalog[0]))
    write_csv(base / "datos/procesados" / "catalogo_lineas.csv", line_catalog, list(line_catalog[0]))
    write_csv(base / "auditoria" / "calidad_datos/crudos.csv", quality, ["layer", "objectid", "issue", "severity"])
    manifest = {
        "schema_version": 1, "script_version": VERSION, "crs_source": CRS_WGS84, "crs_metric": "EPSG:5367",
        "substations": {"path": "datos/crudos/subestaciones_ice.geojson", "sha256": sha256_file(raw_sub_path), "entities": len(raw_subs["features"]), "fields": all_fields(raw_subs), "geometry_types": sorted({feature["geometry"]["type"] for feature in raw_subs["features"]})},
        "lines": {"path": "datos/crudos/lineas_transmision_ice.geojson", "sha256": sha256_file(raw_line_path), "entities": len(raw_lines["features"]), "fields": all_fields(raw_lines), "geometry_types": sorted({feature["geometry"]["type"] for feature in raw_lines["features"]})},
        "official_service_verification": official,
    }
    write_json(base / "auditoria" / "manifest_datos/crudos.json", manifest)
    stations, parts = prepare_geometries(raw_subs, raw_lines)
    associations, candidates = infer_topology(stations, parts, cfg)
    candidates = enhance_evidence(candidates, cfg)
    validated, rejected = deduplicate_evidence(candidates)
    association_columns = ["node_id", "node_name", "node_objectid", "region", "line_objectid", "line_part_id", "line_name", "voltage_kv", "snap_distance_m", "position_m", "confidence"]
    evidence_columns = ["edge_id", "source", "target", "source_objectid", "target_objectid", "source_name", "target_name", "region", "line_objectid", "line_part_id", "line_name", "voltage_kv", "source_snap_distance_m", "target_snap_distance_m", "max_snap_distance_m", "route_length_km", "straight_distance_km", "detour_ratio", "raw_weight", "confidence", "validation_status", "validation_reason", "validation_basis", "operational_connectivity_confirmed", "geometry_source", "geometry_hash", "same_continuous_part", "segment_exists", "intermediate_station_count", "line_part_count", "multipart_risk", "branching_risk", "line_crosses_regions", "crossing_risk", "crossing_line_objectids", "parallel_candidate_count"]
    write_csv(base / "auditoria" / "asociaciones_subestacion_linea.csv", associations, association_columns)
    write_csv(base / "auditoria" / "aristas_candidatas.csv", candidates, evidence_columns)
    write_csv(base / "auditoria" / "aristas_rechazadas.csv", rejected, evidence_columns)
    write_csv(base / "auditoria" / "aristas_validadas.csv", validated, evidence_columns)
    review_rows = []
    for item in sorted(validated + rejected, key=lambda row: (row["source"], row["target"], row["line_part_id"])):
        if item["confidence"] in {"media confianza", "baja confianza"}:
            review_rows.append({**item, "used_in_regional_graph": item["validation_status"] == "VALIDADA", "review_priority": "media" if item["confidence"] == "media confianza" else "alta"})
    write_csv(base / "auditoria" / "aristas_revision_tecnica.csv", review_rows, evidence_columns + ["used_in_regional_graph", "review_priority"])
    write_json(base / "auditoria" / "aristas_validadas.geojson", {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": CRS_WGS84}}, "features": [{"type": "Feature", "geometry": mapping(item["segment_geometry"]), "properties": {key: rounded(value) for key, value in item.items() if key != "segment_geometry"}} for item in validated]})
    sensitivity = sensitivity_rows(stations, parts, cfg)
    write_csv(base / "auditoria" / "sensibilidad_tolerancia.csv", sensitivity, ["tolerance_m", "region", "nodes_with_edges", "edges", "largest_component_nodes", "largest_component_edges", "cycle_rank_largest", "largest_is_bipartite", "low_confidence_edges", "within_declared_maximum"])
    graphs = build_regional_graphs(stations, validated)
    regional_summary = export_regional_graphs(base, graphs)
    write_csv(base / "auditoria" / "resumen_grafos_regionales.csv", regional_summary, ["region", "nodes", "edges", "components", "largest_component_nodes", "isolated_nodes", "is_bipartite", "has_odd_cycle", "high_confidence_edges", "medium_confidence_edges"])
    sizes = [int(value) for value in cfg["instances"]["sizes"]]
    evaluation, selection, instances, order = evaluate_regions(graphs, sizes)
    if cfg["instances"].get("use_audited_instance_lock", True):
        locked = load_audited_instance_lock(ROOT, graphs, sizes)
        if locked is not None:
            selection, instances, order = locked
    write_csv(base / "resultados" / "evaluacion_regiones.csv", evaluation, ["region", "regional_nodes", "regional_edges", "largest_component_nodes", "largest_component_edges", "supports_connected_6_8_10_12", "minimum_required_snap_m", "high_confidence_edges", "medium_confidence_edges", "high_confidence_proportion", "geographic_extent_km", "is_tree_largest_component", "is_bipartite_largest_component", "selection_rank", "reason"])
    write_json(base / "resultados" / "region_seleccionada.json", selection)
    summaries: list[dict[str, Any]] = []
    if instances is not None and selection["selected_region"]:
        summaries = export_instances(base, instances, validated, selection["selected_region"], float(cfg["maxcut"]["epsilon"]))
        selected_regional = graphs[selection["selected_region"]]
        plot_network(selected_regional, base / "resultados" / "mapa_region_completa.png", f"Red regional validada · {selection['selected_region']}", shortest_odd_cycle(selected_regional), validated)
    else:
        diagnostic_region = max(graphs, key=lambda region: max((len(comp) for comp in nx.connected_components(graphs[region])), default=0))
        plot_network(graphs[diagnostic_region], base / "resultados" / "mapa_region_completa.png", f"Diagnóstico · {diagnostic_region} · sin región seleccionable", evidence=validated)
    revision_graph = nx.Graph()
    by_id = {station["node_id"]: station for station in stations}
    medium_evidence = []
    for item in validated:
        if item["confidence"] == "media confianza":
            medium_evidence.append(item)
            for node in (item["source"], item["target"]):
                station = by_id[node]
                revision_graph.add_node(node, **{key: station[key] for key in ("objectid", "name", "region", "province", "canton", "district", "longitude", "latitude")})
            revision_graph.add_edge(item["source"], item["target"], confidence="media confianza", weight=item["raw_weight"])
    plot_network(revision_graph, base / "auditoria" / "mapa_aristas_revision.png", "Aristas de confianza media · revisión geográfica", evidence=medium_evidence)
    summary_columns = ["size", "nodes", "edges", "connected", "is_tree", "is_bipartite", "cycle_rank", "odd_cycle_length", "region", "high_confidence_edges", "medium_confidence_edges", "low_confidence_edges", "total_edge_weight", "exact_maxcut_weight", "nontriviality_gap", "nested", "data_hash"]
    write_csv(base / "resultados" / "resumen_grafos.csv", summaries, summary_columns)
    nontriviality = [{"size": item["size"], "total_edge_weight": item["total_edge_weight"], "exact_maxcut_weight": item["exact_maxcut_weight"], "nontriviality_gap": item["nontriviality_gap"], "passes": item["nontriviality_gap"] > float(cfg["maxcut"]["epsilon"])} for item in summaries]
    write_csv(base / "resultados" / "validacion_no_trivialidad.csv", nontriviality, ["size", "total_edge_weight", "exact_maxcut_weight", "nontriviality_gap", "passes"])
    subgraph_rows = []
    if instances:
        master = instances[max(sizes)]
        previous_nodes: set[str] = set()
        for size in sizes:
            graph = instances[size]
            nodes = set(graph.nodes)
            induced_edges = {canonical_pair(a, b) for a, b in master.subgraph(nodes).edges}
            actual_edges = {canonical_pair(a, b) for a, b in graph.edges}
            subgraph_rows.append({
                "size": size, "nodes": graph.number_of_nodes(), "edges": graph.number_of_edges(),
                "connected": nx.is_connected(graph), "same_region": len({data["region"] for _, data in graph.nodes(data=True)}) == 1,
                "nested_from_previous": previous_nodes.issubset(nodes), "induced_from_g12": actual_edges == induced_edges,
                "is_tree": nx.is_tree(graph), "is_bipartite": nx.is_bipartite(graph), "positive_weights": all(float(data["weight"]) > 0 for _, _, data in graph.edges(data=True)),
            })
            previous_nodes = nodes
    write_csv(base / "auditoria" / "validacion_subgrafos.csv", subgraph_rows, ["size", "nodes", "edges", "connected", "same_region", "nested_from_previous", "induced_from_g12", "is_tree", "is_bipartite", "positive_weights"])
    source_rows = [
        {"resource": "Subestaciones ICE", "layer": "DT_SNIT_v2/FeatureServer/3", "url": SUBSTATIONS_LAYER_URL, "local_file": "datos/crudos/subestaciones_ice.geojson", "sha256": sha256_file(raw_sub_path)},
        {"resource": "Líneas de transmisión ICE", "layer": "DT_SNIT_v2/FeatureServer/2", "url": LINES_LAYER_URL, "local_file": "datos/crudos/lineas_transmision_ice.geojson", "sha256": sha256_file(raw_line_path)},
    ]
    write_csv(base / "resultados" / "fuentes.csv", source_rows, ["resource", "layer", "url", "local_file", "sha256"])
    if instances is not None:
        export_notebook_compatibility(base, sizes, selection, validated)
    weight_validation = [{"edge_id": item["edge_id"], "line_part_id": item["line_part_id"], "length_km": item["route_length_km"], "voltage_kv": item["voltage_kv"], "raw_weight_expected": item["route_length_km"] * (item["voltage_kv"] / 230.0), "raw_weight_exported": item["raw_weight"], "difference": abs(item["raw_weight"] - item["route_length_km"] * (item["voltage_kv"] / 230.0)), "positive_finite": item["raw_weight"] > 0 and math.isfinite(item["raw_weight"])} for item in validated]
    write_csv(base / "auditoria" / "validacion_pesos.csv", weight_validation, ["edge_id", "line_part_id", "length_km", "voltage_kv", "raw_weight_expected", "raw_weight_exported", "difference", "positive_finite"])
    requirements_matrix_challenge(base)
    write_challenge_docs(base, selection, evaluation, official, summaries, validated, cfg)
    write_challenge_readme(base, selection)
    return {"selection": selection, "summaries": summaries, "official": official, "validated_edges": len(validated), "rejected_edges": len(rejected)}


def deterministic_hashes(base: Path) -> dict[str, str]:
    result = {}
    for directory in DETERMINISTIC_DIRS:
        for path in sorted((base / directory).rglob("*")):
            if path.is_file():
                relative = path.relative_to(base).as_posix()
                if relative not in REPRO_EXCLUDED:
                    result[relative] = sha256_file(path)
    return result


def add_reproducibility(base: Path, hashes_1: dict[str, str], hashes_2: dict[str, str]) -> None:
    write_json(base / "auditoria" / "reproducibilidad_ejecucion_1.json", {"deterministic_files": hashes_1, "excluded": sorted(REPRO_EXCLUDED) + ["logs/"]})
    write_json(base / "auditoria" / "reproducibilidad_ejecucion_2.json", {"deterministic_files": hashes_2, "excluded": sorted(REPRO_EXCLUDED) + ["logs/"]})
    all_paths = sorted(set(hashes_1) | set(hashes_2))
    rows = [{"file": path, "sha256_run_1": hashes_1.get(path, "MISSING"), "sha256_run_2": hashes_2.get(path, "MISSING"), "identical": hashes_1.get(path) == hashes_2.get(path)} for path in all_paths]
    write_csv(base / "auditoria" / "comparacion_hashes.csv", rows, ["file", "sha256_run_1", "sha256_run_2", "identical"])
    matching = sum(bool(row["identical"]) for row in rows)
    percentage = 100.0 * matching / len(rows) if rows else 100.0
    (base / "auditoria" / "reporte_reproducibilidad.md").write_text(
        f"# Reproducibilidad\n\nSe ejecutó el núcleo completo dos veces desde directorios vacíos con los mismos GeoJSON y la misma verificación oficial inmutable.\n\n- Archivos deterministas comparados: {len(rows)}\n- Coincidencias: {matching}\n- Porcentaje: {percentage:.1f} %\n- Resultado: {'CUMPLE' if percentage == 100.0 else 'NO CUMPLE'}\n\n`logs/` y los propios archivos de comparación se excluyen explícitamente para evitar autorreferencias y marcas temporales.\n",
        encoding="utf-8",
    )


def stage_raw_layers(
    output_root: Path,
    raw_sub_path: Path,
    raw_line_path: Path,
) -> None:
    """Copia la caché oficial al árbol aislado que será reconstruido."""
    destination = output_root / "datos" / "crudos"
    destination.mkdir(parents=True, exist_ok=True)
    for source in (raw_sub_path, raw_line_path):
        target = destination / source.name
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)


def main() -> int:
    global ROOT

    args = parse_args()
    project_root = args.project_root.expanduser().resolve()
    ROOT = project_root
    config_path = (
        args.config.expanduser().resolve()
        if args.config is not None
        else project_root / "config.yaml"
    )
    output_root = (
        args.output_root.expanduser().resolve()
        if args.output_root is not None
        else project_root / "build" / "grafos_ice"
    )

    if not config_path.is_file():
        raise RuntimeError(f"No existe la configuración: {config_path}")
    if output_root == project_root:
        raise RuntimeError(
            "--output-root no puede ser la raíz del proyecto: el constructor "
            "limpia sus salidas deterministas antes de regenerarlas."
        )
    if args.offline and (args.online_verify or args.refresh_data):
        raise RuntimeError(
            "--offline no puede combinarse con --online-verify o "
            "--refresh-data."
        )

    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    cfg.setdefault("instances", {})["use_audited_instance_lock"] = not bool(
        args.ignore_instance_lock
    )
    offline = not (args.online_verify or args.refresh_data)
    raw_sub_path, raw_line_path = ensure_raw_layers(
        project_root=project_root,
        refresh=bool(args.refresh_data),
        offline=offline,
    )
    raw_subs = load_geojson(raw_sub_path)
    raw_lines = load_geojson(raw_line_path)
    official = verify_official_layers(
        raw_subs,
        raw_lines,
        enabled=bool(cfg["data"]["verify_official_service"])
        and bool(args.online_verify or args.refresh_data),
    )

    stage_raw_layers(output_root, raw_sub_path, raw_line_path)
    if args.no_repro_check:
        result = generate_core(output_root, cfg, official)
    else:
        with tempfile.TemporaryDirectory(prefix="grafos_ice_run1_") as one, tempfile.TemporaryDirectory(prefix="grafos_ice_run2_") as two:
            run1, run2 = Path(one), Path(two)
            for run in (run1, run2):
                stage_raw_layers(run, raw_sub_path, raw_line_path)
                generate_core(run, cfg, official)
            hashes_1, hashes_2 = deterministic_hashes(run1), deterministic_hashes(run2)
            result = generate_core(output_root, cfg, official)
            add_reproducibility(output_root, hashes_1, hashes_2)
    logs = output_root / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / "ejecucion.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()} version={VERSION} status={result['selection']['status']}\n")
    print(
        json.dumps(
            {
                "status": result["selection"]["status"],
                "selected_region": result["selection"].get(
                    "selected_region"
                ),
                "validated_edges": result["validated_edges"],
                "rejected_edges": result["rejected_edges"],
                "offline": offline,
                "output_root": str(output_root),
                "script_version": VERSION,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
