// One-hour reachability on precomputed Londrina networks.
// Every function returns travel times in seconds; Infinity means unreachable.

const KMH_TO_MS = 1 / 3.6;

class MinHeap {
  constructor() {
    this.nodes = [];
    this.keys = [];
  }

  push(node, key) {
    const { nodes, keys } = this;
    let i = nodes.length;
    nodes.push(node);
    keys.push(key);
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (keys[parent] <= key) break;
      nodes[i] = nodes[parent];
      keys[i] = keys[parent];
      i = parent;
    }
    nodes[i] = node;
    keys[i] = key;
  }

  pop() {
    const { nodes, keys } = this;
    const top = nodes[0];
    const topKey = keys[0];
    const lastNode = nodes.pop();
    const lastKey = keys.pop();
    if (nodes.length) {
      let i = 0;
      const n = nodes.length;
      while (true) {
        let child = 2 * i + 1;
        if (child >= n) break;
        if (child + 1 < n && keys[child + 1] < keys[child]) child += 1;
        if (keys[child] >= lastKey) break;
        nodes[i] = nodes[child];
        keys[i] = keys[child];
        i = child;
      }
      nodes[i] = lastNode;
      keys[i] = lastKey;
    }
    return [top, topKey];
  }

  get size() {
    return this.nodes.length;
  }
}

function toGraph(raw) {
  return {
    lon: Float64Array.from(raw.lon),
    lat: Float64Array.from(raw.lat),
    offsets: Int32Array.from(raw.offsets),
    targets: Int32Array.from(raw.targets),
    lengths: Float32Array.from(raw.lengths)
  };
}

export function prepareNetwork(raw) {
  return {
    walk: toGraph(raw.walk),
    drive: toGraph(raw.drive),
    cells: {
      walkNode: Int32Array.from(raw.cells.walkNode),
      walkSnapM: Float32Array.from(raw.cells.walkSnapM),
      driveNode: Int32Array.from(raw.cells.driveNode)
    },
    stops: {
      name: raw.stops.name,
      walkNode: Int32Array.from(raw.stops.walkNode),
      walkSnapM: Float32Array.from(raw.stops.walkSnapM),
      hub: Int32Array.from(raw.stops.hub)
    },
    patterns: raw.patterns.map(p => ({ ...p, stops: Int32Array.from(p.stops), cum: Float64Array.from(p.cum) })),
    egressCache: new Map()
  };
}

// Equirectangular metres are accurate enough for snapping inside one city.
function nearestNode(graph, lon, lat) {
  const kx = 111320 * Math.cos(lat * Math.PI / 180);
  const ky = 110540;
  let best = -1;
  let bestD2 = Infinity;
  for (let i = 0; i < graph.lon.length; i++) {
    const dx = (graph.lon[i] - lon) * kx;
    const dy = (graph.lat[i] - lat) * ky;
    const d2 = dx * dx + dy * dy;
    if (d2 < bestD2) {
      bestD2 = d2;
      best = i;
    }
  }
  return { node: best, distanceM: Math.sqrt(bestD2) };
}

// Bounded Dijkstra; sources are [node, startSeconds] pairs.
function dijkstra(graph, sources, speedMs, cutoffSec) {
  const times = new Float64Array(graph.offsets.length - 1).fill(Infinity);
  const heap = new MinHeap();
  sources.forEach(([node, t]) => {
    if (t <= cutoffSec && t < times[node]) {
      times[node] = t;
      heap.push(node, t);
    }
  });
  while (heap.size) {
    const [u, t] = heap.pop();
    if (t > times[u]) continue;
    for (let e = graph.offsets[u]; e < graph.offsets[u + 1]; e++) {
      const v = graph.targets[e];
      const tv = t + graph.lengths[e] / speedMs;
      if (tv <= cutoffSec && tv < times[v]) {
        times[v] = tv;
        heap.push(v, tv);
      }
    }
  }
  return times;
}

function walkCellTimes(net, nodeTimes, walkSpeedMs) {
  const { walkNode, walkSnapM } = net.cells;
  const out = new Float64Array(walkNode.length);
  for (let i = 0; i < walkNode.length; i++) out[i] = nodeTimes[walkNode[i]] + walkSnapM[i] / walkSpeedMs;
  return out;
}

export function reachWalk(net, params, lon, lat) {
  const speed = params.walk.speedKmh * KMH_TO_MS;
  const budget = params.budgetMin * 60;
  const origin = nearestNode(net.walk, lon, lat);
  const nodeTimes = dijkstra(net.walk, [[origin.node, origin.distanceM / speed]], speed, budget);
  return walkCellTimes(net, nodeTimes, speed);
}

