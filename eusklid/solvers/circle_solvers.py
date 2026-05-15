# SPDX-License-Identifier: LGPL-2.1-or-later
#
# euSKlidWB - FreeCAD Workbench
# Copyright (C) 2026 Olivier Giroire
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

import math

from ..math2d import (
    circle_from_3pts,
    circles_from_2pts_radius,
    line_circle_intersections,
    circle_circle_intersections,
    tangent_centers_two_lines_radius,
    parallel_line,
    unique_points,
    dist2,
    normalize,
    perp,
)


# --------------------------------------------------
# Simple circle builders
# --------------------------------------------------

def build_circle_center_radius(center, radius):
    r = float(radius)
    if r <= 1e-9:
        return None
    return {
        "center": center,
        "radius": r,
        "mode": "center-radius",
    }


def build_circle_center_pass(center, point):
    r = dist2(center, point)
    if r <= 1e-9:
        return None
    return {
        "center": center,
        "radius": r,
        "mode": "center-pass",
    }


def build_circle_center_anchor(center, anchor):
    if anchor["kind"] == "point":
        c = build_circle_center_pass(center, anchor["point"])
        return [c] if c is not None else []

    if anchor["kind"] == "line":
        d = normalize(anchor["direction"])
        n = normalize(perp(d))
        cst = n[0] * anchor["origin"][0] + n[1] * anchor["origin"][1]
        r = abs(n[0] * center[0] + n[1] * center[1] - cst)
        if r <= 1e-9:
            return []
        return [{
            "center": center,
            "radius": r,
            "mode": "center-anchor",
        }]

    if anchor["kind"] == "circle":
        d = dist2(center, anchor["center"])
        R = float(anchor["radius"])
        radii = []
        for r in [abs(d - R), d + R]:
            if r > 1e-9 and all(abs(r - x) > 1e-7 for x in radii):
                radii.append(r)
        return [{
            "center": center,
            "radius": r,
            "mode": "center-anchor",
        } for r in radii]

    return []


def build_circle_three_points(p1, p2, p3):
    result = circle_from_3pts(p1, p2, p3)
    if result is None:
        return None
    c, r = result
    return {
        "center": c,
        "radius": r,
        "mode": "3pts",
    }


def build_circles_from_two_anchors_radius(a1, a2, radius):
    r = float(radius)
    if r <= 1e-9:
        return []

    k1 = a1["kind"]
    k2 = a2["kind"]

    if k1 == "point" and k2 == "point":
        centers = circles_from_2pts_radius(a1["point"], a2["point"], r)
        return [{"center": c, "radius": r, "mode": "2anchors-radius"} for c in centers or []]

    if k1 == "point" and k2 == "line":
        p = a1["point"]
        pts = []
        for s in (+1.0, -1.0):
            lo, ld = parallel_line(a2["origin"], a2["direction"], s * r)
            pts.extend(line_circle_intersections(lo, ld, p, r))
        pts = unique_points(pts)
        return [{"center": c, "radius": r, "mode": "2anchors-radius"} for c in pts]

    if k1 == "line" and k2 == "point":
        return build_circles_from_two_anchors_radius(a2, a1, r)

    if k1 == "point" and k2 == "circle":
        p = a1["point"]
        c = a2
        pts = []
        radii = [c["radius"] + r]
        if abs(c["radius"] - r) > 1e-9:
            radii.append(abs(c["radius"] - r))
        for rr in radii:
            pts.extend(circle_circle_intersections(p, r, c["center"], rr))
        pts = unique_points(pts)
        return [{"center": c0, "radius": r, "mode": "2anchors-radius"} for c0 in pts]

    if k1 == "circle" and k2 == "point":
        return build_circles_from_two_anchors_radius(a2, a1, r)

    if k1 == "line" and k2 == "line":
        pts = tangent_centers_two_lines_radius(
            (a1["origin"], a1["direction"]),
            (a2["origin"], a2["direction"]),
            r,
        )
        pts = unique_points(pts)
        return [{"center": c, "radius": r, "mode": "2anchors-radius"} for c in pts]

    if k1 == "line" and k2 == "circle":
        pts = []
        radii = [a2["radius"] + r]
        if abs(a2["radius"] - r) > 1e-9:
            radii.append(abs(a2["radius"] - r))
        for s in (+1.0, -1.0):
            lo, ld = parallel_line(a1["origin"], a1["direction"], s * r)
            for rr in radii:
                pts.extend(line_circle_intersections(lo, ld, a2["center"], rr))
        pts = unique_points(pts)
        return [{"center": c, "radius": r, "mode": "2anchors-radius"} for c in pts]

    if k1 == "circle" and k2 == "line":
        return build_circles_from_two_anchors_radius(a2, a1, r)

    if k1 == "circle" and k2 == "circle":
        pts = []
        radii1 = [a1["radius"] + r]
        radii2 = [a2["radius"] + r]
        if abs(a1["radius"] - r) > 1e-9:
            radii1.append(abs(a1["radius"] - r))
        if abs(a2["radius"] - r) > 1e-9:
            radii2.append(abs(a2["radius"] - r))
        for r1 in radii1:
            for r2 in radii2:
                pts.extend(circle_circle_intersections(a1["center"], r1, a2["center"], r2))
        pts = unique_points(pts)
        return [{"center": c, "radius": r, "mode": "2anchors-radius"} for c in pts]

    return []


