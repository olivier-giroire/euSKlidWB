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

import FreeCAD as App
import FreeCADGui as Gui

from ..runtime import get_data
from .config import get_config
from ..snap import SnapEngine2D
from ..math2d import (
    normalize,
    perp,
    scale,
    add,
    project_point_on_line,
    lines_through_point_tangent_circle,
)

_SNAP = SnapEngine2D(tol=8.0)


def _autogrid_step():
    """Return autogrid step in UV/model units, or None when disabled.

    Current convention follows FreeCAD's usual model units:
    - cm     -> 10.0
    - mm     -> 1.0
    - 0.1mm  -> 0.1
    """
    try:
        feeling = get_config().get("feeling", {})
        mode = str(feeling.get("autogrid", feeling.get("autocorrect", "off"))).strip().lower()
    except Exception:
        mode = "off"

    if mode in ("off", "none", "", "false"):
        return None
    if mode in ("cm", "closest cm", "centimeter", "centimetre"):
        return 10.0
    if mode in ("mm", "closest mm", "millimeter", "millimetre"):
        return 1.0
    if mode in ("0.1mm", "mm/10", "closest 0.1 mm", "closest 0.1mm", "0.1 mm"):
        return 0.1
    return None


def _apply_autogrid_to_free_point(uv):
    step = _autogrid_step()
    if step is None or step <= 0.0:
        return uv
    try:
        return (
            round(float(uv[0]) / step) * step,
            round(float(uv[1]) / step) * step,
        )
    except Exception:
        return uv


def _with_autogrid_if_free(snap):
    try:
        if snap.get("kind") == "free":
            snap = dict(snap)
            snap["point"] = _apply_autogrid_to_free_point(snap.get("point", (0.0, 0.0)))
            snap["autogrid"] = _autogrid_step() is not None
        return snap
    except Exception:
        return snap


def _snap_threshold_px():
    try:
        return float(get_config().get("feeling", {}).get("snap_threshold", 20.0))
    except Exception:
        return 20.0


def snap_threshold_uv(sketch_obj, uv):
    """Convert the configured snap threshold from screen pixels to UV/model units.

    The UI value is intentionally expressed in pixels: snap feel should remain
    stable while zooming. Distances in the 2D snap/pick code are UV/model units,
    so this helper converts the pixel threshold at the current cursor position.
    """
    px = _snap_threshold_px()

    try:
        data = get_data(sketch_obj)
        plane = data.plane

        view = Gui.ActiveDocument.ActiveView
        cam = view.getCameraNode()

        try:
            _w, h = view.getSize()
            vh = max(1.0, float(h))
        except Exception:
            vh = 1000.0

        world = App.Vector(*plane.uv_to_world(uv))

        # Orthographic camera: cam.height is the visible world height.
        try:
            cam_height = float(cam.height.getValue())
            return max(1e-6, cam_height * px / vh)
        except Exception:
            pass

        # Perspective camera: use depth along the view axis, not raw distance.
        try:
            pos = cam.position.getValue()
            cam_pos = App.Vector(float(pos[0]), float(pos[1]), float(pos[2]))

            ori = cam.orientation.getValue()
            rot = App.Rotation(float(ori[0]), float(ori[1]), float(ori[2]), float(ori[3]))
            view_dir = rot.multVec(App.Vector(0.0, 0.0, -1.0))

            depth = max(1e-6, world.sub(cam_pos).dot(view_dir))
            angle = float(cam.heightAngle.getValue())
            visible_h = 2.0 * depth * math.tan(angle * 0.5)
            return max(1e-6, visible_h * px / vh)
        except Exception:
            pass

    except Exception:
        pass

    # Fallback: previous behavior, but only if view conversion failed.
    return max(1e-6, px)

def compute_snap(sketch_obj, uv):
    try:
        _SNAP.tol = snap_threshold_uv(sketch_obj, uv)
    except Exception:
        pass
    base = _SNAP.snap(uv, get_data(sketch_obj))
    ox, oy = 0.0, 0.0
    d0 = (uv[0] - ox) ** 2 + (uv[1] - oy) ** 2
    if d0 <= (_SNAP.tol * _SNAP.tol):
        if base.get("kind") == "free":
            return {"kind": "origin", "point": (0.0, 0.0), "source": "origin"}
        bp = base.get("point", uv)
        db = (uv[0] - bp[0]) ** 2 + (uv[1] - bp[1]) ** 2
        if d0 <= db:
            return {"kind": "origin", "point": (0.0, 0.0), "source": "origin"}
    return _with_autogrid_if_free(base)


