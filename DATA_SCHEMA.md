# Web data schema

## `site/map3d/data/manifest.json`

The manifest records dataset status, class definitions, global statistics and one entry per city. Schema version 4 includes the lower, median and upper predictive quantiles, the normalized pointwise predictive-interval width and the exact patch polygon for every cell.

Important fields:

- `datasetMode`: `demo` or `model-output`.
- `gridSizeM`: nominal side length of each rendered cell.
- `dataYear`: year represented by the published data.
- `modelConfiguration`: TabPFN feature configuration used for inference (`60`).
- `referenceParcelAreaM2`: reference parcel area used for inference (`450`).
- `classes`: ordered class definitions. The array position is the class index used by each cell.
- `cities[].file`: path to the compact city JSON.

## City files

Each city file contains metadata, statistics and a `cells` array. Each cell is a positional tuple:

```text
index  meaning
0      longitude, EPSG:4326
1      latitude, EPSG:4326
2      predicted median unit land value, R$/m²
3      urban land-cover class index
4      DINOv2–LoRA classification confidence, 0–1
5      nearest-neighbour association distance, metres
6      normalized pointwise predictive-interval width, w_i* = w_i / R
7      predicted 10th quantile of unit land value, R$/m²
8      predicted 90th quantile of unit land value, R$/m²
9      exact patch polygon, four [longitude, latitude] vertices (TL, TR, BR, BL)
```

The browser appends a transient eleventh element (index 10) containing the city index. It is not stored in the source JSON.

## Transportation-network data

`site/map3d/data/transport/manifest.json` records the five displayed
OpenStreetMap `highway` classes, styling, source, ODbL licence, snapshot date,
city file index and segment counts. Transportation schema version 1 is
independent of the analytical-cell schema.

Each file under `site/map3d/data/transport/cities/` contains a compact `roads`
array. Every road is represented as:

```text
index  meaning
0      transport-class index from the transport manifest
1      LineString path as [[longitude, latitude], ...], EPSG:4326
```

The preprocessing script removes duplicate directed OSM graph geometries within
each municipality, treating a path and the same path in reverse order as one
rendered segment.

## Commute reachability data

`site/map3d/data/reachability/params.json` holds the travel-time parameters
(`budgetMin`; `walk.speedKmh`; `car.speedKmh`, `walkToCarMin`, `parkAndWalkMin`;
`bus.speedKmh`, `walkSpeedKmh`, `maxAccessWalkMin`, `waitMin`,
`terminalTransferWaitMin`, `maxEgressWalkMin`). They are applied in the browser,
so editing them requires no rebuild.

`site/map3d/data/reachability/<city>.json` (schema version 1) contains:

- `walk`, `drive`: directed graphs in CSR form — `lon`, `lat` (n nodes),
  `offsets` (n + 1), `targets` and `lengths` in metres (m edges). The walk graph
  stores both directions; the drive graph respects one-way streets.
- `cells`: per analytical cell, in the order of `cities/<city>.json`, the nearest
  walk and drive node (`walkNode`, `driveNode`) and the straight-line snap
  distance in metres (`walkSnapM`, `driveSnapM`).
- `stops`: unique bus stops — `name`, `lon`, `lat`, nearest walk node, snap
  distance and terminal `hub` index (-1 for ordinary stops).
- `patterns`: unique ordered stop sequences — `route`, `name`, `color`, `stops`
  (stop indices) and `cum` (non-decreasing on-route distance in metres).

Reachability data are tied to the city cell order: regenerate them whenever the
city file changes. `validate_site.py` checks array lengths, node references and
pattern distances.
