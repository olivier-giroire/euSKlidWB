# SPDX-License-Identifier: LGPL-2.1-or-later
"""Geometric detection helpers for constraint export."""

import math


def normalize(v):
    x, y = float(v[0]), float(v[1])
    n = math.hypot(x, y)
    if n <= 1e-12:
        return (0.0, 0.0)
    return (x / n, y / n)




def are_tangent_vectors(a, b, dot_tol=0.999):
    """Return True when two local tangent vectors describe smooth continuity.

    Direction may be the same or opposite depending on Sketcher orientation and
    path traversal, so the absolute dot product is used.
    """
    va = normalize(a)
    vb = normalize(b)
    if va == (0.0, 0.0) or vb == (0.0, 0.0):
        return False
    dot = abs(va[0] * vb[0] + va[1] * vb[1])
    return dot >= float(dot_tol)


def is_horizontal(dx, dy):
    scale = max(abs(float(dx)), abs(float(dy)), 1.0)
    return abs(float(dy)) <= max(1e-6, 1e-3 * scale)


def is_vertical(dx, dy):
    scale = max(abs(float(dx)), abs(float(dy)), 1.0)
    return abs(float(dx)) <= max(1e-6, 1e-3 * scale)


def segment_dir(meta):
    return (
        meta["end"][0] - meta["start"][0],
        meta["end"][1] - meta["start"][1],
    )


def segment_length(meta):
    dx, dy = segment_dir(meta)
    return math.hypot(float(dx), float(dy))


def tangent_vec_start(meta):
    if meta["type"] == "segment":
        return segment_dir(meta)
    ang = meta["a0"]
    rvec = (math.cos(ang), math.sin(ang))
    if meta.get("delta", 1.0) >= 0:
        return (-rvec[1], rvec[0])
    return (rvec[1], -rvec[0])


def tangent_vec_end(meta):
    if meta["type"] == "segment":
        return segment_dir(meta)
    ang = meta["a1"]
    rvec = (math.cos(ang), math.sin(ang))
    if meta.get("delta", 1.0) >= 0:
        return (-rvec[1], rvec[0])
    return (rvec[1], -rvec[0])



def arc_sweep_length(meta):
    """Return absolute arc length in model units for deterministic references."""
    try:
        return abs(float(meta.get("delta", 0.0))) * abs(float(meta.get("radius", 0.0)))
    except Exception:
        return 0.0


def same_center(a, b, dist_tol=1e-5):
    """Return True when two arc centers are geometrically coincident."""
    ca = a.get("center")
    cb = b.get("center")
    if ca is None or cb is None:
        return False
    return math.hypot(float(ca[0]) - float(cb[0]), float(ca[1]) - float(cb[1])) <= float(dist_tol)


def same_radius(a, b, radius_tol=1e-5):
    """Return True when two arcs have the same radius within tolerance."""
    try:
        ra = abs(float(a.get("radius")))
        rb = abs(float(b.get("radius")))
    except Exception:
        return False
    scale = max(ra, rb, 1.0)
    return abs(ra - rb) <= max(float(radius_tol), 1e-6 * scale)


def same_circle_support(a, b, dist_tol=1e-5, radius_tol=1e-5):
    """Return True when two arcs are fragments of the same circle support."""
    return same_center(a, b, dist_tol=dist_tol) and same_radius(a, b, radius_tol=radius_tol)


def group_same_circle_arcs(arcs, dist_tol=1e-5, radius_tol=1e-5):
    """Group arc fragments by common circle support.

    This is the circular equivalent of line support grouping: disconnected or
    consecutive arc pieces can come from the same construction circle.  Only
    groups of at least two arcs are returned.
    """
    remaining = list(arcs)
    groups = []
    while remaining:
        base = remaining.pop(0)
        group = [base]
        rest = []
        for candidate in remaining:
            if same_circle_support(base, candidate, dist_tol=dist_tol, radius_tol=radius_tol):
                group.append(candidate)
            else:
                rest.append(candidate)
        remaining = rest
        if len(group) > 1:
            groups.append(group)
    return groups

def _line_support(meta):
    """Return canonical infinite-line support for a segment.

    The support is represented as ``(ux, uy, nx, ny, c)`` where ``u`` is a
    canonical unit direction and ``n dot p = c`` is the infinite supporting
    line.  Opposite segment directions are normalized to the same support.
    """
    dx, dy = segment_dir(meta)
    ux, uy = normalize((dx, dy))
    if ux == 0.0 and uy == 0.0:
        return None
    # Canonical sign: opposite directions describe the same line.
    if ux < -1e-12 or (abs(ux) <= 1e-12 and uy < -1e-12):
        ux, uy = -ux, -uy
    nx, ny = -uy, ux
    c = nx * float(meta["start"][0]) + ny * float(meta["start"][1])
    return (ux, uy, nx, ny, c)


def _point_line_distance(pt, support):
    _ux, _uy, nx, ny, c = support
    return abs(nx * float(pt[0]) + ny * float(pt[1]) - c)


def are_collinear_segments(a, b, angle_tol=1e-6, dist_tol=1e-5):
    """Return True when two path segments share the same infinite support."""
    sa = _line_support(a)
    sb = _line_support(b)
    if sa is None or sb is None:
        return False
    dot = abs(sa[0] * sb[0] + sa[1] * sb[1])
    if (1.0 - dot) > float(angle_tol):
        return False
    # Check both endpoints of b against a's support.  This is more robust than
    # comparing offsets when normals are opposite/canonicalized differently.
    return (
        _point_line_distance(b["start"], sa) <= float(dist_tol)
        and _point_line_distance(b["end"], sa) <= float(dist_tol)
    )


def group_collinear_segments(segments, angle_tol=1e-6, dist_tol=1e-5):
    """Group segments by common supporting line.

    Each returned group is ordered by original path traversal.  Only groups of
    at least two segments are returned.  This intentionally groups disjoint
    pieces when they are fragments of the same construction line.
    """
    remaining = list(segments)
    groups = []
    while remaining:
        base = remaining.pop(0)
        group = [base]
        rest = []
        for candidate in remaining:
            if are_collinear_segments(base, candidate, angle_tol=angle_tol, dist_tol=dist_tol):
                group.append(candidate)
            else:
                rest.append(candidate)
        remaining = rest
        if len(group) > 1:
            groups.append(group)
    return groups
