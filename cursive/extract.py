"""Turn outline font glyphs into ordered single-line pen strokes.

Pipeline: render -> skeletonize -> skeleton graph -> clean (merge junction
clusters, prune spurs) -> choose a pen traversal per connected component
-> normalise to x-height units (baseline y=0, x-height y=1, y up).

The output is a draft. Glyph JSON files can be hand-tuned afterwards.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

import freetype
import numpy as np
from scipy import ndimage
from skan import Skeleton
from skimage.morphology import skeletonize

from . import geometry as g

XH_PX = 220  # x-height in pixels when rasterising


# ---------------------------------------------------------------- rendering


def font_xheight_units(face: freetype.Face) -> float:
    """x-height in font units: measured from the flat top of 'x' / 'u' / 'v'."""
    face.set_char_size(face.units_per_EM * 64)
    heights = []
    for ch in "xzuvw":
        face.load_char(ch, freetype.FT_LOAD_NO_SCALE | freetype.FT_LOAD_NO_HINTING)
        pts = np.array(face.glyph.outline.points, dtype=float)
        if len(pts):
            heights.append(np.percentile(pts[:, 1], 90))
    return float(np.median(heights))


def font_slant(face: freetype.Face, xh_units: float) -> float:
    """Measure slant as dx/dy from the ascender strokes of l, h, d, k, b."""
    ks = []
    for ch in "lhdkb":
        img, orow, ocol, _, _ = render(face, ch, xh_units)
        rows, cols = np.nonzero(skeletonize(img))
        y = (orow - rows) / XH_PX
        x = (cols - ocol) / XH_PX
        m = (y > 1.15) & (y < 2.0)
        if m.sum() < 20:
            continue
        # robust-ish fit x = a + k*y on the ascender band, keep the steepest cluster
        k = np.polyfit(y[m], x[m], 1)[0]
        ks.append(k)
    return float(np.median(ks)) if ks else 0.0


def render(face: freetype.Face, char: str, xh_units: float, glyph_name: str | None = None):
    """Return (bool bitmap, origin_row, origin_col, advance_px, px_per_unit).

    `glyph_name` renders a named glyph (e.g. "e.fina") instead of `char`.
    """
    px_per_unit = XH_PX / xh_units
    size_px = face.units_per_EM * px_per_unit
    face.set_char_size(int(round(size_px * 64)))
    flags = freetype.FT_LOAD_RENDER | freetype.FT_LOAD_NO_HINTING
    if glyph_name:
        idx = face.get_name_index(glyph_name.encode())
        if not idx:
            raise KeyError(f"no glyph named {glyph_name!r} in font")
        face.load_glyph(idx, flags)
    else:
        face.load_char(char, flags)
    gl = face.glyph
    bm = gl.bitmap
    arr = np.array(bm.buffer, dtype=np.uint8).reshape(bm.rows, bm.pitch)[:, : bm.width]
    pad = 8
    img = np.pad(arr > 110, pad)
    origin_row = gl.bitmap_top + pad  # row index of the baseline
    origin_col = -gl.bitmap_left + pad  # col index of x=0
    advance_px = gl.advance.x / 64.0
    return img, origin_row, origin_col, advance_px, px_per_unit


# ------------------------------------------------------------ skeleton graph


@dataclass(eq=False)
class Edge:
    u: int
    v: int
    pts: np.ndarray  # (N,2) in pixel-space xy, from u to v
    alive: bool = True

    @property
    def length(self) -> float:
        return g.length(self.pts)


@dataclass
class Graph:
    pos: dict[int, np.ndarray] = field(default_factory=dict)
    radius: dict[int, float] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def live(self):
        return [e for e in self.edges if e.alive]

    def degree(self, n: int) -> int:
        d = 0
        for e in self.live():
            d += (e.u == n) + (e.v == n)
        return d


def build_graph(img: np.ndarray) -> tuple[Graph, np.ndarray]:
    dt = ndimage.distance_transform_edt(img)
    skel = skeletonize(img)
    G = Graph()
    if skel.sum() == 0:
        return G, dt
    sk = Skeleton(skel)

    def xy(rc):
        rc = np.asarray(rc, float)
        return np.column_stack([rc[:, 1], rc[:, 0]])  # (x=col, y=row) in px

    for i in range(sk.n_paths):
        idx = sk.path(i)
        coords = sk.path_coordinates(i)
        u, v = int(idx[0]), int(idx[-1])
        for n, rc in ((u, coords[0]), (v, coords[-1])):
            if n not in G.pos:
                G.pos[n] = xy([rc])[0]
                G.radius[n] = float(dt[int(rc[0]), int(rc[1])])
        G.edges.append(Edge(u, v, xy(coords)))
    return G, dt


def _contract(G: Graph, keep: int, drop: int):
    for e in G.live():
        if e.u == drop:
            e.u = keep
        if e.v == drop:
            e.v = keep
    G.radius[keep] = max(G.radius[keep], G.radius[drop])


def clean_graph(G: Graph, base_r: float) -> Graph:
    """Merge junction clusters, prune spurs, fuse degree-2 chains."""
    for _ in range(50):
        changed = False
        # 1. contract very short edges between distinct nodes (junction clusters)
        for e in sorted(G.live(), key=lambda e: e.length):
            if not e.alive or e.u == e.v:
                continue
            r = max(G.radius[e.u], G.radius[e.v], base_r)
            if e.length < 1.1 * r and G.degree(e.u) > 1 and G.degree(e.v) > 1:
                e.alive = False
                keep, drop = e.u, e.v
                G.pos[keep] = 0.5 * (G.pos[keep] + G.pos[drop])
                _contract(G, keep, drop)
                changed = True
        # 2. prune short spurs (terminal edges hanging off junctions)
        spurs = []
        for e in G.live():
            if e.u == e.v:
                continue
            du, dv = G.degree(e.u), G.degree(e.v)
            junction = e.u if dv == 1 else e.v
            if min(du, dv) == 1 and max(du, dv) >= 3:
                r = max(G.radius[junction], base_r)
                if e.length < 1.6 * r:
                    spurs.append(e)
        for e in spurs:
            e.alive = False
            changed = True
        # 3. fuse chains through degree-2 nodes
        for n in list(G.pos):
            inc = [e for e in G.live() if n in (e.u, e.v)]
            if len(inc) == 2 and inc[0] is not inc[1] and all(e.u != e.v for e in inc):
                a, b = inc
                pa = a.pts if a.v == n else a.pts[::-1]
                ua = a.u if a.v == n else a.v
                pb = b.pts if b.u == n else b.pts[::-1]
                vb = b.v if b.u == n else b.u
                a.alive = b.alive = False
                G.edges.append(Edge(ua, vb, np.vstack([pa, pb[1:]])))
                changed = True
        if not changed:
            break
    # snap edge endpoints to (possibly moved) node positions
    for e in G.live():
        e.pts = e.pts.copy()
        e.pts[0] = G.pos[e.u]
        e.pts[-1] = G.pos[e.v]
    return G


def merge_bars(bars: list[np.ndarray], tol: float = 0.15) -> list[np.ndarray]:
    """Merge bar pieces at about the same height (the two halves either side of
    a stem) into single straight bars drawn left to right."""
    groups: list[list[np.ndarray]] = []
    for b in sorted(bars, key=lambda b: float(b[:, 1].mean())):
        if groups and abs(float(b[:, 1].mean()) - float(groups[-1][0][:, 1].mean())) < tol:
            groups[-1].append(b)
        else:
            groups.append([b])
    out = []
    for grp in groups:
        pts = np.vstack(grp)
        left, right = pts[np.argmin(pts[:, 0])], pts[np.argmax(pts[:, 0])]
        out.append(np.round(np.linspace(left, right, 6), 4))
    return out


def split_bars(G: Graph, orow: float, slant: float) -> list[np.ndarray]:
    """Detach crossbars (t, f...) from the skeleton and return them as polylines.

    A bar is one or two short, straight, near-horizontal terminal edges meeting
    at a junction high on the letter. They are removed from the graph and
    returned joined left-to-right, to be drawn after the word.
    """
    def is_bar(e: Edge, junction: int) -> bool:
        chord = e.pts[-1] - e.pts[0]
        L = e.length
        if L < 0.08 * XH_PX or L > 1.6 * XH_PX:
            return False
        if np.linalg.norm(chord) < 0.85 * L:
            return False
        if abs(chord[1]) > 0.45 * abs(chord[0]):  # within ~24 degrees of horizontal
            return False
        return (orow - G.pos[junction][1]) / XH_PX > 0.55

    by_junction: dict[int, list[tuple[Edge, np.ndarray]]] = {}
    for e in G.live():
        if e.u == e.v:
            continue
        du, dv = G.degree(e.u), G.degree(e.v)
        if min(du, dv) != 1 or max(du, dv) < 3:
            continue
        j = e.u if du >= 3 else e.v
        if is_bar(e, j):
            pts = e.pts if e.u == j else e.pts[::-1]  # oriented junction -> tip
            by_junction.setdefault(j, []).append((e, pts))
    out = []
    for j, cand in by_junction.items():
        left = [c for c in cand if c[1][-1, 0] < c[1][0, 0]]
        right = [c for c in cand if c[1][-1, 0] >= c[1][0, 0]]
        pick_l = max(left, key=lambda c: c[0].length) if left else None
        pick_r = max(right, key=lambda c: c[0].length) if right else None
        # a lone one-sided "bar" is only accepted if it is clearly long
        if not (pick_l and pick_r):
            only = pick_l or pick_r
            if only[0].length < 0.25 * XH_PX:
                continue
        pieces = []
        if pick_l:
            pieces.append(pick_l[1][::-1])
            pick_l[0].alive = False
        if pick_r:
            pieces.append(pick_r[1] if not pieces else pick_r[1][1:])
            pick_r[0].alive = False
        out.append(np.vstack(pieces))
    return out


# ---------------------------------------------------------------- traversal


def _components(G: Graph) -> list[list[Edge]]:
    edges = G.live()
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        parent[find(e.u)] = find(e.v)
    comps: dict[int, list[Edge]] = {}
    for e in edges:
        comps.setdefault(find(e.u), []).append(e)
    return list(comps.values())


def _oriented(e: Edge, start: int) -> np.ndarray:
    return e.pts if e.u == start else e.pts[::-1]


def _shortest(comp, src, targets, nodes):
    """Dijkstra over component edges; returns {target: [oriented pts,...]}."""
    adj: dict[int, list] = {n: [] for n in nodes}
    for e in comp:
        adj[e.u].append((e.length, e.v, e.pts))
        adj[e.v].append((e.length, e.u, e.pts[::-1]))
    dist = {src: 0.0}
    prev = {}
    pq = [(0.0, src)]
    while pq:
        d, n = heapq.heappop(pq)
        if d > dist.get(n, 1e18):
            continue
        for w, m, p in adj[n]:
            nd = d + w
            if nd < dist.get(m, 1e18):
                dist[m] = nd
                prev[m] = (n, p)
                heapq.heappush(pq, (nd, m))
    routes = {}
    for t in targets:
        if t == src or t not in prev:
            continue
        route, n = [], t
        while n in prev:
            n0, p = prev[n]
            route.append(p)
            n = n0
        routes[t] = route[::-1]
    return routes


def _widths(pts: np.ndarray, dt: np.ndarray) -> np.ndarray:
    r = np.clip(np.round(pts[:, 1]).astype(int), 0, dt.shape[0] - 1)
    c = np.clip(np.round(pts[:, 0]).astype(int), 0, dt.shape[1] - 1)
    return dt[r, c]


def _greedy_walk(G: Graph, comp: list[Edge], start: int, look: float, nodes) -> list[np.ndarray]:
    """Cover every edge: straightest continuation at junctions, retracing to the
    nearest unfinished node when stuck. Always completes."""
    unused = set(range(len(comp)))
    segs: list[np.ndarray] = []
    cur, d_in = start, None
    while unused:
        cands = []
        for k in unused:
            e = comp[k]
            if e.u == cur:
                cands.append((k, e.pts))
            if e.v == cur:
                cands.append((k, e.pts[::-1]))
        if cands:
            k, pts = min(cands, key=lambda c: 0.0 if d_in is None
                         else g.turn_angle(d_in, g.start_tangent(c[1], look)))
            unused.discard(k)
            segs.append(pts)
            d_in = g.end_tangent(pts, look)
            e = comp[k]
            cur = e.v if (e.u == cur and pts is e.pts) or e.u == e.v else e.u
            continue
        want = {comp[k].u for k in unused} | {comp[k].v for k in unused}
        routes = _shortest(comp, cur, want, set(nodes))
        if not routes:
            break
        t, route = min(routes.items(), key=lambda tr: sum(g.length(p) for p in tr[1]))
        segs.extend(route)
        d_in = g.end_tangent(route[-1], look)
        cur = t
    return segs


TURN_W = 0.5  # cost per radian^2 of turning at a junction
RETRACE_W = 1.0  # cost per x-height of retraced (doubled) line
REVERSAL = TURN_W * np.pi**2  # a retrace starts by reversing direction


THICK_W = 3.0  # cost per x-height of travelling *up* a thick (shaded) stroke


def best_traversal(G: Graph, comp: list[Edge], look: float, bbox, deslant, height,
                   start_hint=None, dt: np.ndarray | None = None) -> np.ndarray:
    """Find the cheapest pen walk that covers every edge of a skeleton component.

    Exhaustive memoised search. Cost = turning at junctions (straight-through
    is cheap) + retracing + penalties for starting anywhere but the left of
    the body band or finishing anywhere but the right. `height(pt)` gives y in
    x-height units; `start_hint` (pixel xy) forces the start node.
    """
    nodes = sorted({e.u for e in comp} | {e.v for e in comp})
    deg = {n: sum((e.u == n) + (e.v == n) for e in comp) for n in nodes}
    x0, x1 = bbox
    width = max(x1 - x0, 1.0)
    idx = {id(e): k for k, e in enumerate(comp)}
    # orientations: (edge k, from node, pts, out_dir, in_dir_at_end, to node)
    # pointed-pen scripts are thick going down and hairline going up, so
    # climbing a thick stroke is (nearly always) the wrong pen direction
    if dt is not None:
        allw = np.concatenate([_widths(e.pts, dt) for e in comp])
        w_thin, w_thick = np.percentile(allw, 15), np.percentile(allw, 90)
    def up_thick(pts):
        if dt is None or w_thick - w_thin < 0.5:
            return 0.0
        w = _widths(pts, dt)
        thick = np.clip((w - w_thin) / (w_thick - w_thin), 0, 1)
        up = np.clip(-np.diff(pts[:, 1]), 0, None)  # pixel rows: upward is negative
        return float(np.sum(up * 0.5 * (thick[1:] + thick[:-1]))) / XH_PX

    ors: dict[int, list] = {n: [] for n in nodes}
    for k, e in enumerate(comp):
        for pts, a, b in ((e.pts, e.u, e.v), (e.pts[::-1], e.v, e.u)):
            o = (k, a, pts, g.start_tangent(pts, look), g.end_tangent(pts, look), b,
                 THICK_W * up_thick(pts))
            ors[a].append(o)

    def start_cost(n):
        pt = G.pos[n]
        ys = height(pt)
        return 6.0 * (deslant(pt) - x0) / width + 4.0 * (ys > 1.4) + 10.0 * (ys < -0.25)

    def end_cost(n):
        pt = G.pos[n]
        ye = height(pt)
        return 6.0 * (x1 - deslant(pt)) / width + 5.0 * (ye > 1.4) + 10.0 * (ye < -0.15)

    memo: dict = {}
    retrace_cache: dict = {}
    MAX_STATES = 60000  # beyond this, fall back to greedy choices (ornate capitals)

    def routes_from(n):
        if n not in retrace_cache:
            retrace_cache[n] = _shortest(comp, n, set(nodes), set(nodes))
        return retrace_cache[n]

    def search(cur, d_in, in_key, unused: frozenset, budget: int):
        """Return (cost, [segments]) to finish from `cur` with `unused` edges left."""
        if not unused:
            return end_cost(cur), []
        key = (cur, in_key, unused)
        if key in memo:
            return memo[key]
        best = (float("inf"), [])
        incident = [o for o in ors[cur] if o[0] in unused]
        greedy = len(memo) > MAX_STATES
        if greedy and d_in is not None and len(incident) > 1:
            incident = [min(incident, key=lambda o: g.turn_angle(d_in, o[3]))]
        elif len(comp) > 10 and d_in is not None and len(incident) > 1:
            # big graphs (ornate capitals): only explore the straightest options
            incident.sort(key=lambda o: g.turn_angle(d_in, o[3]))
            incident = incident[: 1 if len(comp) > 16 else 2]
        for k, _, pts, out, arr, nxt, thick_cost in incident:
            turn = 0.0 if d_in is None else g.turn_angle(d_in, out)
            c, segs = search(nxt, arr, (k, nxt), unused - {k}, budget)
            c += TURN_W * turn**2 + thick_cost
            if c < best[0]:
                best = (c, [pts] + segs)
        if not incident and budget > 0:
            want = {o[1] for n in nodes for o in ors[n] if o[0] in unused}
            cands = [(t, r) for t, r in routes_from(cur).items() if t in want]
            if greedy or len(comp) > 10:
                cands.sort(key=lambda tr: sum(g.length(p) for p in tr[1]))
                cands = cands[: 1 if greedy else 2]
            for t, route in cands:
                L = sum(g.length(p) for p in route) / XH_PX
                arr = g.end_tangent(route[-1], look)
                c, segs = search(t, arr, ("r", t), unused, budget - 1)
                c += RETRACE_W * L + REVERSAL + THICK_W * sum(up_thick(p) for p in route)
                if c < best[0]:
                    best = (c, route + segs)
        memo[key] = best
        return best

    all_edges = frozenset(range(len(comp)))
    starts = [n for n in nodes if deg[n] % 2 == 1] or list(nodes)
    if start_hint is not None:
        starts = [min(nodes, key=lambda n: np.linalg.norm(G.pos[n] - start_hint))]
    best = None
    for s0 in starts:
        c, segs = search(s0, None, None, all_edges, budget=4)
        c += start_cost(s0)
        if segs and (best is None or c < best[0]):
            best = (c, segs)
    if best is None or not np.isfinite(best[0]):
        # search gave up (very ornate glyph): greedy walk that always covers everything
        s0 = min(starts, key=start_cost)
        segs = _greedy_walk(G, comp, s0, look, nodes)
    else:
        segs = best[1]
    return np.vstack([segs[0]] + [p[1:] for p in segs[1:]])


# ------------------------------------------------------------------- glyphs


def _dot(center, r, n=14) -> np.ndarray:
    """A small closed spiral that reads as a dot when plotted."""
    t = np.linspace(0, 2 * np.pi * 1.5, n * 2)
    rr = r * (0.35 + 0.65 * t / t[-1])
    return np.column_stack([center[0] + rr * np.cos(t), center[1] + rr * np.sin(t)])


def extract_glyph(face: freetype.Face, char: str, xh_units: float, slant: float = 0.0,
                  hint: dict | None = None, glyph_name: str | None = None) -> dict | None:
    img, orow, ocol, adv_px, _ = render(face, char, xh_units, glyph_name)
    if img.sum() == 0:
        return None
    # small blobs (dots of i, j, '.', ':') become plotted dots, not skeletons
    labels, n_lab = ndimage.label(img)
    dots = []
    for k, sl in enumerate(ndimage.find_objects(labels), start=1):
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if max(h, w) < 0.3 * XH_PX:
            ys, xs = np.nonzero(labels[sl] == k)
            c = np.array([xs.mean() + sl[1].start, ys.mean() + sl[0].start])
            dots.append((c, max(h, w) / 2))
            img = img & (labels != k)
    if img.sum() == 0 and not dots:
        return None
    G, dt = build_graph(img) if img.sum() else (Graph(), ndimage.distance_transform_edt(img))
    on_skel = dt[skeletonize(img)]
    base_r = float(np.percentile(on_skel, 30)) if len(on_skel) else 2.0
    G = clean_graph(G, base_r)
    bars = []
    if hint and hint.get("bar"):
        bars = split_bars(G, orow, slant)
        if bars:
            G = clean_graph(G, base_r)
    comps = _components(G)

    def to_units(p):
        p = np.asarray(p, float)
        return np.column_stack([(p[:, 0] - ocol) / XH_PX, (orow - p[:, 1]) / XH_PX])

    def deslant(pt):  # pixel xy -> x with the font's slant removed
        return pt[0] - slant * (orow - pt[1])

    sk_rows, sk_cols = np.nonzero(img)
    dx = sk_cols - slant * (orow - sk_rows)
    bbox = (float(dx.min()), float(dx.max())) if len(dx) else (0.0, 1.0)
    look = max(3.0 * base_r, 10.0)
    strokes = []
    for b in merge_bars([to_units(b) for b in bars]):
        strokes.append({"points": b, "deferred": True, "kind": "line", "_len": 0.0})
    for c, r in dots:
        cu = to_units(c[None])[0]
        strokes.append({"points": _dot(cu, min(r / XH_PX * 0.6, 0.06)), "deferred": True,
                        "kind": "dot", "_len": 0.0})
    for comp in comps:
        total = sum(e.length for e in comp)
        allpts = np.vstack([e.pts for e in comp])
        extent = np.ptp(allpts, axis=0).max()
        if extent < 0.16 * XH_PX:
            c = to_units(allpts.mean(axis=0)[None])[0]
            r = max(extent / 2, float(dt.max()) * 0.4) / XH_PX
            strokes.append({"points": _dot(c, min(r, 0.06)), "deferred": True, "kind": "dot", "_len": total})
            continue
        sh = None
        if hint and "start" in hint and comp is max(comps, key=lambda c: sum(e.length for e in c)):
            hx, hy = hint["start"]
            sh = np.array([ocol + hx * XH_PX, orow - hy * XH_PX])
        pts = best_traversal(G, comp, look, bbox, deslant,
                             lambda pt: (orow - pt[1]) / XH_PX, sh, dt)
        pts = to_units(pts)
        pts = g.smooth(g.resample(pts, 0.01), iterations=3)
        pts = g.rdp(pts, 0.003)
        strokes.append({"points": pts, "deferred": False, "kind": "line", "_len": total})

    # main stroke = longest non-dot; everything else is deferred
    if not strokes:
        return None
    lines = [s for s in strokes if s["kind"] == "line"] or strokes  # '.' is just a dot
    main = max(lines, key=lambda s: s["_len"])
    for s in strokes:
        s["deferred"] = s is not main
    strokes.sort(key=lambda s: (s["deferred"], float(np.min(s["points"][:, 0]))))
    if hint and hint.get("merge"):
        # join the other pen strokes onto the main one (e.g. a two-piece 'k')
        merged = np.asarray(strokes[0]["points"])
        rest = []
        for st in strokes[1:]:
            if st["kind"] != "line":
                rest.append(st)
                continue
            q = np.asarray(st["points"])
            if np.linalg.norm(q[-1] - merged[-1]) < np.linalg.norm(q[0] - merged[-1]):
                q = q[::-1]
            t0 = g.end_tangent(merged, 0.06)
            t1 = g.start_tangent(q, 0.06)
            bridge = g.hermite(merged[-1], t0, q[0], t1, tension=0.4, n=20)
            merged = np.vstack([merged, bridge[1:-1], q])
            strokes[0]["_len"] += st["_len"]
        strokes = [dict(strokes[0], points=merged)] + rest
    for s in strokes:
        s.pop("_len")
        s["points"] = np.round(s["points"], 4).tolist()

    glyph = {
        "char": char,
        "advance": round(adv_px / XH_PX, 4),
        "strokes": strokes,
    }
    glyph.update(auto_anchors(np.asarray(strokes[0]["points"]), char, slant))
    if char.isupper() and glyph["exit"] == "high":
        # capitals that finish high or to the side (B, D, O, P, S...) are
        # traditionally not joined to the next letter
        glyph["exit"] = "none"
    for k in ("lead_in", "lead_out", "entry", "exit", "advance", "final_trim"):
        if hint and k in hint:  # hand overrides from extract_hints.json
            glyph[k] = hint[k]
    return glyph


def auto_anchors(p: np.ndarray, char: str, slant: float = 0.0) -> dict:
    """Guess where the lead-in ends and the lead-out begins on the main stroke.

    lead_in / lead_out are arc lengths from the start / end of the main stroke.
    The join engine replaces those hairlines with a connector when joining.
    """
    s = g.arc_lengths(p)
    total = s[-1]
    out = {"lead_in": 0.0, "lead_out": 0.0, "entry": "low", "exit": "low"}

    # ---- lead-in: the opening upstroke, cut just below its first peak so the
    # connector takes over the upstroke and the glyph keeps its own rounded top
    if len(p) > 2 and p[1, 1] >= p[0, 1] - 1e-3 and p[0, 1] > -0.15:
        i = 0
        while i < len(p) - 1 and p[i + 1, 1] >= p[i, 1] - 1e-3:
            i += 1
        rise = p[i, 1] - p[0, 1]
        # only a true entry stroke coming in from the left counts (with the
        # slant removed); an 'o' that starts low on its own right side does not
        from_left = (p[0, 0] - slant * p[0, 1]) < (p[i, 0] - slant * p[i, 1]) - 0.05
        if rise > 0.2 and s[i] < 0.6 * total and from_left:
            target = p[i, 1] - min(0.12, 0.3 * rise)
            j = min(int(np.searchsorted(p[: i + 1, 1], target)), i)
            # if the letter later crosses its own entry stroke (the eye of an
            # 'e', a looped 'l'), the entry is part of the loop: only cut up to
            # the crossing so the loop survives
            later = p[s > s[j] + 0.15]
            if len(later):
                lead = g.resample(p[: j + 1], 0.01)
                d = np.min(np.linalg.norm(lead[:, None, :] - later[None, :, :], axis=2), axis=1)
                hit = np.flatnonzero(d < 0.035)
                if len(hit):
                    j_arc = g.arc_lengths(lead)[hit[-1]]
                    j = int(np.searchsorted(s, j_arc))
            out["lead_in"] = round(float(s[min(j, len(s) - 1)]), 4) if j > 0 else 0.0
    if out["lead_in"] == 0.0 and len(p) > 4:
        # letters that open with a little hook and then curve back left over
        # their top (c, a, d, g, q in many scripts): the connector should meet
        # the top of the letter, not climb through the bowl to reach the hook
        k = int(np.argmax(np.where(s < 0.35 * total, p[:, 1], -np.inf)))
        right_of_top = (p[0, 0] - slant * p[0, 1]) > (p[k, 0] - slant * p[k, 1]) + 0.03
        short_hook = p[0, 1] > 0.55 and p[k, 1] - p[0, 1] < 0.35
        if k > 0 and right_of_top and short_hook and 0.4 < p[k, 1] < 1.4 and s[k] < 0.35 * total:
            d_after = g.start_tangent(p[k:], 0.06)
            if d_after[0] < 0:  # carries on leftwards from the top
                out["lead_in"] = round(float(s[k]), 4)
                out["hook_retrace"] = True  # keep the hook: flick out and back
    out["entry"] = "low" if p[0, 1] < 0.45 else ("high" if p[0, 1] > 0.7 else "mid")

    # ---- lead-out: a tail rising from the bottom of the last downstroke is a
    # "low" exit (cut back to the bottom); a flat tail near x-height is "high"
    end = p[-1]
    j = len(p) - 1
    while j > 0 and p[j - 1, 1] <= p[j, 1] + 1e-3 and p[j - 1, 1] > -0.02:
        j -= 1  # stop at the baseline: descender loops keep their own shape
    rise = end[1] - p[j, 1]
    if end[1] > 1.5 or end[1] < -0.3:
        out["exit"] = "none"  # ends on an ascender or descender tip: can't join onward
    elif rise > 0.3 and p[j, 1] < 0.35 and total - s[j] < 0.6 * total:
        out["exit"] = "low"
        out["lead_out"] = round(float(total - s[j]), 4)
    elif end[1] > 0.55:
        out["exit"] = "high"
        out["lead_out"] = round(float(min(0.1, 0.2 * total)), 4)
    else:
        out["exit"] = "low"
    return out
