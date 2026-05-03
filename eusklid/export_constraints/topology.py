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
