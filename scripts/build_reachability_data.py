#!/usr/bin/env python3
"""Build compact Londrina network data for in-browser one-hour reachability.

All heavy work happens here: OSM walk/drive graphs are downloaded once and
flattened to CSR arrays, every analytical cell and bus stop is snapped to its
nearest network node, and bus trips become ordered stop patterns with the
cumulative on-route distance of each stop. The browser only runs bounded
Dijkstra searches; travel-time parameters live in params.json and are applied
at runtime, so changing them requires no rebuild.
"""

import argparse
import json
import re
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point, shape
from shapely.ops import substring

METRIC_CRS = "EPSG:31982"
TERMINAL_PATTERN = re.compile(r"termin|plataforma", re.IGNORECASE)


def to_csr(graph: nx.MultiDiGraph) -> tuple[list[int], dict]:
    """Flatten a directed OSM graph to CSR arrays keeping the shortest parallel edge.

    :param graph: projected-or-geographic OSMnx graph with a ``length`` edge attribute.
    :return: OSM node ids in CSR order, and a dict with ``lon``, ``lat`` (float, n),
        ``offsets`` (int, n + 1), ``targets`` (int, m) and ``lengths`` (metres, m).
    """
    node_ids = list(graph.nodes)
    index = {node: i for i, node in enumerate(node_ids)}
    best: dict[tuple[int, int], float] = {}
    for u, v, data in graph.edges(data=True):
        key = (index[u], index[v])
        length = float(data["length"])
        if key not in best or length < best[key]:
            best[key] = length
    edges = sorted(best.items())
    offsets = np.zeros(len(node_ids) + 1, dtype=np.int64)
    for (u, _), _ in edges:
        offsets[u + 1] += 1
    offsets = np.cumsum(offsets)
    return node_ids, {
        "lon": [round(graph.nodes[n]["x"], 6) for n in node_ids],
        "lat": [round(graph.nodes[n]["y"], 6) for n in node_ids],
        "offsets": offsets.tolist(),
        "targets": [v for (_, v), _ in edges],
        "lengths": [round(length, 1) for _, length in edges],
    }


def largest_component(graph: nx.MultiDiGraph, strongly: bool) -> nx.MultiDiGraph:
    """Keep the largest (strongly or weakly) connected component.

    :param graph: OSMnx graph.
    :param strongly: True for directed drive graphs, False for walk graphs.
    """
    components = nx.strongly_connected_components(graph) if strongly else nx.weakly_connected_components(graph)
    return graph.subgraph(max(components, key=len)).copy()


def snap(points_metric: np.ndarray, graph_csr: dict) -> tuple[list[int], list[float]]:
    """Snap metric points to the nearest graph node.

    :param points_metric: point coordinates in METRIC_CRS, float, shape (k, 2).
    :param graph_csr: CSR dict produced by :func:`to_csr`.
    :return: nearest node index and straight-line snap distance in metres, each of length k.
    """
    nodes = gpd.GeoSeries(gpd.points_from_xy(graph_csr["lon"], graph_csr["lat"]), crs="EPSG:4326").to_crs(METRIC_CRS)
    tree = cKDTree(np.column_stack([nodes.x, nodes.y]))
    distance, node = tree.query(points_metric)
    return node.tolist(), np.round(distance, 1).tolist()


