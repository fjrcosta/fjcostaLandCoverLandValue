#!/usr/bin/env python3
"""Validate the static website data and required asset references using stdlib only."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
MAP3D = SITE / "map3d"


def fail(message: str) -> None:
    raise SystemExit(f"VALIDATION ERROR: {message}")


def main() -> None:
    landing = SITE / "index.html"
    index = MAP3D / "index.html"
    app = MAP3D / "assets" / "app.js"
    css = MAP3D / "assets" / "styles.css"
    manifest_path = MAP3D / "data" / "manifest.json"
    transport_manifest_path = MAP3D / "data" / "transport" / "manifest.json"
    economics_path = MAP3D / "data" / "economics" / "municipalities.geojson"
    reach_js = MAP3D / "assets" / "reachability.js"
    reach_params_path = MAP3D / "data" / "reachability" / "params.json"
    reach_data_path = MAP3D / "data" / "reachability" / "londrina.json"
    for path in (landing, index, app, css, manifest_path, transport_manifest_path, economics_path,
                 reach_js, reach_params_path, reach_data_path):
        if not path.exists():
            fail(f"Missing {path.relative_to(ROOT)}")

    html = index.read_text(encoding="utf-8")
    for ref in ("./assets/app.js", "./assets/styles.css"):
        if ref not in html:
            fail(f"index.html does not reference {ref}")
    required_ids = [
        "map", "citySelect", "coverDimension", "valueDimension", "transportDimension",
        "heightScale", "valueTint", "coverTint", "transportTint", "classFilters",
        "roadFilters", "toggleRoadClasses", "ludDimension", "lvyDimension",
        "economicsInsightContent", "loadingOverlay", "aboutDialog",
        "reachDimension", "reachMode", "reachSummary", "reachStatus"
    ]
    for element_id in required_ids:
        if not re.search(rf'id=["\']{re.escape(element_id)}["\']', html):
            fail(f"index.html is missing #{element_id}")
    if "data-mode=" in html:
        fail("index.html still contains exclusive analytical-mode buttons")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 4:
        fail("Manifest does not use schema version 4")
    if manifest.get("datasetMode") == "model-output":
        if manifest.get("modelConfiguration") != 60:
            fail("Model-output manifest does not identify configuration 60")
        if manifest.get("referenceParcelAreaM2") != 450:
            fail("Model-output manifest does not identify the 450 m² reference parcel")
    classes = manifest.get("classes", [])
    cities = manifest.get("cities", [])
    if len(classes) != 10:
        fail(f"Expected 10 classes, found {len(classes)}")
    if not cities:
        fail("Manifest contains no cities")

    class_keys = [item["key"] for item in classes]
    if len(class_keys) != len(set(class_keys)):
        fail("Class keys are not unique")

    total = 0
    for meta in cities:
        city_path = MAP3D / meta["file"]
        if not city_path.exists():
            fail(f"Missing city data file {meta['file']}")
        city = json.loads(city_path.read_text(encoding="utf-8"))
        if city.get("schemaVersion") != 4:
            fail(f"{meta['file']} does not use schema version 4")
        if city.get("slug") != meta.get("slug"):
            fail(f"City slug mismatch in {meta['file']}")
        cells = city.get("cells", [])
        if not cells:
            fail(f"No cells in {meta['file']}")
        seen_centres = set()
        for i, cell in enumerate(cells):
            if len(cell) != 10:
                fail(f"{meta['file']} cell {i} has {len(cell)} fields, expected 10")
            (lon, lat, price, class_index, confidence, distance,
             pointwise_width, q10, q90, polygon) = cell
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                fail(f"Invalid coordinate in {meta['file']} cell {i}")
            centre_key = (lon, lat)
            if centre_key in seen_centres:
                fail(f"Duplicate patch centre in {meta['file']} cell {i}")
            seen_centres.add(centre_key)
            if not (price > 0):
                fail(f"Non-positive price in {meta['file']} cell {i}")
            if not (0 <= class_index < len(classes)):
                fail(f"Invalid class index in {meta['file']} cell {i}")
            if not (0 <= confidence <= 1):
                fail(f"Invalid confidence in {meta['file']} cell {i}")
            if distance < 0:
                fail(f"Negative match distance in {meta['file']} cell {i}")
            if pointwise_width < 0:
                fail(f"Negative pointwise normalized interval width in {meta['file']} cell {i}")
            if not (0 < q10 <= price <= q90):
                fail(f"Invalid predictive-quantile ordering in {meta['file']} cell {i}")
            if len(polygon) != 4:
                fail(f"{meta['file']} cell {i} does not contain four patch vertices")
            for vertex_lon, vertex_lat in polygon:
                if not (-180 <= vertex_lon <= 180 and -90 <= vertex_lat <= 90):
                    fail(f"Invalid patch vertex in {meta['file']} cell {i}")
            mean_lon = sum(vertex[0] for vertex in polygon) / 4
            mean_lat = sum(vertex[1] for vertex in polygon) / 4
            dy = math.radians(mean_lat - lat) * 6_371_008.8
            dx = math.radians(mean_lon - lon) * 6_371_008.8 * math.cos(math.radians((mean_lat + lat) / 2))
            if math.hypot(dx, dy) > 0.2:
                fail(f"Patch polygon is not centred on its record in {meta['file']} cell {i}")
        if meta.get("stats", {}).get("cells") != len(cells):
            fail(f"Cell count mismatch in manifest for {meta['slug']}")
        total += len(cells)

    if manifest.get("globalStats", {}).get("cells") != total:
        fail("Global cell count does not match city files")

    transport = json.loads(transport_manifest_path.read_text(encoding="utf-8"))
    if transport.get("schemaVersion") != 1:
        fail("Transport manifest does not use schema version 1")
    road_classes = transport.get("classes", [])
    if [item.get("key") for item in road_classes] != [
        "motorway", "trunk", "primary", "secondary", "residential"
    ]:
        fail("Transport manifest has unexpected OSM highway classes")
    transport_cities = transport.get("cities", [])
    if {item.get("slug") for item in transport_cities} != {item.get("slug") for item in cities}:
        fail("Transport and analytical manifests cover different cities")

    total_roads = 0
    for meta in transport_cities:
        road_path = MAP3D / meta["file"]
        if not road_path.exists():
            fail(f"Missing transport data file {meta['file']}")
        city = json.loads(road_path.read_text(encoding="utf-8"))
        if city.get("schemaVersion") != 1 or city.get("slug") != meta.get("slug"):
            fail(f"Invalid transport metadata in {meta['file']}")
        roads = city.get("roads", [])
        if meta.get("segments") != len(roads):
            fail(f"Transport segment count mismatch for {meta['slug']}")
        seen = set()
        for i, road in enumerate(roads):
            if len(road) != 2:
                fail(f"{meta['file']} road {i} has {len(road)} fields, expected 2")
            class_index, path = road
            if not (0 <= class_index < len(road_classes)) or len(path) < 2:
                fail(f"Invalid road record in {meta['file']} at {i}")
            for lon, lat in path:
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    fail(f"Invalid road coordinate in {meta['file']} at {i}")
            forward = tuple(tuple(point) for point in path)
            canonical = min(forward, tuple(reversed(forward)))
            key = (class_index, canonical)
            if key in seen:
                fail(f"Duplicate directed road geometry in {meta['file']} at {i}")
            seen.add(key)
        total_roads += len(roads)

    if transport.get("globalStats", {}).get("segments") != total_roads:
        fail("Global transport count does not match city files")

    economics = json.loads(economics_path.read_text(encoding="utf-8"))
    features = economics.get("features", [])
    if economics.get("type") != "FeatureCollection" or len(features) != len(cities):
        fail("Municipal economics GeoJSON must contain one feature per municipality")
    economics_slugs = {feature.get("properties", {}).get("slug") for feature in features}
    if economics_slugs != {item.get("slug") for item in cities}:
        fail("Municipal economics GeoJSON and analytical manifest cover different municipalities")
    required_economics = {
        "developed_extent_km2_2024", "gva_csi_usd_million_2023", "lud_2023_2024",
        "developed_land_value_usd_million_2024", "lvy_2023_2024"
    }
    for feature in features:
        properties = feature.get("properties", {})
        if not required_economics.issubset(properties):
            fail(f"Incomplete economics data for {properties.get('slug', 'unknown')}")
        if not feature.get("geometry"):
            fail(f"Missing economics geometry for {properties.get('slug', 'unknown')}")

        def coordinates(value):
            if (isinstance(value, list) and len(value) >= 2
                    and all(isinstance(item, (int, float)) for item in value[:2])):
                yield value
            elif isinstance(value, list):
                for item in value:
                    yield from coordinates(item)

        geometry = feature["geometry"]
        geometries = geometry.get("geometries", [geometry])
        points = [point for part in geometries for point in coordinates(part.get("coordinates", []))]
        if not points or not all(-180 <= point[0] <= 180 and -90 <= point[1] <= 90 for point in points):
            fail(f"Economics geometry is not EPSG:4326 for {properties.get('slug', 'unknown')}")

    reach = json.loads(reach_data_path.read_text(encoding="utf-8"))
    if reach.get("schemaVersion") != 1:
        fail("Reachability data does not use schema version 1")
    reach_meta = next((item for item in cities if item.get("slug") == reach.get("city")), None)
    if reach_meta is None:
        fail(f"Reachability city {reach.get('city')} is not in the analytical manifest")
    reach_cells = len(json.loads((MAP3D / reach_meta["file"]).read_text(encoding="utf-8"))["cells"])
    for network in ("walk", "drive"):
        graph = reach[network]
        n, m = len(graph["lon"]), len(graph["targets"])
        if len(graph["lat"]) != n or len(graph["offsets"]) != n + 1 or graph["offsets"][-1] != m or len(graph["lengths"]) != m:
            fail(f"Inconsistent CSR arrays in the reachability {network} network")
        if any(not 0 <= target < n for target in graph["targets"]) or any(length < 0 for length in graph["lengths"]):
            fail(f"Invalid edge in the reachability {network} network")
    walk_n, drive_n = len(reach["walk"]["lon"]), len(reach["drive"]["lon"])
    cell_links = reach["cells"]
    if any(len(cell_links[key]) != reach_cells for key in ("walkNode", "walkSnapM", "driveNode", "driveSnapM")):
        fail("Reachability cell links and analytical cells are out of sync")
    if any(not 0 <= node < walk_n for node in cell_links["walkNode"]) or any(not 0 <= node < drive_n for node in cell_links["driveNode"]):
        fail("Reachability cell links reference missing network nodes")
    stops = reach["stops"]
    n_stops = len(stops["name"])
    if any(len(stops[key]) != n_stops for key in ("lon", "lat", "walkNode", "walkSnapM", "hub")):
        fail("Inconsistent reachability stop arrays")
    for i, pattern in enumerate(reach["patterns"]):
        sequence, cumulative = pattern["stops"], pattern["cum"]
        if len(sequence) < 2 or len(sequence) != len(cumulative) or any(not 0 <= s < n_stops for s in sequence):
            fail(f"Invalid bus stop pattern {i}")
        if any(b < a for a, b in zip(cumulative, cumulative[1:])):
            fail(f"Bus stop pattern {i} has decreasing on-route distance")
    params = json.loads(reach_params_path.read_text(encoding="utf-8"))
    required_params = {
        "walk": {"speedKmh"},
        "car": {"speedKmh", "walkToCarMin", "parkAndWalkMin"},
        "bus": {"speedKmh", "walkSpeedKmh", "maxAccessWalkMin", "waitMin", "terminalTransferWaitMin", "maxEgressWalkMin"},
    }
    if "budgetMin" not in params or any(not keys.issubset(params.get(mode, {})) for mode, keys in required_params.items()):
        fail("Reachability params.json is incomplete")

    print(
        f"Validated static site: {len(cities)} cities, {len(classes)} classes, "
        f"{total:,} cells, {total_roads:,} unique OSM road geometries, "
        f"{len(features)} municipal economics polygons, "
        f"reachability {reach['city']} ({walk_n:,} walk / {drive_n:,} drive nodes, {n_stops:,} stops, "
        f"{len(reach['patterns'])} bus patterns), datasetMode={manifest.get('datasetMode')}"
    )


if __name__ == "__main__":
    main()
