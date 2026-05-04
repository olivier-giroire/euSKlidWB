# SPDX-License-Identifier: LGPL-2.1-or-later
"""Path topology helpers for constraint export."""

import math


def dist(a, b):
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def connected_junctions(geom_meta, tol):
    """Yield successive closed-loop junctions whose endpoints coincide.

    This keeps the path traversal semantics and is used for local smoothness
    constraints only (tangent continuity between neighbouring path elements).
    """
    n = len(geom_meta)
    for i in range(n):
        cur = geom_meta[i]
        nxt = geom_meta[(i + 1) % n]
        if dist(cur.get("end"), nxt.get("start")) <= tol:
            yield i, cur, nxt


def endpoint_coincidence_pairs(geom_meta, tol):
    """Yield every geometric endpoint coincidence in the exported path.

    Unlike :func:`connected_junctions`, this is not limited to successive
    traversal neighbours.  Path exports can contain fragments generated from a
    common support circle/line where the actual topological connection is an
    endpoint coincidence between non-consecutive geometry entries.  These
    coincidences are mandatory and must not be filtered out by higher-level
    relation reductions.

    Yields tuples ``(a_meta, a_point_id, b_meta, b_point_id)`` where point ids
    follow FreeCAD Sketcher convention for lines/arcs:

    - ``1``: start point
    - ``2``: end point
    """
    endpoints = []
    for order, meta in enumerate(geom_meta):
        start = meta.get("start")
        end = meta.get("end")
        if start is not None:
            endpoints.append((order, meta, 1, start))
        if end is not None:
            endpoints.append((order, meta, 2, end))

    seen = set()
    n = len(endpoints)
    for i in range(n):
        order_a, meta_a, point_a, pos_a = endpoints[i]
        for j in range(i + 1, n):
            order_b, meta_b, point_b, pos_b = endpoints[j]
            if meta_a is meta_b:
                continue
            if dist(pos_a, pos_b) > tol:
                continue
            key = (
                int(meta_a.get("index", order_a)),
                int(point_a),
                int(meta_b.get("index", order_b)),
                int(point_b),
            )
            rev = (key[2], key[3], key[0], key[1])
            if key in seen or rev in seen:
                continue
            seen.add(key)
            yield meta_a, point_a, meta_b, point_b



def endpoint_clusters(geom_meta, tol):
    """Return geometric endpoint clusters.

    Each cluster contains tuples ``(order, meta, point_id, position)``.  This is
    used by higher-level relation detection to avoid adding one constraint per
    coincident duplicate endpoint.  Coincidence constraints remain emitted for
    every matching endpoint pair; clusters are only a compact representative
    view of the same topology.
    """
    endpoints = []
    for order, meta in enumerate(geom_meta):
        start = meta.get("start")
        end = meta.get("end")
        if start is not None:
            endpoints.append((order, meta, 1, start))
        if end is not None:
            endpoints.append((order, meta, 2, end))

    clusters = []
    for item in endpoints:
        _order, _meta, _point_id, pos = item
        found = None
        for cluster in clusters:
            # Compare to the first representative; endpoint coincidence is
            # already tolerance-based and model coordinates are stable here.
            if dist(pos, cluster[0][3]) <= tol:
                found = cluster
                break
        if found is None:
            clusters.append([item])
        else:
            found.append(item)
    return clusters


def _cluster_center(cluster):
    sx = 0.0
    sy = 0.0
    n = 0
    for _order, _meta, _point_id, pos in cluster:
        sx += float(pos[0])
        sy += float(pos[1])
        n += 1
    if n <= 0:
        return (0.0, 0.0)
    return (sx / n, sy / n)