# --------------------------------------------------
# Generic helpers for 3 anchors
# --------------------------------------------------

def _dedup_candidates(cands, tol=1e-6):
    out = []
    for c in cands:
        keep = True
        for u in out:
            if dist2(c["center"], u["center"]) < tol and abs(c["radius"] - u["radius"]) < tol:
                keep = False
                break
        if keep:
            out.append(c)
    return out


def _line_variants(anchor):
    d = normalize(anchor["direction"])
    n = normalize(perp(d))
    cst = n[0] * anchor["origin"][0] + n[1] * anchor["origin"][1]
    return [
        {"type": "line", "n": n, "c": cst, "s": +1.0},
        {"type": "line", "n": n, "c": cst, "s": -1.0},
    ]


def _circle_variants(anchor):
    R = float(anchor["radius"])
    cen = anchor["center"]
    return [
        # external tangency: d = r + R
        {"type": "circle", "center": cen, "alpha": -1.0, "beta": -R},
        # internal tangency, solution circle larger: d = r - R
        {"type": "circle", "center": cen, "alpha": -1.0, "beta": +R},
        # internal tangency, solution circle smaller: d = R - r
        {"type": "circle", "center": cen, "alpha": +1.0, "beta": -R},
    ]


def _point_variants(anchor):
    return [{
        "type": "point",
        "center": anchor["point"],
        "alpha": -1.0,
        "beta": 0.0,
    }]


def _anchor_variants(anchor):
    k = anchor["kind"]
    if k == "point":
        return _point_variants(anchor)
    if k == "line":
        return _line_variants(anchor)
    if k == "circle":
        return _circle_variants(anchor)
    return []


def _eval_equation(var, x, y, r):
    if var["type"] == "line":
        n = var["n"]
        cst = var["c"]
        s = var["s"]
        f = n[0] * x + n[1] * y - cst - s * r
        j = [n[0], n[1], -s]
        return f, j

    cx, cy = var["center"]
    dx = x - cx
    dy = y - cy
    d = math.hypot(dx, dy)
    if d < 1e-12:
        return None, None

    f = d + var["alpha"] * r + var["beta"]
    j = [dx / d, dy / d, var["alpha"]]
    return f, j


def _solve_3x3(A, b):
    M = [
        A[0][:] + [b[0]],
        A[1][:] + [b[1]],
        A[2][:] + [b[2]],
    ]

    for col in range(3):
        piv = max(range(col, 3), key=lambda rr: abs(M[rr][col]))
        if abs(M[piv][col]) < 1e-12:
            return None
        M[col], M[piv] = M[piv], M[col]

        fac = M[col][col]
        for j in range(col, 4):
            M[col][j] /= fac

        for rr in range(3):
            if rr == col:
                continue
            fac = M[rr][col]
            for j in range(col, 4):
                M[rr][j] -= fac * M[col][j]

    return [M[i][3] for i in range(3)]