def _pick_nearest_circle(context, uv):
    try:
        from ..controller import _pick_nearest_circle
        return _pick_nearest_circle(context.sketch_obj, uv)
    except Exception:
        return None


def _pick_nearest_line(context, uv):
    try:
        from ..controller import _pick_reference_line
        return _pick_reference_line(context.sketch_obj, uv)
    except Exception:
        return None


def _tangent_snap_for_fixed_direction(direction, circle, cursor_uv):
    d = normalize(direction)
    if d == (0.0, 0.0):
        return None
    n = normalize(perp(d))
    pts = [
        add(circle["center"], scale(n, circle["radius"])),
        add(circle["center"], scale(n, -circle["radius"])),
    ]
    best = min(pts, key=lambda p: (p[0]-cursor_uv[0])**2 + (p[1]-cursor_uv[1])**2)
    return {
        "kind": "tangent",
        "point": best,
        "source": circle,
    }


def _tangent_snap_from_point_to_circle(point, circle, cursor_uv):
    cands = lines_through_point_tangent_circle(point, circle["center"], circle["radius"])
    if not cands:
        return None
    pts = [project_point_on_line(circle["center"], c["origin"], c["direction"]) for c in cands]
    best = min(pts, key=lambda p: (p[0]-cursor_uv[0])**2 + (p[1]-cursor_uv[1])**2)
    return {
        "kind": "tangent",
        "point": best,
        "source": circle,
        "anchor": {"kind": "circle", "center": circle["center"], "radius": circle["radius"]},
    }


def _tangent_snap_from_center_to_line(center, line):
    pt = project_point_on_line(center, line["origin"], line["direction"])
    return {
        "kind": "tangent",
        "point": pt,
        "source": line,
        "anchor": {"kind": "line", "origin": line["origin"], "direction": line["direction"]},
    }


def _tangent_snap_from_center_to_circle(center, circle, cursor_uv):
    vx = center[0] - circle["center"][0]
    vy = center[1] - circle["center"][1]
    d = (vx * vx + vy * vy) ** 0.5
    if d <= 1e-12:
        return None
    ux, uy = vx / d, vy / d
    pts = [
        (circle["center"][0] + ux * circle["radius"], circle["center"][1] + uy * circle["radius"]),
        (circle["center"][0] - ux * circle["radius"], circle["center"][1] - uy * circle["radius"]),
    ]
    best = min(pts, key=lambda p: (p[0]-cursor_uv[0])**2 + (p[1]-cursor_uv[1])**2)
    return {
        "kind": "tangent",
        "point": best,
        "source": circle,
        "anchor": {"kind": "circle", "center": circle["center"], "radius": circle["radius"]},
    }


def compute_free_point(context, cursor_uv):
    """Return a free point position, applying Autogrid if enabled.

    This intentionally bypasses geometric snaps and primitive picking. It is
    used by the user override modifier in pickers.
    """
    try:
        return _apply_autogrid_to_free_point(cursor_uv)
    except Exception:
        return cursor_uv

def compute_contextual_snaps(context, cursor_uv):
    base = compute_snap(context.sketch_obj, cursor_uv)

    if base.get("kind") != "free":
        return base

    if context.name in ("parallel_ref_anchor", "perpendicular_ref_anchor"):
        direction = context.metadata.get("tangent_line_direction")
        if direction is not None:
            circle = _pick_nearest_circle(context, cursor_uv)
            if circle is not None:
                snap = _tangent_snap_for_fixed_direction(direction, circle, cursor_uv)
                if snap is not None:
                    return snap

    selected = context.metadata.get("selected_anchors", []) if hasattr(context, "metadata") else []

    if selected:
        point_anchor = None
        for a in reversed(selected):
            if a.get("kind") == "point":
                point_anchor = a
                break

        if point_anchor is not None and context.name in ("line_two_anchors", "circle_three_anchors", "circle_two_anchors_radius"):
            circle = _pick_nearest_circle(context, cursor_uv)
            if circle is not None:
                snap = _tangent_snap_from_point_to_circle(point_anchor["point"], circle, cursor_uv)
                if snap is not None:
                    return snap

        if point_anchor is not None and context.name == "circle_center_anchor":
            line = _pick_nearest_line(context, cursor_uv)
            if line is not None and line.get("kind") != "axis":
                snap = _tangent_snap_from_center_to_line(point_anchor["point"], line)
                if snap is not None:
                    return snap
            circle = _pick_nearest_circle(context, cursor_uv)
            if circle is not None:
                snap = _tangent_snap_from_center_to_circle(point_anchor["point"], circle, cursor_uv)
                if snap is not None:
                    return snap

    return base
