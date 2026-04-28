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


from .geom import LineEntity2D, CircleEntity2D
from .math2d import dist2, intersect_lines, line_circle_intersections, circle_circle_intersections

class SnapEngine2D:
    def __init__(self, tol=8.0):
        self.tol = float(tol)

    def _collect_points(self, data):
        pts = []
        entities = list(data.entities)
        for ent in entities:
            if isinstance(ent, CircleEntity2D):
                pts.append({"kind": "center", "point": tuple(ent.center), "source": ent})
        for i in range(len(entities)):
            a = entities[i]
            for j in range(i + 1, len(entities)):
                b = entities[j]
                if isinstance(a, LineEntity2D) and isinstance(b, LineEntity2D):
                    p = intersect_lines(a.origin, a.direction, b.origin, b.direction)
                    if p is not None:
                        pts.append({"kind": "intersection", "point": p, "source": (a, b)})
                elif isinstance(a, LineEntity2D) and isinstance(b, CircleEntity2D):
                    for p in line_circle_intersections(a.origin, a.direction, b.center, b.radius):
                        pts.append({"kind": "intersection", "point": p, "source": (a, b)})
                elif isinstance(a, CircleEntity2D) and isinstance(b, LineEntity2D):
                    for p in line_circle_intersections(b.origin, b.direction, a.center, a.radius):
                        pts.append({"kind": "intersection", "point": p, "source": (a, b)})
                elif isinstance(a, CircleEntity2D) and isinstance(b, CircleEntity2D):
                    for p in circle_circle_intersections(a.center, a.radius, b.center, b.radius):
                        pts.append({"kind": "intersection", "point": p, "source": (a, b)})
        out = []
        for item in pts:
            duplicate = False
            for existing in out:
                if dist2(existing["point"], item["point"]) < 1e-7:
                    duplicate = True
                    break
            if not duplicate:
                out.append(item)
        return out

    def snap(self, uv, data):
        candidates = self._collect_points(data)
        best = None
        best_dist = None
        for item in candidates:
            d = dist2(uv, item["point"])
            if best_dist is None or d < best_dist:
                best = item
                best_dist = d
        if best is not None and best_dist is not None and best_dist <= self.tol:
            return dict(best)
        return {"kind": "free", "point": tuple(uv), "source": None}