def mirrored_endpoint_pairs_y_axis(geom_meta, tol):
    """Yield representative endpoint pairs mirrored about the sketch Y axis.

    v6.1 intentionally starts with the safest symmetry case: mirror pairs about
    the global vertical sketch axis (x=0).  The detection works on endpoint
    clusters rather than raw endpoints, so a topological vertex made of several
    coincident endpoints contributes only one symmetry constraint.

    Yields ``(a_meta, a_point_id, b_meta, b_point_id)``.  The caller is
    responsible for converting this to Sketcher ``Symmetric`` constraints.
    """
    clusters = endpoint_clusters(geom_meta, tol)
    infos = []
    for ci, cluster in enumerate(clusters):
        cx, cy = _cluster_center(cluster)
        # Points already on the symmetry axis do not need a pair constraint.
        if abs(cx) <= tol:
            continue
        # Use the first endpoint in path order as representative.  Coincidence
        # constraints tie the rest of the cluster to this representative.
        rep = min(cluster, key=lambda item: int(item[0]))
        infos.append((ci, cx, cy, rep))

    used = set()
    pairs = []
    for i, (ci, cx, cy, rep) in enumerate(infos):
        if ci in used:
            continue
        best = None
        best_score = None
        for cj, ox, oy, orep in infos[i + 1:]:
            if cj in used:
                continue
            # Mirror across Y: x coordinates are opposite, y identical.
            dx_mirror = abs(cx + ox)
            dy = abs(cy - oy)
            if dx_mirror > tol or dy > tol:
                continue
            # Require opposite sides.  This avoids pairing near-axis noise.
            if cx * ox >= 0:
                continue
            score = dx_mirror + dy
            if best_score is None or score < best_score:
                best_score = score
                best = (cj, orep)
        if best is None:
            continue
        cj, orep = best
        used.add(ci)
        used.add(cj)
        _order_a, meta_a, point_a, _pos_a = rep
        _order_b, meta_b, point_b, _pos_b = orep
        pairs.append((meta_a, point_a, meta_b, point_b))

    for pair in pairs:
        yield pair

def mirrored_endpoint_pairs_x_axis(geom_meta, tol):
    """Yield representative endpoint pairs mirrored about the sketch X axis.

    This is the horizontal-axis counterpart of
    :func:`mirrored_endpoint_pairs_y_axis`: x coordinates must match and y
    coordinates must be opposite.  Detection is performed on endpoint clusters
    so coincident duplicate endpoints contribute only one symmetry constraint.

    Yields ``(a_meta, a_point_id, b_meta, b_point_id)``.
    """
    clusters = endpoint_clusters(geom_meta, tol)
    infos = []
    for ci, cluster in enumerate(clusters):
        cx, cy = _cluster_center(cluster)
        # Points already on the symmetry axis do not need a pair constraint.
        if abs(cy) <= tol:
            continue
        rep = min(cluster, key=lambda item: int(item[0]))
        infos.append((ci, cx, cy, rep))

    used = set()
    pairs = []
    for i, (ci, cx, cy, rep) in enumerate(infos):
        if ci in used:
            continue
        best = None
        best_score = None
        for cj, ox, oy, orep in infos[i + 1:]:
            if cj in used:
                continue
            # Mirror across X: x identical, y coordinates are opposite.
            dx = abs(cx - ox)
            dy_mirror = abs(cy + oy)
            if dx > tol or dy_mirror > tol:
                continue
            # Require opposite sides.  This avoids pairing near-axis noise.
            if cy * oy >= 0:
                continue
            score = dx + dy_mirror
            if best_score is None or score < best_score:
                best_score = score
                best = (cj, orep)
        if best is None:
            continue
        cj, orep = best
        used.add(ci)
        used.add(cj)
        _order_a, meta_a, point_a, _pos_a = rep
        _order_b, meta_b, point_b, _pos_b = orep
        pairs.append((meta_a, point_a, meta_b, point_b))

    for pair in pairs:
        yield pair

