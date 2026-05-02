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

EPS = 1e-12
POINT_TOL = 1e-7


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def scale(v, s):
    return (v[0] * s, v[1] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def perp(v):
    """Return the 2D vector rotated 90 degrees counter-clockwise."""
    return (-v[1], v[0])


def length(v):
    return math.hypot(v[0], v[1])


def normalize(v):
    vector_length = length(v)
    if vector_length <= EPS:
        return (0.0, 0.0)
    return (v[0] / vector_length, v[1] / vector_length)


def dist2(a, b):
    """Return the Euclidean distance between two 2D points.

    Historical name kept for compatibility: this returns distance, not squared
    distance.
    """
    return math.hypot(a[0] - b[0], a[1] - b[1])


def parallel_line(origin, direction, offset):
    normal = normalize(perp(direction))
    return add(origin, scale(normal, offset)), direction


def visible_segment_for_line(origin, direction, half_len=1000.0):
    return (
        add(origin, scale(direction, -half_len)),
        add(origin, scale(direction, half_len)),
    )


def point_to_line_distance(point, origin, direction):
    px, py = point
    ox, oy = origin
    dx, dy = direction
    nx, ny = -dy, dx
    return abs((px - ox) * nx + (py - oy) * ny)


def circle_from_3pts(p1, p2, p3):
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    determinant = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(determinant) < EPS:
        return None

    ux = (
        (x1 * x1 + y1 * y1) * (y2 - y3)
        + (x2 * x2 + y2 * y2) * (y3 - y1)
        + (x3 * x3 + y3 * y3) * (y1 - y2)
    ) / determinant
    uy = (
        (x1 * x1 + y1 * y1) * (x3 - x2)
        + (x2 * x2 + y2 * y2) * (x1 - x3)
        + (x3 * x3 + y3 * y3) * (x2 - x1)
    ) / determinant
    center = (ux, uy)
    return center, dist2(center, p1)


def circles_from_2pts_radius(p1, p2, r):
    chord_length = dist2(p1, p2)
    if chord_length <= EPS or chord_length > 2 * r + EPS:
        return []

    midpoint = ((p1[0] + p2[0]) * 0.5, (p1[1] + p2[1]) * 0.5)
    normal = normalize(perp(sub(p2, p1)))
    h_sq = r * r - (chord_length * 0.5) * (chord_length * 0.5)
    if -1e-9 < h_sq < 0:
        h_sq = 0
    if h_sq < 0:
        return []

    h = math.sqrt(h_sq)
    c1 = add(midpoint, scale(normal, h))
    c2 = add(midpoint, scale(normal, -h))
    return [c1] if dist2(c1, c2) < 1e-9 else [c1, c2]


def intersect_lines(o1, d1, o2, d2):
    x1, y1 = o1
    x2, y2 = o2
    a1, b1 = d1
    a2, b2 = d2
    determinant = a1 * b2 - b1 * a2
    if abs(determinant) < EPS:
        return None

    dx = x2 - x1
    dy = y2 - y1
    t = (dx * b2 - dy * a2) / determinant
    return (x1 + t * a1, y1 + t * b1)


def tangent_centers_two_lines_radius(line1, line2, radius):
    centers = []
    for s1 in (+1.0, -1.0):
        o1, d1 = parallel_line(line1[0], line1[1], s1 * radius)
        for s2 in (+1.0, -1.0):
            o2, d2 = parallel_line(line2[0], line2[1], s2 * radius)
            p = intersect_lines(o1, d1, o2, d2)
            if p is None:
                continue
            if not any(dist2(p, q) < POINT_TOL for q in centers):
                centers.append(p)
    return centers


def line_circle_intersections(line_origin, line_dir, circle_center, circle_radius):
    ox, oy = line_origin
    dx, dy = normalize(line_dir)
    cx, cy = circle_center
    fx = ox - cx
    fy = oy - cy
    b = 2.0 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - circle_radius * circle_radius
    discriminant = b * b - 4.0 * c
    if discriminant < -EPS:
        return []
    if discriminant < 0:
        discriminant = 0.0

    root = math.sqrt(discriminant)
    t1 = (-b - root) / 2.0
    t2 = (-b + root) / 2.0
    pts = [(ox + t1 * dx, oy + t1 * dy)]
    if abs(t2 - t1) > 1e-9:
        pts.append((ox + t2 * dx, oy + t2 * dy))
    return pts


def circle_circle_intersections(c1, r1, c2, r2):
    x0, y0 = c1
    x1, y1 = c2
    dx = x1 - x0
    dy = y1 - y0
    center_distance = math.hypot(dx, dy)
    if center_distance < EPS:
        return []
    if center_distance > r1 + r2 + EPS:
        return []
    if center_distance < abs(r1 - r2) - EPS:
        return []

    a = (r1 * r1 - r2 * r2 + center_distance * center_distance) / (2 * center_distance)
    h_sq = r1 * r1 - a * a
    if h_sq < -EPS:
        return []
    if h_sq < 0:
        h_sq = 0.0

    h = math.sqrt(h_sq)
    xm = x0 + a * dx / center_distance
    ym = y0 + a * dy / center_distance
    rx = -dy * (h / center_distance)
    ry = dx * (h / center_distance)
    p1 = (xm + rx, ym + ry)
    if h < 1e-9:
        return [p1]
    p2 = (xm - rx, ym - ry)
    return [p1, p2]


def unique_points(points, tol=POINT_TOL):
    out = []
    for p in points:
        if not any(dist2(p, q) < tol for q in out):
            out.append(p)
    return out


def project_point_on_line(point, origin, direction):
    normalized_direction = normalize(direction)
    origin_to_point = sub(point, origin)
    t = dot(origin_to_point, normalized_direction)
    return add(origin, scale(normalized_direction, t))


def lines_through_point_tangent_circle(point, center, radius):
    px, py = point
    cx, cy = center
    vx = px - cx
    vy = py - cy
    dd = vx * vx + vy * vy
    rr = radius * radius

    if dd < rr - EPS:
        return []
    if dd <= EPS:
        return []

    d = math.sqrt(dd)

    if abs(d - radius) < 1e-9:
        dx, dy = normalize(perp((vx, vy)))
        return [{"origin": point, "direction": (dx, dy), "mode": "point-tg-circle"}]

    a = rr / dd
    b = radius * math.sqrt(dd - rr) / dd

    tx1 = cx + a * vx - b * vy
    ty1 = cy + a * vy + b * vx
    tx2 = cx + a * vx + b * vy
    ty2 = cy + a * vy - b * vx

    d1 = normalize((tx1 - px, ty1 - py))
    d2v = normalize((tx2 - px, ty2 - py))

    out = [{"origin": point, "direction": d1, "mode": "point-tg-circle"}]
    if dist2((tx1, ty1), (tx2, ty2)) > 1e-9:
        out.append({"origin": point, "direction": d2v, "mode": "point-tg-circle"})
    return out


def parallel_lines_tangent_circle(direction, center, radius):
    normalized_direction = normalize(direction)
    if length(normalized_direction) <= EPS:
        return []
    normal = normalize(perp(normalized_direction))
    out = []
    for s in (+1.0, -1.0):
        origin = add(center, scale(normal, s * radius))
        out.append({"origin": origin, "direction": normalized_direction, "mode": "parallel-tg-circle"})
    return out


def parallel_ref_tangent_circle(ref_origin, ref_direction, center, radius):
    return parallel_lines_tangent_circle(ref_direction, center, radius)