def _seed_points(anchors):
    pts = []
    rs = []

    for a in anchors:
        if a["kind"] == "point":
            pts.append(a["point"])
        elif a["kind"] == "circle":
            pts.append(a["center"])
            rs.append(float(a["radius"]))
        elif a["kind"] == "line":
            pts.append(a["origin"])

    if not pts:
        pts = [(0.0, 0.0)]

    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)

    scale = max([dist2(p, (cx, cy)) for p in pts] + rs + [5.0])

    rad_guesses = [
        max(scale, 1.0),
        max(scale * 0.5, 1.0),
        max(scale * 1.5, 1.0),
        max((max(rs) if rs else 1.0), 1.0),
        max((max(rs) if rs else 1.0) * 1.5, 1.0),
    ]

    shifts = [
        (0.0, 0.0),
        (scale * 0.5, 0.0),
        (-scale * 0.5, 0.0),
        (0.0, scale * 0.5),
        (0.0, -scale * 0.5),
        (scale * 0.35, scale * 0.35),
        (-scale * 0.35, scale * 0.35),
        (scale * 0.35, -scale * 0.35),
        (-scale * 0.35, -scale * 0.35),
    ]

    seeds = []
    for dx, dy in shifts:
        for rg in rad_guesses:
            seeds.append((cx + dx, cy + dy, rg))
    return seeds


def _verify_anchor(anchor, cand, tol=1e-4):
    x, y = cand["center"]
    r = cand["radius"]

    if anchor["kind"] == "point":
        return abs(dist2((x, y), anchor["point"]) - r) < tol

    if anchor["kind"] == "line":
        d = normalize(anchor["direction"])
        n = normalize(perp(d))
        cst = n[0] * anchor["origin"][0] + n[1] * anchor["origin"][1]
        return abs(abs(n[0] * x + n[1] * y - cst) - r) < tol

    if anchor["kind"] == "circle":
        R = float(anchor["radius"])
        d = dist2((x, y), anchor["center"])
        return min(
            abs(d - (r + R)),
            abs(d - abs(r - R)),
        ) < tol

    return False


def _build_circles_numeric(a1, a2, a3):
    anchors = [a1, a2, a3]
    out = []

    variants_lists = [_anchor_variants(a) for a in anchors]
    for v1 in variants_lists[0]:
        for v2 in variants_lists[1]:
            for v3 in variants_lists[2]:
                for x, y, r in _seed_points(anchors):
                    for _ in range(40):
                        Fs = []
                        Js = []
                        bad = False

                        for v in (v1, v2, v3):
                            f, j = _eval_equation(v, x, y, r)
                            if j is None:
                                bad = True
                                break
                            Fs.append(f)
                            Js.append(j)

                        if bad:
                            break

                        if max(abs(f) for f in Fs) < 1e-9:
                            break

                        step = _solve_3x3(Js, [-f for f in Fs])
                        if step is None:
                            break

                        x += step[0]
                        y += step[1]
                        r += step[2]

                        if r <= 1e-8:
                            break

                        if max(abs(s) for s in step) < 1e-9:
                            break

                    cand = {
                        "center": (x, y),
                        "radius": r,
                        "mode": "3anchors",
                    }
                    if r > 1e-6 and all(_verify_anchor(a, cand) for a in anchors):
                        out.append(cand)

    return _dedup_candidates(out)


# --------------------------------------------------
# Public entry point
# --------------------------------------------------

def build_circles_from_three_anchors(a1, a2, a3):
    # 3 pure points shortcut
    if a1["kind"] == "point" and a2["kind"] == "point" and a3["kind"] == "point":
        c = build_circle_three_points(a1["point"], a2["point"], a3["point"])
        return [c] if c is not None else []

    return _build_circles_numeric(a1, a2, a3)

def build_circles_two_points_radius(p1, p2, radius):
    """Compat wrapper kept for existing tool imports."""
    a1 = {"kind": "point", "point": p1}
    a2 = {"kind": "point", "point": p2}
    return build_circles_from_two_anchors_radius(a1, a2, radius)