def _central_symmetry_nodes(geom_meta, tol):
    """Return representative point-like nodes for central symmetry.

    Nodes include topological endpoint clusters and circular support centers.
    Each node is a tuple ``(kind, cx, cy, representative)``.  The
    representative is ``(order, meta, point_id, position)`` and follows
    Sketcher point ids: endpoints use 1/2, arc/circle centers use 3.

    Centers are clustered by position so several arc fragments from the same
    construction circle contribute only one symmetry candidate.
    """
    nodes = []

    for cluster in endpoint_clusters(geom_meta, tol):
        cx, cy = _cluster_center(cluster)
        rep = min(cluster, key=lambda item: int(item[0]))
        nodes.append(("endpoint", cx, cy, rep))

    center_clusters = []
    for order, meta in enumerate(geom_meta):
        center = meta.get("center")
        if center is None:
            continue
        # Arc/circle center point id in FreeCAD Sketcher.
        item = (order, meta, 3, center)
        found = None
        for cluster in center_clusters:
            if dist(center, cluster[0][3]) <= tol:
                found = cluster
                break
        if found is None:
            center_clusters.append([item])
        else:
            found.append(item)

    for cluster in center_clusters:
        cx, cy = _cluster_center(cluster)
        rep = min(cluster, key=lambda item: int(item[0]))
        nodes.append(("center", cx, cy, rep))

    return nodes


def mirrored_endpoint_pairs_center_origin(geom_meta, tol):
    """Yield representative point pairs centrally symmetric about origin.

    Despite the historical function name, this v6.3.1 implementation includes
    both topological endpoints and circular support centers.  Endpoint clusters
    preserve the path graph semantics; center clusters allow central symmetry of
    circles/arcs to be exported as a relation between their Sketcher center
    points.

    Yields ``(a_meta, a_point_id, b_meta, b_point_id)``.
    """
    infos = []
    for ni, (_kind, cx, cy, rep) in enumerate(_central_symmetry_nodes(geom_meta, tol)):
        # The origin itself does not need a symmetric pair.
        if abs(cx) <= tol and abs(cy) <= tol:
            continue
        infos.append((ni, cx, cy, rep))

    used = set()
    pairs = []
    for i, (ci, cx, cy, rep) in enumerate(infos):
        if ci in used:
            continue
        best = None
        best_score = None
        for cj, ox, oy, orep in infos[i + 1:]:
            if cj in used:
                continue
            dx_mirror = abs(cx + ox)
            dy_mirror = abs(cy + oy)
            if dx_mirror > tol or dy_mirror > tol:
                continue
            # Require true opposite quadrants/half-planes, not near-origin noise.
            if (cx * ox > -tol) and (cy * oy > -tol):
                continue
            score = dx_mirror + dy_mirror
            if best_score is None or score < best_score:
                best_score = score
                best = (cj, orep)
        if best is None:
            continue
        cj, orep = best
        used.add(ci)
        used.add(cj)
        _order_a, meta_a, point_a, _pos_a = rep
        _order_b, meta_b, point_b, _pos_b = orep
        pairs.append((meta_a, point_a, meta_b, point_b))

    for pair in pairs:
        yield pair



def _symmetry_node_key(node):
    """Return a stable key for a point-like symmetry node."""
    if len(node) >= 5:
        _kind, _cx, _cy, rep, _ctx = node
    else:
        _kind, _cx, _cy, rep = node
    _order, meta, point_id, _pos = rep
    return (int(meta.get("index", _order)), int(point_id))


def _node_rep(node):
    return node[3]


def _node_context(node):
    if len(node) >= 5:
        return node[4] or {}
    kind = node[0]
    _order, meta, point_id, _pos = _node_rep(node)
    if int(point_id) == 3 or kind == "center":
        return {"kind": "center", "types": {meta.get("type")}, "degree": 1, "radius": meta.get("radius")}
    return {"kind": "endpoint", "types": {meta.get("type")}, "degree": 1}


def _radius_close(a, b, tol):
    try:
        ra = abs(float(a))
        rb = abs(float(b))
    except Exception:
        return False
    scale = max(ra, rb, 1.0)
    return abs(ra - rb) <= max(float(tol), 1e-5 * scale)


def _endpoint_cluster_role(cluster):
    types = set()
    orders = []
    for order, meta, _point_id, _pos in cluster:
        types.add(str(meta.get("type") or "unknown"))
        try:
            orders.append(int(order))
        except Exception:
            pass
    return {
        "kind": "endpoint",
        "types": types,
        "degree": len(cluster),
        "path_span": (max(orders) - min(orders)) if orders else 0,
        "has_segment": "segment" in types,
        "has_arc": "arc" in types,
    }


