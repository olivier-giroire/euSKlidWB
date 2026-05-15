
import math
from ..math2d import normalize, dist2, project_point_on_line

def build_point_angle_series(ref, point, angles_deg):
    base = normalize(ref["direction"])
    out = []
    for angle_deg in angles_deg or []:
        angle = math.radians(float(angle_deg))
        ca = math.cos(angle)
        sa = math.sin(angle)
        direction = normalize((
            base[0] * ca - base[1] * sa,
            base[0] * sa + base[1] * ca,
        ))
        out.append({
            "origin": point,
            "direction": direction,
            "mode": "point-angle-series",
            "angle": float(angle_deg),
        })
    return out


def build_line_from_two_points(p1, p2):
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        return []
    return [{"origin": p1, "direction": normalize((dx, dy)), "mode": "line-2anchors"}]


def build_tangent_lines_circle_point(circle, point):
    cx, cy = circle["center"]
    r = float(circle["radius"])
    px, py = point

    vx = px - cx
    vy = py - cy
    d2 = vx * vx + vy * vy
    r2 = r * r

    if d2 < r2 - 1e-12:
        return []
    if d2 <= 1e-12:
        return []

    d = math.sqrt(d2)

    if abs(d - r) < 1e-9:
        # point on circle -> one tangent
        dx, dy = normalize((-vy, vx))
        return [{"origin": point, "direction": (dx, dy), "mode": "line-2anchors-tangent"}]

    a = r2 / d2
    b = r * math.sqrt(d2 - r2) / d2

    tx1 = cx + a * vx - b * vy
    ty1 = cy + a * vy + b * vx
    tx2 = cx + a * vx + b * vy
    ty2 = cy + a * vy - b * vx

    d1 = normalize((tx1 - px, ty1 - py))
    d2v = normalize((tx2 - px, ty2 - py))

    out = [{"origin": point, "direction": d1, "mode": "line-2anchors-tangent"}]
    if dist2((tx1, ty1), (tx2, ty2)) > 1e-9:
        out.append({"origin": point, "direction": d2v, "mode": "line-2anchors-tangent"})
    return out


def build_common_tangent_lines_two_circles(c1, c2):
    # returns all common tangents as line candidates
    x1, y1 = c1["center"]
    r1 = float(c1["radius"])
    x2, y2 = c2["center"]
    r2 = float(c2["radius"])

    dx = x2 - x1
    dy = y2 - y1
    d2 = dx * dx + dy * dy
    if d2 <= 1e-12:
        return []

    out = []

    # External and internal tangents
    for s in (+1.0, -1.0):
        rr = r1 - s * r2
        h2 = d2 - rr * rr
        if h2 < -1e-12:
            continue
        h2 = max(0.0, h2)

        for sign in (+1.0, -1.0):
            nx = (dx * rr + -dy * math.sqrt(h2) * sign) / d2
            ny = (dy * rr +  dx * math.sqrt(h2) * sign) / d2

            p1 = (x1 + r1 * nx, y1 + r1 * ny)
            p2 = (x2 + s * r2 * nx, y2 + s * r2 * ny)
            direction = normalize((p2[0] - p1[0], p2[1] - p1[1]))
            out.append({"origin": p1, "direction": direction, "mode": "line-2anchors-tangent"})

    # deduplicate near-identical lines
    uniq = []
    for cand in out:
        keep = True
        for u in uniq:
            d = abs(cand["direction"][0] * u["direction"][1] - cand["direction"][1] * u["direction"][0])
            p = project_point_on_line(cand["origin"], u["origin"], u["direction"])
            dd = dist2(cand["origin"], p)
            if d < 1e-8 and dd < 1e-8:
                keep = False
                break
        if keep:
            uniq.append(cand)
    return uniq

def build_lines_from_two_anchors(a1, a2):
    k1 = a1["kind"]
    k2 = a2["kind"]

    if k1 == "point" and k2 == "point":
        return build_line_from_two_points(a1["point"], a2["point"])

    if k1 == "circle" and k2 == "point":
        return build_tangent_lines_circle_point(a1, a2["point"])

    if k1 == "point" and k2 == "circle":
        return build_tangent_lines_circle_point(a2, a1["point"])

    if k1 == "circle" and k2 == "circle":
        return build_common_tangent_lines_two_circles(a1, a2)

    return []