def terminal_hubs(stops: gpd.GeoDataFrame, radius_m: float) -> list[int]:
    """Group terminal/platform stops lying within ``radius_m`` of each other into hubs.

    :param stops: unique stops in METRIC_CRS with a ``stop_name`` column.
    :param radius_m: clustering radius in metres.
    :return: hub index per stop, -1 for ordinary stops.
    """
    is_terminal = stops["stop_name"].str.contains(TERMINAL_PATTERN).to_numpy()
    terminal_idx = np.flatnonzero(is_terminal)
    xy = np.column_stack([stops.geometry.x, stops.geometry.y])[terminal_idx]
    parent = list(range(len(terminal_idx)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in cKDTree(xy).query_pairs(radius_m):
        parent[find(i)] = find(j)
    roots = sorted({find(i) for i in range(len(terminal_idx))})
    root_to_hub = {root: h for h, root in enumerate(roots)}
    hubs = [-1] * len(stops)
    for k, stop_i in enumerate(terminal_idx):
        hubs[stop_i] = root_to_hub[find(k)]
    return hubs


def stop_patterns(routes: gpd.GeoDataFrame, stops_raw: gpd.GeoDataFrame, stop_index: dict[int, int]) -> list[dict]:
    """Turn bus trips into unique ordered stop patterns with cumulative on-route distance.

    Stops are projected progressively along the trip shape so loops do not send a
    later stop back to an earlier part of the line.

    :param routes: one LineString per trip in METRIC_CRS.
    :param stops_raw: per-trip stop records in METRIC_CRS, in travel order.
    :param stop_index: stop_id -> unique stop position.
    """
    patterns: dict[tuple, dict] = {}
    for trip in routes.itertuples():
        line: LineString = trip.geometry
        trip_stops = stops_raw[stops_raw["trip_id"] == trip.trip_id]
        sequence: list[int] = []
        distances: list[float] = []
        position = 0.0
        for stop in trip_stops.itertuples():
            idx = stop_index[stop.stop_id]
            if sequence and sequence[-1] == idx:
                continue
            remainder = substring(line, position, line.length)
            if remainder.length > 0:
                position += remainder.project(stop.geometry)
            sequence.append(idx)
            distances.append(round(position, 1))
        if len(sequence) < 2:
            continue
        key = tuple(sequence)
        if key not in patterns:
            patterns[key] = {
                "route": trip.route_short_name,
                "name": trip.route_long_name,
                "color": trip.route_color,
                "stops": sequence,
                "cum": distances,
            }
    return list(patterns.values())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site-data", type=Path, required=True, help="site/map3d/data directory")
    parser.add_argument("--bus-dir", type=Path, required=True, help="Directory with bus_routes.geojson and bus_stops.geojson")
    parser.add_argument("--city", required=True, help="City slug, e.g. londrina")
    parser.add_argument("--perimeter-buffer-m", type=float, required=True, help="Buffer around the urban perimeter for the OSM download")
    parser.add_argument("--hub-radius-m", type=float, required=True, help="Clustering radius for terminal platforms")
    parser.add_argument("--exclude-route-regex", required=True, help="Routes whose long name matches are dropped, e.g. night lines")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.site_data / "reachability"
    output_dir.mkdir(parents=True, exist_ok=True)

    economics = json.loads((args.site_data / "economics/municipalities.geojson").read_text(encoding="utf-8"))
    perimeter = next(shape(f["geometry"]) for f in economics["features"] if f["properties"]["slug"] == args.city)
    area = gpd.GeoSeries([perimeter], crs="EPSG:4326").to_crs(METRIC_CRS).buffer(args.perimeter_buffer_m).to_crs("EPSG:4326").iloc[0]

    print("Downloading OSM walk network…")
    walk_graph = largest_component(ox.graph_from_polygon(area, network_type="walk", simplify=True), strongly=False)
    print("Downloading OSM drive network…")
    drive_graph = largest_component(ox.graph_from_polygon(area, network_type="drive", simplify=True), strongly=True)
    _, walk = to_csr(walk_graph)
    _, drive = to_csr(drive_graph)
    print(f"  walk: {len(walk['lon'])} nodes, {len(walk['targets'])} directed edges")
    print(f"  drive: {len(drive['lon'])} nodes, {len(drive['targets'])} directed edges")

    city = json.loads((args.site_data / f"cities/{args.city}.json").read_text(encoding="utf-8"))
    centres = gpd.GeoSeries(gpd.points_from_xy([c[0] for c in city["cells"]], [c[1] for c in city["cells"]]), crs="EPSG:4326").to_crs(METRIC_CRS)
    centres_xy = np.column_stack([centres.x, centres.y])
    cell_walk_node, cell_walk_snap = snap(centres_xy, walk)
    cell_drive_node, cell_drive_snap = snap(centres_xy, drive)

    routes = gpd.read_file(args.bus_dir / "bus_routes.geojson").to_crs(METRIC_CRS)
    stops_raw = gpd.read_file(args.bus_dir / "bus_stops.geojson").to_crs(METRIC_CRS)
    excluded = routes["route_long_name"].str.contains(args.exclude_route_regex, regex=True)
    print(f"  excluding {routes.loc[excluded, 'route_short_name'].nunique()} routes matching {args.exclude_route_regex!r}")
    routes = routes[~excluded]
    stops_raw = stops_raw[stops_raw["trip_id"].isin(routes["trip_id"])]
    stops = stops_raw.drop_duplicates("stop_id").reset_index(drop=True)
    stop_index = {sid: i for i, sid in enumerate(stops["stop_id"])}
    stop_walk_node, stop_walk_snap = snap(np.column_stack([stops.geometry.x, stops.geometry.y]), walk)
    hubs = terminal_hubs(stops, args.hub_radius_m)
    stops_wgs = stops.to_crs("EPSG:4326")
    patterns = stop_patterns(routes, stops_raw, stop_index)
    hub_names = {}
    for name, hub in zip(stops["stop_name"], hubs):
        if hub >= 0:
            hub_names.setdefault(hub, []).append(name)
    print(f"  bus: {len(stops)} stops, {len(patterns)} unique stop patterns, {len(hub_names)} terminal hubs")
    for hub, names in sorted(hub_names.items()):
        print(f"    hub {hub}: {len(names)} stops — {names[0]}")

    payload = {
        "schemaVersion": 1,
        "city": args.city,
        "source": {
            "roads": "OpenStreetMap contributors (ODbL), OSMnx walk and drive networks",
            "bus": "Mobilibus / bus2.info project 83 (CMTU Londrina)",
            "busExcludedRoutes": args.exclude_route_regex,
            "osmDownloaded": str(np.datetime64("today")),
        },
        "walk": walk,
        "drive": drive,
        "cells": {
            "walkNode": cell_walk_node, "walkSnapM": cell_walk_snap,
            "driveNode": cell_drive_node, "driveSnapM": cell_drive_snap,
        },
        "stops": {
            "name": stops["stop_name"].tolist(),
            "lon": [round(p.x, 6) for p in stops_wgs.geometry],
            "lat": [round(p.y, 6) for p in stops_wgs.geometry],
            "walkNode": stop_walk_node, "walkSnapM": stop_walk_snap,
            "hub": hubs,
        },
        "patterns": patterns,
    }
    out = output_dir / f"{args.city}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