def _arbitrary_symmetry_nodes(geom_meta, tol):
    """Return point-like nodes enriched with local context for v6.4e.

    Arbitrary centers are dangerous if selected only by raw pair count.  This
    helper keeps the same representative geometry used by the previous passes,
    but adds a compact local role used to score pair relevance:

    - endpoint clusters know whether they are segment/segment, arc/arc, or
      arc/segment junctions;
    - center clusters know their radius and are therefore comparable only with
      similar circle/arc centers.
    """
    nodes = []

    for cluster in endpoint_clusters(geom_meta, tol):
        cx, cy = _cluster_center(cluster)
        rep = min(cluster, key=lambda item: int(item[0]))
        ctx = _endpoint_cluster_role(cluster)
        nodes.append(("endpoint", cx, cy, rep, ctx))

    center_clusters = []
    for order, meta in enumerate(geom_meta):
        center = meta.get("center")
        if center is None:
            continue
        item = (order, meta, 3, center)
        found = None
        for cluster in center_clusters:
            if dist(center, cluster[0][3]) <= tol:
                found = cluster
                break
        if found is None:
            center_clusters.append([item])
        else:
            found.append(item)

    for cluster in center_clusters:
        cx, cy = _cluster_center(cluster)
        rep = min(cluster, key=lambda item: int(item[0]))
        radii = []
        types = set()
        for _order, meta, _point, _pos in cluster:
            types.add(str(meta.get("type") or "unknown"))
            try:
                radii.append(abs(float(meta.get("radius"))))
            except Exception:
                pass
        radius = sum(radii) / len(radii) if radii else None
        ctx = {"kind": "center", "types": types, "degree": len(cluster), "radius": radius}
        nodes.append(("center", cx, cy, rep, ctx))

    return nodes


def _pair_relevance(a, b, tol):
    """Return a deterministic semantic relevance score for a symmetry pair.

    The previous v6.4d score counted independent pairs.  That can select a
    very local, artificial center if several unrelated endpoints happen to have
    the same midpoint.  v6.4e keeps only comparable local roles and ranks them:

    - similar circle/arc centers are highly structural;
    - arc/segment junctions are strong path features;
    - plain segment endpoints are weak but still valid;
    - center/endpoint pairs are rejected as usually accidental.
    """
    ca = _node_context(a)
    cb = _node_context(b)
    ka = ca.get("kind")
    kb = cb.get("kind")

    if ka != kb:
        return 0.0

    if ka == "center":
        # Symmetry between centers is only meaningful if the supports are
        # comparable.  Equal/similar radii make this a very strong signal.
        ra = ca.get("radius")
        rb = cb.get("radius")
        if ra is not None and rb is not None:
            if _radius_close(ra, rb, tol):
                return 4.0
            return 1.0
        return 2.0

    if ka == "endpoint":
        ta = set(ca.get("types") or [])
        tb = set(cb.get("types") or [])
        if not ta or not tb:
            return 0.5
        common = ta.intersection(tb)
        if not common:
            return 0.0

        # Arc/segment junctions are much more meaningful than isolated path
        # endpoints because they preserve a local construction role.
        if ca.get("has_arc") and ca.get("has_segment") and cb.get("has_arc") and cb.get("has_segment"):
            return 2.5
        if ca.get("has_arc") and cb.get("has_arc"):
            return 2.0
        if ca.get("has_segment") and cb.get("has_segment"):
            # Degree > 1 is a true topological junction.  Degree == 1 is often
            # just a free endpoint and should not dominate structural centers.
            if int(ca.get("degree", 1)) > 1 and int(cb.get("degree", 1)) > 1:
                return 1.5
            return 1.0
        return 0.5

    return 0.0