export function reachCar(net, params, lon, lat) {
  const { speedKmh, walkToCarMin, parkAndWalkMin } = params.car;
  const budget = params.budgetMin * 60;
  const origin = nearestNode(net.drive, lon, lat);
  const nodeTimes = dijkstra(net.drive, [[origin.node, walkToCarMin * 60]], speedKmh * KMH_TO_MS, budget - parkAndWalkMin * 60);
  const { driveNode } = net.cells;
  const out = new Float64Array(driveNode.length);
  for (let i = 0; i < driveNode.length; i++) out[i] = nodeTimes[driveNode[i]] + parkAndWalkMin * 60;
  return out;
}

// Ride every stop pattern once: boarding at position i, alighting at any later k.
function scanPatterns(net, boardTimes, busSpeedMs, arrivals) {
  net.patterns.forEach(pattern => {
    let best = Infinity;
    for (let k = 0; k < pattern.stops.length; k++) {
      const stop = pattern.stops[k];
      const rideOffset = pattern.cum[k] / busSpeedMs;
      if (best < Infinity && best + rideOffset < arrivals[stop]) arrivals[stop] = best + rideOffset;
      const board = boardTimes[stop] - rideOffset;
      if (board < best) best = board;
    }
  });
}

// Walk-node times from one stop within the egress limit; origin-independent, so cached.
function egressFromStop(net, stop, walkSpeedMs, maxEgressSec) {
  let entry = net.egressCache.get(stop);
  if (!entry) {
    const times = dijkstra(net.walk, [[net.stops.walkNode[stop], net.stops.walkSnapM[stop] / walkSpeedMs]], walkSpeedMs, maxEgressSec);
    const nodes = [];
    const secs = [];
    times.forEach((t, node) => {
      if (t < Infinity) {
        nodes.push(node);
        secs.push(t);
      }
    });
    entry = { nodes: Int32Array.from(nodes), secs: Float64Array.from(secs) };
    net.egressCache.set(stop, entry);
  }
  return entry;
}

export function reachBus(net, params, lon, lat) {
  const p = params.bus;
  const budget = params.budgetMin * 60;
  const walkSpeed = p.walkSpeedKmh * KMH_TO_MS;
  const busSpeed = p.speedKmh * KMH_TO_MS;
  const nStops = net.stops.walkNode.length;

  const origin = nearestNode(net.walk, lon, lat);
  const access = dijkstra(net.walk, [[origin.node, origin.distanceM / walkSpeed]], walkSpeed, p.maxAccessWalkMin * 60);

  const board = new Float64Array(nStops).fill(Infinity);
  for (let s = 0; s < nStops; s++) {
    const walkSec = access[net.stops.walkNode[s]] + net.stops.walkSnapM[s] / walkSpeed;
    if (walkSec <= p.maxAccessWalkMin * 60) board[s] = walkSec + p.waitMin * 60;
  }
  const arrivals = new Float64Array(nStops).fill(Infinity);
  scanPatterns(net, board, busSpeed, arrivals);

  // One transfer, only inside terminal hubs, paying a second wait.
  const hubArrival = new Map();
  for (let s = 0; s < nStops; s++) {
    const hub = net.stops.hub[s];
    if (hub >= 0 && arrivals[s] < (hubArrival.get(hub) ?? Infinity)) hubArrival.set(hub, arrivals[s]);
  }
  const transferBoard = new Float64Array(nStops).fill(Infinity);
  for (let s = 0; s < nStops; s++) {
    const hub = net.stops.hub[s];
    if (hub >= 0 && hubArrival.has(hub)) transferBoard[s] = hubArrival.get(hub) + p.terminalTransferWaitMin * 60;
  }
  scanPatterns(net, transferBoard, busSpeed, arrivals);

  const nodeTimes = Float64Array.from(access);
  const maxEgressSec = p.maxEgressWalkMin * 60;
  for (let s = 0; s < nStops; s++) {
    if (arrivals[s] >= budget) continue;
    const { nodes, secs } = egressFromStop(net, s, walkSpeed, maxEgressSec);
    for (let i = 0; i < nodes.length; i++) {
      const t = arrivals[s] + secs[i];
      if (t <= budget && t < nodeTimes[nodes[i]]) nodeTimes[nodes[i]] = t;
    }
  }
  const cellTimes = walkCellTimes(net, nodeTimes, walkSpeed);
  // The off-network walk from the nearest node to the cell centre is added on top of the egress limit.
  for (let i = 0; i < cellTimes.length; i++) if (cellTimes[i] > budget) cellTimes[i] = Infinity;
  return cellTimes;
}
