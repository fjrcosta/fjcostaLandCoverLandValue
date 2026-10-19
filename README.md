# Deep Learning for Urban Land Cover & Land Value with Mobility and Municipal Economics Analysis

An interactive analytical portal for the Londrina–Maringá urban system in Paraná, Brazil. It integrates urban land-cover classification, predicted unit land value, urban mobility (the transport network and one-hour commute reachability) and aggregated municipal land economics.

**Live portal:** [fjcosta.github.io/fjcostaLandCoverLandValue](https://fjcosta.github.io/fjcostaLandCoverLandValue/)

## Analytical content

- **Urban land cover:** DINOv2 ViT-L/14 + LoRA classification for ten mutually exclusive classes, with classification confidence.
- **Unit land value:** TabPFN v2 configuration 60 predictions for a 450 m² reference parcel, reported in R$/m² as the 10th, 50th and 90th percentiles.
- **Transport network:** OpenStreetMap road geometry grouped into motorway, trunk, primary, secondary and residential classes.
- **Municipal land economics:** municipal polygons coloured by:
  - **LUD (2023/2024):** GVA CS+I per developed urban km² — US$ million/km².
  - **LVY (2023/2024):** GVA CS+I divided by estimated aggregate developed land value — year⁻¹. LVY is a proxy for territorial economic output relative to developed land value, not a financial return rate or cap rate.
- **Multimodal commute reachability (Londrina):** from a location clicked on the map — typically a bare-soil or row-crop patch considered for residential rezoning — the browser computes the one-hour outbound commute (Bertaud's travel-time budget) by walking, car or bus. Industrial land cover serves as a simplified employment proxy; patches beyond reach are dimmed in every active layer.

| Mode | Access | Wait | In-motion speed | Network | Transfer | Egress |
|---|---|---|---|---|---|---|
| Walking | — | — | 5 km/h | OSM pedestrian network | — | — |
| Car | 2 min walk | — | 35 km/h | OSM drive network, one-way streets respected | — | 2 min walk |
| Bus | ≤ 10 min walk to a stop | 10 min | 20 km/h | Official CMTU stop sequences (night "Corujão" lines excluded) | 1 at bus terminals, +10 min wait | ≤ 10 min walk |

  Parameters live in `site/map3d/data/reachability/params.json` and are applied at runtime. Outbound trips only; congestion and timetables are not modelled, and candidate sites connect to the existing network through the nearest node. The bus mode does not fall back to walking — compare modes with the mode selector.

Reference conditions are from 2024; municipal economic aggregates use GVA from 2023 and estimated developed land value from 2024, considering developed categories only.

## Interface

The interface provides independent controls for Land Cover, Land Value, Transport Network, LUD and LVY; municipality, land-cover and road-class filters; regional and 12-municipality views; hover/click inspection of patch predictions; dynamic selected/all-municipality statistics; exact urban patch polygons; urban-perimeter outlines; optional 3D buildings; conventional and satellite basemaps; a municipality tour; coordinate markers with analytical popups; and one-hour commute reachability for Londrina with a per-mode summary of reached and industrial area. The portal is static and requires no backend, database or API key.

LUD and LVY are mutually exclusive municipal-economics views. Selecting either economic layer switches the right-hand panel to the complete 12-municipality comparison; deselecting both returns to the general analytical panel.

## Data representation and architecture

```text
DINOv2–LoRA CSVs ──┐
                    ├─ scripts/build_data.py ── spatial association ── city JSON
TabPFN CSVs ────────┘

city JSON with exact patch vertices ── deck.gl SolidPolygonLayer ── MapLibre scene
OSM Folium HTML ── scripts/build_transport_data.py ── deck.gl PathLayer
municipal economics GeoJSON ── MapLibre fill/outline layers
OSM walk/drive + CMTU bus CSVs ── scripts/build_reachability_data.py ── CSR networks ── in-browser bounded Dijkstra
```

Each patch is stored with its four geographic vertices rather than reconstructed from a regular grid:

```text
[longitude, latitude, value_q50_R$/m², class_index, confidence,
 match_distance_m, normalized_pointwise_interval_width,
 value_q10_R$/m², value_q90_R$/m², polygon]
```

`polygon` contains the exact four `[longitude, latitude]` vertices in top-left, top-right, bottom-right, bottom-left order. The current model-output manifest records schema version 4, EPSG:4326 web coordinates, source CRS EPSG:29192, a 109.45 m grid, data year 2024, configuration 60, a 450 m² reference parcel and 73,166 cells across 12 municipalities.

## Local preview

No JavaScript build step is required:

```bash
cd /Volumes/ssd_externo/northern-parana-urban-twin
python3 -m http.server 8000 --directory site
```

Open [http://localhost:8000](http://localhost:8000). Opening the HTML directly with a `file://` URL can block JSON requests.

## Regenerating data products

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
```

Build the land-cover/land-value association:

```bash
python3 scripts/build_data.py \
  --land-cover-dir raw/land_cover \
  --land-value-dir raw/land_value \
  --land-value-pattern 'inferencia_*_cfg60_450m2.csv' \
  --output-dir site/map3d/data \
  --utm-crs EPSG:29192 \
  --grid-size-m 109.45
```

Land-cover files must provide `predicted_class`, `prediction_confidence` and either `center` or patch-corner fields. Land-value files must provide `utm_x`, `utm_y`, `unit_q10`, `unit_q50`, `unit_q90`, `pinaw_pontual`, `configuracao` and `area_m2`. The converter checks configuration 60 and the 450 m² reference parcel.

Enrich exact patch geometry, build transport data, generate economics and validate:

```bash
python3 scripts/enrich_patch_geometry.py
python3 scripts/build_transport_data.py \
  --source-html /path/to/LandCover_DINO_TransportStructure.html \
  --output-dir site/map3d/data/transport \
  --snapshot 2025-12-28
python3 scripts/build_economics_data.py
python3 scripts/build_reachability_data.py \
  --site-data site/map3d/data \
  --bus-dir /path/to/transportLondrina/arquivos \
  --city londrina \
  --perimeter-buffer-m 500 \
  --hub-radius-m 250 \
  --exclude-route-regex '^Corujão'
python3 scripts/validate_site.py
```

`build_reachability_data.py` downloads the OSM walk and drive networks through OSMnx (Overpass), flattens them to CSR arrays, snaps every Londrina cell and bus stop to its nearest node, groups terminal platforms into transfer hubs and turns bus trips into ordered stop patterns with cumulative on-route distance. It must be rerun whenever the Londrina cells change.

A headless browser smoke test exercises every control and reports JavaScript errors:

```bash
python3 -m playwright install chromium
python3 -m http.server 8765 --directory site &
python3 scripts/smoke_test.py --url http://localhost:8765 --with-reach
```

## Publish with GitHub Pages

The repository is [github.com/fjcosta/fjcostaLandCoverLandValue](https://github.com/fjcosta/fjcostaLandCoverLandValue). `.github/workflows/deploy-pages.yml` publishes `site/` after pushes to `main`.

```bash
git add README.md site scripts
git commit -m "Update portal documentation"
git push origin main
```

## Scientific interpretation

This viewer is an exploratory analytical and communication instrument, not a cadastral, photogrammetric or building-height model. Prism extrusion is a visual encoding of predicted unit land value, not physical elevation. Unit values are model predictions for the 450 m² reference parcel; quantiles and normalized pointwise interval width describe predictive distributions and uncertainty, not observed transactions.

Exact patch polygons preserve source geometry, while match distance documents the association between land-cover and land-value products. LUD and LVY summarize municipal conditions over developed urban areas. LVY is a territorial economic-output proxy, not a land rent, investment yield or capitalization rate. Visual associations should not be read as causal relationships or substitutes for parcel-specific appraisal.

## Main files

```text
site/index.html                         Portal landing page
site/map3d/index.html                   Interactive map shell
site/map3d/assets/app.js                Map layers, controls and statistics
site/map3d/assets/styles.css            Responsive visual design
site/map3d/data/manifest.json           Dataset metadata and city index
site/map3d/data/cities/*.json           Exact patch-level analytical records
site/map3d/data/transport/              OSM transport manifest and city roads
site/map3d/data/economics/              Municipal LUD/LVY GeoJSON
site/map3d/assets/reachability.js       In-browser walk/car/bus reachability
site/map3d/data/reachability/           Londrina networks, bus patterns and params.json
scripts/build_data.py                   CSV-to-web conversion
scripts/enrich_patch_geometry.py        Exact patch-vertex enrichment
scripts/build_transport_data.py         OSM hierarchy extraction
scripts/build_economics_data.py         Municipal economics generation
scripts/build_reachability_data.py      Reachability network preprocessing
scripts/smoke_test.py                   Headless browser smoke test
scripts/validate_site.py                Schema and geometry validation
.github/workflows/deploy-pages.yml      GitHub Pages deployment
```

## Licensing and attribution

Application code is released under the MIT License. Transportation-network data are © OpenStreetMap contributors and used under the Open Database License (ODbL); the reachability networks were downloaded on 19 October 2026. Bus routes and stops are from the 2025 CMTU Londrina network, as published via Mobilibus (bus2.info), extracted on 23 February 2026 for non-commercial academic research. Model outputs, imagery and other research data retain their original licences and attribution requirements.