def arbitrary_center_symmetry_candidates(geom_meta, tol, min_score=4, include_origin=False):
    """Detect arbitrary central symmetry centers with semantic relevance.

    Every pair of comparable point-like nodes defines a possible center.  A
    candidate is accepted only when at least ``min_score`` independent relevant
    pairs share the same midpoint.  Candidates also carry ``weighted_score`` so
    the emission pass can prefer structural symmetries over accidental local
    branches with the same raw count.

    ``include_origin`` controls the interaction with the explicit origin-center
    symmetry mode.  When Central symmetry export is enabled, (0,0) is handled by
    that dedicated pass and should not be emitted again here.  When it is
    disabled, (0,0) is allowed to compete as an ordinary arbitrary center.
    """
    try:
        min_score = max(3, int(min_score))
    except Exception:
        min_score = 4

    nodes = list(_arbitrary_symmetry_nodes(geom_meta, tol))
    raw = []
    for i, a in enumerate(nodes):
        _ak, ax, ay, _arep = a[:4]
        for b in nodes[i + 1:]:
            _bk, bx, by, _brep = b[:4]
            relevance = _pair_relevance(a, b, tol)
            if relevance <= 0.0:
                continue
            mx = (float(ax) + float(bx)) * 0.5
            my = (float(ay) + float(by)) * 0.5
            # Origin central symmetry has its own explicit toggle.  Exclude it
            # only when the dedicated origin-center pass is enabled; otherwise
            # let (0,0) compete normally as an arbitrary center.
            if not include_origin and abs(mx) <= tol and abs(my) <= tol:
                continue
            raw.append((mx, my, a, b, float(relevance)))

    clusters = []
    for item in raw:
        mx, my, _a, _b, _rel = item
        found = None
        for cluster in clusters:
            cx, cy = cluster["center"]
            if dist((mx, my), (cx, cy)) <= tol:
                found = cluster
                break
        if found is None:
            clusters.append({"center": (mx, my), "items": [item]})
        else:
            found["items"].append(item)
            # Maintain a stable average center for logging.
            n = len(found["items"])
            cx, cy = found["center"]
            found["center"] = ((cx * (n - 1) + mx) / n, (cy * (n - 1) + my) / n)

    candidates = []
    for cluster in clusters:
        used_nodes = set()
        kept_pairs = []
        weighted_score = 0.0
        cx, cy = cluster["center"]
        # Prefer strong semantic pairs first, then numeric proximity to the
        # cluster center.  This prevents weak accidental endpoints from taking
        # slots before circle centers or arc/segment junctions.
        sorted_items = sorted(
            cluster["items"],
            key=lambda it: (-float(it[4]), dist((it[0], it[1]), (cx, cy))),
        )
        for _mx, _my, a, b, relevance in sorted_items:
            ka = _symmetry_node_key(a)
            kb = _symmetry_node_key(b)
            if ka in used_nodes or kb in used_nodes:
                continue
            used_nodes.add(ka)
            used_nodes.add(kb)
            kept_pairs.append((a, b, float(relevance)))
            weighted_score += float(relevance)

        if len(kept_pairs) < min_score:
            continue
        candidates.append({
            "center": cluster["center"],
            "score": len(kept_pairs),
            "raw_pairs": len(cluster["items"]),
            "weighted_score": weighted_score,
            "pairs": kept_pairs,
        })

    candidates.sort(
        key=lambda c: (
            -float(c.get("weighted_score", 0.0)),
            -int(c.get("score", 0)),
            float(abs(c["center"][0])) + float(abs(c["center"][1])),
        )
    )
    for candidate in candidates:
        yield candidate

def _canonical_axis_from_pair(a, b, tol):
    """Return a canonical perpendicular-bisector axis for node pair ``a``/``b``.

    A symmetry axis candidate is the perpendicular bisector of the two point-like
    nodes.  It is stored in normal form ``n.x * x + n.y * y = offset`` plus a
    direction vector useful for Sketcher construction-line emission.
    """
    _ak, ax, ay, _arep = a[:4]
    _bk, bx, by, _brep = b[:4]
    dx = float(bx) - float(ax)
    dy = float(by) - float(ay)
    length = math.hypot(dx, dy)
    if length <= max(float(tol), 1e-12):
        return None

    # Reflection axis normal is the segment AB direction.
    nx = dx / length
    ny = dy / length
    mx = (float(ax) + float(bx)) * 0.5
    my = (float(ay) + float(by)) * 0.5
    offset = nx * mx + ny * my

    # Canonical orientation so equivalent axes cluster together.
    if nx < -tol or (abs(nx) <= tol and ny < 0.0):
        nx = -nx
        ny = -ny
        offset = -offset

    # Axis direction is perpendicular to the normal.
    ux = -ny
    uy = nx
    return {
        "point": (mx, my),
        "normal": (nx, ny),
        "direction": (ux, uy),
        "offset": offset,
    }


def _axis_close(axis_a, axis_b, tol):
    nax, nay = axis_a["normal"]
    nbx, nby = axis_b["normal"]
    # Normals are canonical, so same-axis normals should be close, not opposite.
    dn = math.hypot(float(nax) - float(nbx), float(nay) - float(nby))
    if dn > max(1e-6, 1e-3):
        return False
    scale = max(abs(float(axis_a.get("offset", 0.0))), abs(float(axis_b.get("offset", 0.0))), 1.0)
    return abs(float(axis_a.get("offset", 0.0)) - float(axis_b.get("offset", 0.0))) <= max(float(tol), 1e-5 * scale)


def arbitrary_axis_symmetry_candidates(geom_meta, tol, min_score=4):
    """Detect arbitrary axial symmetry candidates with semantic relevance.

    Each comparable node pair defines a perpendicular-bisector axis.  Candidates
    are clustered by line normal/offset, then reduced to independent node pairs
    exactly like arbitrary centers.  The result is intentionally conservative:
    only axes with at least ``min_score`` independent relevant pairs are yielded.
    """
    try:
        min_score = max(3, int(min_score))
    except Exception:
        min_score = 4

    nodes = list(_arbitrary_symmetry_nodes(geom_meta, tol))
    raw = []
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            relevance = _pair_relevance(a, b, tol)
            if relevance <= 0.0:
                continue
            axis = _canonical_axis_from_pair(a, b, tol)
            if axis is None:
                continue
            raw.append((axis, a, b, float(relevance)))

    clusters = []
    for item in raw:
        axis, _a, _b, _rel = item
        found = None
        for cluster in clusters:
            if _axis_close(axis, cluster["axis"], tol):
                found = cluster
                break
        if found is None:
            clusters.append({"axis": dict(axis), "items": [item]})
        else:
            found["items"].append(item)
            # Maintain stable averaged axis parameters for logging/emission.
            n = len(found["items"])
            old = found["axis"]
            nx = (old["normal"][0] * (n - 1) + axis["normal"][0]) / n
            ny = (old["normal"][1] * (n - 1) + axis["normal"][1]) / n
            nn = math.hypot(nx, ny) or 1.0
            nx, ny = nx / nn, ny / nn
            off = (old["offset"] * (n - 1) + axis["offset"]) / n
            px = nx * off
            py = ny * off
            found["axis"] = {
                "point": (px, py),
                "normal": (nx, ny),
                "direction": (-ny, nx),
                "offset": off,
            }

    candidates = []
    for cluster in clusters:
        used_nodes = set()
        kept_pairs = []
        weighted_score = 0.0
        axis = cluster["axis"]
        sorted_items = sorted(
            cluster["items"],
            key=lambda it: (-float(it[3]), abs(float(it[0]["offset"]) - float(axis["offset"]))),
        )
        for _axis, a, b, relevance in sorted_items:
            ka = _symmetry_node_key(a)
            kb = _symmetry_node_key(b)
            if ka in used_nodes or kb in used_nodes:
                continue
            used_nodes.add(ka)
            used_nodes.add(kb)
            kept_pairs.append((a, b, float(relevance)))
            weighted_score += float(relevance)

        if len(kept_pairs) < min_score:
            continue
        candidates.append({
            "axis": axis,
            "score": len(kept_pairs),
            "raw_pairs": len(cluster["items"]),
            "weighted_score": weighted_score,
            "pairs": kept_pairs,
        })

    candidates.sort(
        key=lambda c: (
            -float(c.get("weighted_score", 0.0)),
            -int(c.get("score", 0)),
            abs(float(c["axis"].get("offset", 0.0))),
        )
    )
    for candidate in candidates:
        yield candidate

