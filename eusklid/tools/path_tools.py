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
import json
import time

import FreeCAD as App
import FreeCADGui as Gui
import Part

try:
    from pivy import coin
except Exception:
    coin = None

from ..geom import LineEntity2D, CircleEntity2D
from ..runtime import get_or_create_euclid_sketch, get_data
from ..core.groups import ensure_euclid_groups, get_path_group, get_transient_group, add_to_group
from ..core.config import get_config
from ..core import logging as elog
from ..qt_compat import QtWidgets
from ..export_constraints import add_path_constraints




# Sketcher tagging for euSKlid exports.
# Geometry objects in Sketcher do not carry custom properties reliably, so the
# tag is stored on the target Sketcher object as JSON. The stored indices allow
# a later export to remove only the geometry/constraints created by euSKlid,
# leaving user geometry untouched.
_EUSKLID_EXPORT_PROP = "EuSKlidExportTag"
_EUSKLID_EXPORT_GROUP = "euSKlid"
_EUSKLID_EXPORT_TAG = "euSKlid.path.export.v1"


def _ensure_export_tag_property(sk):
    if sk is None:
        return False
    try:
        if _EUSKLID_EXPORT_PROP not in getattr(sk, "PropertiesList", []):
            sk.addProperty(
                "App::PropertyString",
                _EUSKLID_EXPORT_PROP,
                _EUSKLID_EXPORT_GROUP,
                "euSKlid-owned Sketcher geometry/constraints for safe re-export",
            )
        return True
    except Exception as exc:
        try:
            elog.info("Export tag property unavailable: %s" % exc)
        except Exception:
            pass
        return False


def _read_export_tag(sk):
    if sk is None:
        return {}
    try:
        raw = getattr(sk, _EUSKLID_EXPORT_PROP, "") or ""
        data = json.loads(raw) if raw else {}
        if isinstance(data, dict) and data.get("tag") == _EUSKLID_EXPORT_TAG:
            return data
    except Exception as exc:
        try:
            elog.info("Export tag read skipped: %s" % exc)
        except Exception:
            pass
    return {}


def _write_export_tag(sk, geometries, constraints, label="path"):
    if sk is None or not _ensure_export_tag_property(sk):
        return
    data = {
        "tag": _EUSKLID_EXPORT_TAG,
        "label": str(label),
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "geometries": sorted({int(i) for i in geometries}),
        "constraints": sorted({int(i) for i in constraints}),
    }
    try:
        setattr(sk, _EUSKLID_EXPORT_PROP, json.dumps(data, sort_keys=True))
    except Exception as exc:
        try:
            elog.info("Export tag write skipped: %s" % exc)
        except Exception:
            pass


def _delete_constraint_safe(sk, index):
    for meth in ("delConstraint", "deleteConstraint", "removeConstraint"):
        try:
            fn = getattr(sk, meth, None)
            if fn is not None:
                fn(int(index))
                return True
        except Exception:
            pass
    return False


def _delete_geometry_safe(sk, index):
    # delGeometry(index, True) asks Sketcher to remove dependent constraints when
    # supported. We already delete tagged constraints first, but this keeps the
    # operation resilient across FreeCAD versions.
    for args in ((int(index), True), (int(index),)):
        try:
            sk.delGeometry(*args)
            return True
        except Exception:
            pass
    for meth in ("deleteGeometry", "removeGeometry"):
        try:
            fn = getattr(sk, meth, None)
            if fn is not None:
                fn(int(index))
                return True
        except Exception:
            pass
    return False


def _clear_previous_eusklid_export(sk):
    data = _read_export_tag(sk)
    if not data:
        return {"constraints": 0, "geometries": 0}

    removed_constraints = 0
    for ci in sorted(data.get("constraints", []), reverse=True):
        if _delete_constraint_safe(sk, ci):
            removed_constraints += 1

    removed_geometries = 0
    for gi in sorted(data.get("geometries", []), reverse=True):
        if _delete_geometry_safe(sk, gi):
            removed_geometries += 1

    try:
        setattr(sk, _EUSKLID_EXPORT_PROP, "")
    except Exception:
        pass
    return {"constraints": removed_constraints, "geometries": removed_geometries}


def _active_edit_sketch():
    try:
        edit = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument is not None else None
    except Exception:
        edit = None
    candidates = []
    if edit is not None:
        candidates.append(getattr(edit, "Object", edit))
    try:
        for obj in Gui.Selection.getSelection():
            candidates.append(obj)
    except Exception:
        pass
    for obj in candidates:
        try:
            if getattr(obj, "TypeId", "") == "Sketcher::SketchObject":
                return obj
        except Exception:
            pass
    return None

_PATH_ACTIVE_OBJECTS = []
_PATH_PREVIEW_OBJECTS = []
_PATH_MARKER_OBJECTS = []
_PATH_CLOSED_OBJECTS = []

# Coin3D transient Path overlays. Document objects are kept only for closed paths.
_PATH_OVERLAY_ROOTS = {}

_CLOSED_PATHS = []
_ACTIVE_PATH_SESSION = None



def _path_scene_graph():
    try:
        if coin is None or Gui.ActiveDocument is None:
            return None
        return Gui.ActiveDocument.ActiveView.getSceneGraph()
    except Exception:
        return None


def _path_overlay_root(layer):
    """Return the visual content node for a Path overlay layer.

    The scenegraph structure is:
        root separator
          ├─ SoPickStyle(UNPICKABLE)
          └─ content separator  ← returned by this function

    _path_overlay_clear() only clears the content separator, so the
    unpickable style cannot be accidentally removed during redraw.
    """
    if coin is None:
        return None

    entry = _PATH_OVERLAY_ROOTS.get(layer)
    if entry is not None:
        try:
            return entry["content"]
        except Exception:
            return entry

    sg = _path_scene_graph()
    if sg is None:
        return None

    try:
        root = coin.SoSeparator()

        try:
            pick = coin.SoPickStyle()
            pick.style.setValue(coin.SoPickStyle.UNPICKABLE)
            root.addChild(pick)
        except Exception:
            pass

        content = coin.SoSeparator()
        root.addChild(content)

        sg.addChild(root)
        _PATH_OVERLAY_ROOTS[layer] = {"root": root, "content": content}
        return content
    except Exception:
        return None




def _path_request_redraw():
    """Ask FreeCAD/Coin3D to repaint transient Path overlays now.

    Coin3D scene graph updates are sometimes not repainted until the next mouse
    event. This helper intentionally touches only the GUI/view layer; it does
    not change Path state, selection state, closed paths, or exported geometry.
    """
    try:
        if Gui.ActiveDocument is None:
            return
        view = Gui.ActiveDocument.ActiveView
        if view is None:
            return
        for meth in ("update", "redraw"):
            fn = getattr(view, meth, None)
            if fn is None:
                continue
            try:
                fn()
                return
            except Exception:
                pass
        try:
            Gui.updateGui()
        except Exception:
            pass
    except Exception:
        pass

def _path_overlay_clear(layer=None):
    layers = list(_PATH_OVERLAY_ROOTS.keys()) if layer is None else [layer]
    for key in layers:
        entry = _PATH_OVERLAY_ROOTS.get(key)
        if entry is None:
            continue
        try:
            content = entry.get("content") if isinstance(entry, dict) else entry
            if content is not None:
                content.removeAllChildren()
        except Exception:
            pass


def _path_material(color, alpha=0):
    mat = coin.SoMaterial()
    try:
        mat.diffuseColor.setValue(float(color[0]), float(color[1]), float(color[2]))
        mat.transparency.setValue(max(0.0, min(1.0, float(alpha) / 100.0)))
    except Exception:
        pass
    return mat


def _path_draw_polyline(layer, plane, uv_points, color, width=3.0, alpha=0):
    root = _path_overlay_root(layer)
    if root is None or not uv_points:
        return False
    try:
        pts = []
        for uv in uv_points:
            w = App.Vector(*plane.uv_to_world(uv))
            pts.append((float(w.x), float(w.y), float(w.z)))
        if len(pts) < 2:
            return False
        sep = coin.SoSeparator()
        sep.addChild(_path_material(color, alpha))
        draw = coin.SoDrawStyle()
        draw.lineWidth.setValue(float(width))
        sep.addChild(draw)
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(pts), pts)
        sep.addChild(coords)
        line = coin.SoLineSet()
        line.numVertices.set1Value(0, len(pts))
        sep.addChild(line)
        root.addChild(sep)
        return True
    except Exception:
        return False


def _path_piece_uv_points(piece):
    if piece.get("type") == "segment":
        return [piece.get("a"), piece.get("b")]
    try:
        center = piece["center"]
        radius = float(piece["radius"])
        a0 = float(piece["a0"])
        delta = float(piece.get("delta", float(piece["a1"]) - a0))
        steps = max(8, min(96, int(abs(delta) * 24.0) + 2))
        return [(center[0] + radius * math.cos(a0 + delta * i / float(steps)), center[1] + radius * math.sin(a0 + delta * i / float(steps))) for i in range(steps + 1)]
    except Exception:
        return []


def _path_draw_piece(layer, plane, piece, color, width=3.0, alpha=0):
    return _path_draw_polyline(layer, plane, _path_piece_uv_points(piece), color, width, alpha)


def _path_draw_marker(layer, plane, uv, kind="marker", name="euSKlidPathPoint"):
    root = _path_overlay_root(layer)
    if root is None or uv is None:
        return False
    try:
        world = App.Vector(*plane.uv_to_world(uv))
        radius = max(_path_pixels_to_world(plane, uv, _path_point_size() * 0.5), _path_pixels_to_world(plane, uv, 4.0))
        color = _path_point_color(kind)
        sep = coin.SoSeparator()
        sep.addChild(_path_material(color, _path_point_alpha()))
        tr = coin.SoTranslation()
        tr.translation.setValue(float(world.x), float(world.y), float(world.z))
        sep.addChild(tr)
        sph = coin.SoSphere()
        sph.radius.setValue(float(radius))
        sep.addChild(sph)
        root.addChild(sep)
        return True
    except Exception:
        return False

def _path_cfg():
    try:
        return get_config().get("path", {})
    except Exception:
        return {}


def _path_style(kind, fallback_color, fallback_width, fallback_alpha=0):
    try:
        cfg = _path_cfg().get(kind, {})
        color = tuple(cfg.get("color", fallback_color))
        width = float(cfg.get("thickness", fallback_width))
        alpha = int(cfg.get("alpha", fallback_alpha))
        return color, width, alpha
    except Exception:
        return fallback_color, float(fallback_width), int(fallback_alpha)


def _path_point_cfg():
    try:
        return get_config().get("gui", {}).get("points", {})
    except Exception:
        return {}


def _path_point_size():
    try:
        return float(_path_point_cfg().get("size", 20.0))
    except Exception:
        return 20.0


def _path_point_alpha():
    try:
        return int(_path_point_cfg().get("alpha", 30))
    except Exception:
        return 30


def _path_point_color(kind="marker"):
    try:
        colors = _path_point_cfg().get("colors", {})
        if kind == "hover":
            return tuple(colors.get("hover", (1.0, 0.0, 1.0)))
        if kind == "snap":
            return tuple(colors.get("snap", (0.2, 1.0, 0.2)))
        if kind == "selected":
            return tuple(colors.get("selected", (0.2, 0.4, 1.0)))
        if kind == "fixed":
            return tuple(colors.get("fixed", (1.0, 1.0, 0.0)))
        return tuple(colors.get("marker", (1.0, 0.5, 0.0)))
    except Exception:
        return (1.0, 0.5, 0.0)


def _path_pixels_to_world(plane, uv, px):
    try:
        view = Gui.ActiveDocument.ActiveView
        cam = view.getCameraNode()
        try:
            _w, h = view.getSize()
            vh = max(1.0, float(h))
        except Exception:
            vh = 1000.0
        world = App.Vector(*plane.uv_to_world(uv))
        try:
            cam_height = float(cam.height.getValue())
            return max(1e-6, cam_height * float(px) / vh)
        except Exception:
            pass
        try:
            pos = cam.position.getValue()
            cam_pos = App.Vector(float(pos[0]), float(pos[1]), float(pos[2]))
            ori = cam.orientation.getValue()
            rot = App.Rotation(float(ori[0]), float(ori[1]), float(ori[2]), float(ori[3]))
            view_dir = rot.multVec(App.Vector(0.0, 0.0, -1.0))
            depth = max(1e-6, world.sub(cam_pos).dot(view_dir))
            angle = float(cam.heightAngle.getValue())
            visible_h = 2.0 * depth * math.tan(angle * 0.5)
            return max(1e-6, visible_h * float(px) / vh)
        except Exception:
            pass
    except Exception:
        pass
    return max(1e-6, float(px) * 0.01)


def _make_path_point(plane, uv, kind="marker", name="euSKlidPathPoint"):
    radius = _path_pixels_to_world(plane, uv, _path_point_size() * 0.5)
    min_radius = _path_pixels_to_world(plane, uv, 4.0)
    return _make_sphere(
        plane,
        uv,
        radius=max(radius, min_radius),
        color=_path_point_color(kind),
        transparency=_path_point_alpha(),
        name=name,
    )


def _remove_objects(objs):
    doc = App.ActiveDocument
    if doc is None:
        return []
    for obj in list(objs):
        try:
            doc.removeObject(obj.Name)
        except Exception:
            pass
    return []


def clear_path_active():
    global _PATH_ACTIVE_OBJECTS
    _path_overlay_clear("active")
    _PATH_ACTIVE_OBJECTS = _remove_objects(_PATH_ACTIVE_OBJECTS)


def clear_path_preview():
    global _PATH_PREVIEW_OBJECTS
    _path_overlay_clear("preview")
    _PATH_PREVIEW_OBJECTS = _remove_objects(_PATH_PREVIEW_OBJECTS)


def clear_path_markers():
    global _PATH_MARKER_OBJECTS
    _path_overlay_clear("markers")
    _PATH_MARKER_OBJECTS = _remove_objects(_PATH_MARKER_OBJECTS)


def _make_sphere(plane, uv, radius=2.4, color=(1.0, 0.5, 0.0), transparency=5, name="euSKlidPathPoint"):
    doc = App.ActiveDocument
    if doc is None:
        return None
    center = App.Vector(*plane.uv_to_world(uv))
    ensure_euclid_groups(doc)
    obj = doc.addObject("Part::Feature", name)
    try:
        add_to_group(obj, get_transient_group(doc))
    except Exception:
        pass
    obj.Shape = Part.makeSphere(float(radius), center)
    try:
        obj.ViewObject.ShapeColor = color
        obj.ViewObject.LineColor = color
        obj.ViewObject.PointColor = color
        obj.ViewObject.Transparency = transparency
        obj.ViewObject.Selectable = False
    except Exception:
        pass
    return obj


def _make_line_segment(plane, a_uv, b_uv, color, width=5.0, transparency=0, name="euSKlidPathSeg"):
    doc = App.ActiveDocument
    if doc is None:
        return None
    a = App.Vector(*plane.uv_to_world(a_uv))
    b = App.Vector(*plane.uv_to_world(b_uv))
    ensure_euclid_groups(doc)
    obj = doc.addObject("Part::Feature", name)
    try:
        grp = get_path_group(doc) if name.startswith("euSKlidClosedPath") else get_transient_group(doc)
        add_to_group(obj, grp)
    except Exception:
        pass
    obj.Shape = Part.makeLine(a, b)
    try:
        obj.ViewObject.LineColor = color
        obj.ViewObject.LineWidth = width
        obj.ViewObject.Transparency = transparency
        obj.ViewObject.Selectable = False
    except Exception:
        pass
    return obj


def _make_arc_segment(plane, center_uv, radius, a0, a1, color, width=5.0, transparency=0, name="euSKlidPathArc"):
    doc = App.ActiveDocument
    if doc is None:
        return None
    center = App.Vector(*plane.uv_to_world(center_uv))
    normal = App.Vector(plane.normal.x, plane.normal.y, plane.normal.z)
    circ = Part.Circle(center, normal, float(radius))
    arc = Part.ArcOfCircle(circ, float(a0), float(a1))
    ensure_euclid_groups(doc)
    obj = doc.addObject("Part::Feature", name)
    try:
        grp = get_path_group(doc) if name.startswith("euSKlidClosedPath") else get_transient_group(doc)
        add_to_group(obj, grp)
    except Exception:
        pass
    obj.Shape = arc.toShape()
    try:
        obj.ViewObject.LineColor = color
        obj.ViewObject.LineWidth = width
        obj.ViewObject.Transparency = transparency
        obj.ViewObject.Selectable = False
    except Exception:
        pass
    return obj


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _same_uv(a, b, tol=1e-7):
    return _dist(a, b) <= tol


def _normalize(v):
    n = math.hypot(v[0], v[1])
    if n < 1e-12:
        return (0.0, 0.0)
    return (v[0] / n, v[1] / n)


def _param_on_line(origin, direction, p):
    d = _normalize(direction)
    return (p[0] - origin[0]) * d[0] + (p[1] - origin[1]) * d[1]


def _angle_on_circle(center, p):
    return math.atan2(p[1] - center[1], p[0] - center[0])


def _wrap_angle(a):
    while a < 0.0:
        a += 2.0 * math.pi
    while a >= 2.0 * math.pi:
        a -= 2.0 * math.pi
    return a


def _cross(u, v):
    return u[0] * v[1] - u[1] * v[0]


def _line_line_intersection(o1, d1, o2, d2):
    x1, y1 = o1
    dx1, dy1 = d1
    x2, y2 = o2
    dx2, dy2 = d2
    det = dx1 * dy2 - dy1 * dx2
    if abs(det) < 1e-12:
        return None
    t = ((x2 - x1) * dy2 - (y2 - y1) * dx2) / det
    return (x1 + t * dx1, y1 + t * dy1)


def _line_circle_intersections(origin, direction, center, radius):
    ox, oy = origin
    dx, dy = _normalize(direction)
    cx, cy = center
    fx = ox - cx
    fy = oy - cy
    a = dx * dx + dy * dy
    b = 2.0 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - radius * radius
    disc = b * b - 4.0 * a * c
    if disc < -1e-12:
        return []
    if disc < 0.0:
        disc = 0.0
    s = math.sqrt(disc)
    t1 = (-b - s) / (2.0 * a)
    t2 = (-b + s) / (2.0 * a)
    pts = [(ox + t1 * dx, oy + t1 * dy), (ox + t2 * dx, oy + t2 * dy)]
    out = []
    for p in pts:
        if not any(_same_uv(p, q) for q in out):
            out.append(p)
    return out


def _circle_circle_intersections(c1, r1, c2, r2):
    x1, y1 = c1
    x2, y2 = c2
    dx = x2 - x1
    dy = y2 - y1
    d = math.hypot(dx, dy)
    if d < 1e-12:
        return []
    if d > r1 + r2 + 1e-12:
        return []
    if d < abs(r1 - r2) - 1e-12:
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2.0 * d)
    h2 = r1 * r1 - a * a
    if h2 < -1e-12:
        return []
    if h2 < 0.0:
        h2 = 0.0
    h = math.sqrt(h2)
    xm = x1 + a * dx / d
    ym = y1 + a * dy / d
    rx = -dy * h / d
    ry = dx * h / d
    pts = [(xm + rx, ym + ry), (xm - rx, ym - ry)]
    out = []
    for p in pts:
        if not any(_same_uv(p, q) for q in out):
            out.append(p)
    return out


class PathSession:
    def tol(self):
        try:
            bb = self.sketch_obj.Shape.BoundBox
            size = max(bb.XLength, bb.YLength, bb.ZLength, 1.0)
        except Exception:
            size = 100.0
        return max(1e-6, size * 1e-6)

    def __init__(self, sketch_obj):
        self.sketch_obj = sketch_obj
        self.data = get_data(sketch_obj)
        self.plane = self.data.plane
        self.entities = [ent for ent in self.data.entities if isinstance(ent, (LineEntity2D, CircleEntity2D))]
        self.start_entity_idx = None
        self.start_point = None
        self.current_entity_idx = None
        self.current_point = None
        self.current_direction = None
        self.closed = False
        self.last_mouse_uv = None
        self.active_pieces = []
        self.preview_pieces = []
        self.history = []
        self._push_history()

        self._observer = _SelectionObserver(self)
        Gui.Selection.addObserver(self._observer)
        self._view = Gui.ActiveDocument.ActiveView
        self._cb_move = self._view.addEventCallback("SoLocation2Event", self.on_move)
        self._cb_click = self._view.addEventCallback("SoMouseButtonEvent", self.on_mouse_button)
        self._ignore_selection_until = 0.0
        App.Console.PrintMessage("euSKlid Path: new path started\n")

    def _snapshot(self):
        return {
            "start_entity_idx": self.start_entity_idx,
            "start_point": None if self.start_point is None else tuple(self.start_point),
            "current_entity_idx": self.current_entity_idx,
            "current_point": None if self.current_point is None else tuple(self.current_point),
            "current_direction": self.current_direction,
            "closed": self.closed,
            "active_pieces": [dict(p) for p in self.active_pieces],
            "preview_pieces": [dict(p) for p in self.preview_pieces],
        }

    def _restore_snapshot(self, snap):
        self.start_entity_idx = snap["start_entity_idx"]
        self.start_point = snap["start_point"]
        self.current_entity_idx = snap["current_entity_idx"]
        self.current_point = snap["current_point"]
        self.current_direction = snap["current_direction"]
        self.closed = snap["closed"]
        self.active_pieces = [dict(p) for p in snap["active_pieces"]]
        self.preview_pieces = [dict(p) for p in snap["preview_pieces"]]

    def _push_history(self):
        self.history.append(self._snapshot())

    def undo_last_point(self):
        if len(self.history) <= 1:
            return False
        self.history.pop()
        self._restore_snapshot(self.history[-1])
        self.render_active()
        return True

    def finish(self):
        try:
            Gui.Selection.removeObserver(self._observer)
        except Exception:
            pass
        try:
            self._view.removeEventCallback("SoLocation2Event", self._cb_move)
        except Exception:
            pass
        try:
            self._view.removeEventCallback("SoMouseButtonEvent", self._cb_click)
        except Exception:
            pass
        clear_path_preview()
        clear_path_markers()
        clear_path_active()

    def on_move(self, info):
        try:
            pos = info.get("Position")
            if not pos:
                return

            world = self._view.getPoint(pos[0], pos[1])
            self.last_mouse_uv = self.plane.world_to_uv(
                (float(world[0]), float(world[1]), float(world[2]))
            )

            if self.closed:
                clear_path_preview()
                return

            obj_info = None
            try:
                obj_info = self._view.getObjectInfo((pos[0], pos[1]))
            except Exception:
                try:
                    obj_info = self._view.getObjectInfo(pos[0], pos[1])
                except Exception:
                    obj_info = None

            if not obj_info:
                # Keep the last valid candidate visible while a path is in progress.
                # Clearing it here makes the user click while moving.
                if self.current_entity_idx is None:
                    clear_path_preview()
                    if self.last_mouse_uv is not None:
                        self._show_hover_marker(self.last_mouse_uv)
                return

            sub = obj_info.get("Component", "")
            obj_name = obj_info.get("Object", "")
            if obj_name != self.sketch_obj.Name or not sub.startswith("Edge"):
                # Preserve the last valid candidate while a path is in progress.
                if self.current_entity_idx is None:
                    clear_path_preview()
                    if self.last_mouse_uv is not None:
                        self._show_hover_marker(self.last_mouse_uv)
                return

            entity_idx, ent = self.entity_from_subname(sub)
            if ent is None:
                if self.current_entity_idx is None:
                    clear_path_preview()
                return

            target = self.project_on_entity(entity_idx, self.last_mouse_uv)

            if self.current_entity_idx is None:
                clear_path_preview()
                self._show_hover_marker(target)
                return

            pieces = self.build_local_route(
                self.current_entity_idx,
                self.current_point,
                self.current_direction,
                entity_idx,
                target,
                self.last_mouse_uv,
            )

            if pieces:
                self.preview_pieces = pieces
                self.render_preview()
            # If no valid local route was found, keep the previous candidate visible.

        except Exception as e:
            App.Console.PrintError("euSKlid Path move error: %s\n" % str(e))



    def _is_left_button_down(self, info):
        try:
            state = str(info.get("State", "")).upper()
            button = str(info.get("Button", "")).upper()
            typ = str(info.get("Type", "")).upper()
            if "MOUSEBUTTON" not in typ and button == "":
                return False
            if state and state not in ("DOWN", "PRESS", "PRESSED"):
                return False
            if button and button not in ("BUTTON1", "LEFT", "LEFTBUTTON"):
                return False
            return True
        except Exception:
            return False

    def _object_info_at_screen_pos(self, pos):
        try:
            return self._view.getObjectInfo((pos[0], pos[1]))
        except Exception:
            try:
                return self._view.getObjectInfo(pos[0], pos[1])
            except Exception:
                return None

    def on_mouse_button(self, info):
        """Direct click fallback for Path picking.

        FreeCAD selection can be blocked by transient Coin3D overlays in some
        view providers. After the first point, Path can process the click itself:
        clear overlays briefly, query the sketch edge under the cursor, then
        call process_click(). The first point remains handled by normal selection.
        """
        try:
            if self.closed or self.current_entity_idx is None:
                return
            if not self._is_left_button_down(info):
                return

            pos = info.get("Position")
            if not pos:
                return

            # Remove transient overlays before hit-testing. process_click() will
            # redraw the current path afterwards.
            try:
                _path_overlay_clear()
            except Exception:
                pass

            obj_info = self._object_info_at_screen_pos(pos)
            if not obj_info:
                return

            sub = obj_info.get("Component", "")
            obj_name = obj_info.get("Object", "")
            if obj_name != self.sketch_obj.Name or not sub.startswith("Edge"):
                return

            world = self._view.getPoint(pos[0], pos[1])
            click_uv = self.plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))
            self.last_mouse_uv = click_uv

            self.process_click(sub, click_uv)
            self._ignore_selection_until = time.time() + 0.20
            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass
        except Exception as e:
            App.Console.PrintError("euSKlid Path click error: %s\n" % str(e))


    def entity_from_subname(self, subname):
        if not subname.startswith("Edge"):
            return None, None
        try:
            idx = int(subname[4:]) - 1
        except Exception:
            return None, None
        if idx < 0 or idx >= len(self.entities):
            return None, None
        return idx, self.entities[idx]

    def fallback_point_on_entity(self, entity_idx):
        ent = self.entities[entity_idx]
        if isinstance(ent, LineEntity2D):
            return tuple(ent.origin)
        if isinstance(ent, CircleEntity2D):
            return (ent.center[0] + ent.radius, ent.center[1])
        return (0.0, 0.0)

    def project_on_entity(self, entity_idx, uv):
        ent = self.entities[entity_idx]

        if isinstance(ent, LineEntity2D):
            t = _param_on_line(ent.origin, ent.direction, uv)
            d = _normalize(ent.direction)
            return (ent.origin[0] + t * d[0], ent.origin[1] + t * d[1])

        if isinstance(ent, CircleEntity2D):
            cx, cy = ent.center
            vx = uv[0] - cx
            vy = uv[1] - cy
            n = math.hypot(vx, vy)

            if n < self.tol():
                return (cx + ent.radius, cy)

            return (cx + vx / n * ent.radius, cy + vy / n * ent.radius)

        return uv

    def choose_circle_delta_from_hint(self, ent, a0, a1, hint_uv):
        if hint_uv is None:
            return None
        cx, cy = ent.center
        r = ent.radius
        a0 = _wrap_angle(a0)
        a1 = _wrap_angle(a1)
        ccw_delta = (a1 - a0) % (2.0 * math.pi)
        cw_delta = ccw_delta - 2.0 * math.pi

        def sample_arc(delta, steps=48):
            pts = []
            for i in range(steps + 1):
                t = i / float(steps)
                a = a0 + t * delta
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
            return pts

        pts_ccw = sample_arc(ccw_delta)
        pts_cw = sample_arc(cw_delta)
        d_ccw = min(_dist(p, hint_uv) for p in pts_ccw)
        d_cw = min(_dist(p, hint_uv) for p in pts_cw)
        if abs(d_ccw - d_cw) < 1e-3:
            return None
        return ccw_delta if d_ccw < d_cw else cw_delta

    def route_same_circle(self, entity_idx, p0, p1, hint_uv, enforced_dir):
        ent = self.entities[entity_idx]
        c = ent.center
        r = ent.radius
        a0 = _wrap_angle(_angle_on_circle(c, p0))
        a1 = _wrap_angle(_angle_on_circle(c, p1))
        ccw = (a1 - a0) % (2.0 * math.pi)
        cw = ccw - 2.0 * math.pi
        if abs(ccw) < 1e-12 or abs(cw) < 1e-12:
            return []
        if enforced_dir == +1:
            delta = ccw
        elif enforced_dir == -1:
            delta = cw
        else:
            delta = self.choose_circle_delta_from_hint(ent, a0, a1, hint_uv)
            if delta is None:
                delta = ccw if abs(ccw) <= abs(cw) else cw
        if abs(delta) < 1e-12:
            return []
        return [{"type":"arc","entity":entity_idx,"center":c,"radius":r,"a0":a0,"a1":a0 + delta,"delta":delta}]

    def route_same_entity(self, entity_idx, p0, p1, hint_uv, enforced_dir):
        ent = self.entities[entity_idx]
        if isinstance(ent, LineEntity2D):
            t0 = _param_on_line(ent.origin, ent.direction, p0)
            t1 = _param_on_line(ent.origin, ent.direction, p1)
            d = 0
            if t1 > t0 + 1e-9:
                d = +1
            elif t1 < t0 - 1e-9:
                d = -1
            if enforced_dir is not None and d != 0 and d != enforced_dir:
                return []
            if _same_uv(p0, p1):
                return []
            return [{"type":"segment","entity":entity_idx,"a":p0,"b":p1}]
        if isinstance(ent, CircleEntity2D):
            return self.route_same_circle(entity_idx, p0, p1, hint_uv, enforced_dir)
        return []

    def intersections_between(self, idx1, idx2):
        e1 = self.entities[idx1]
        e2 = self.entities[idx2]
        if isinstance(e1, LineEntity2D) and isinstance(e2, LineEntity2D):
            p = _line_line_intersection(e1.origin, e1.direction, e2.origin, e2.direction)
            return [] if p is None else [p]
        if isinstance(e1, LineEntity2D) and isinstance(e2, CircleEntity2D):
            return _line_circle_intersections(e1.origin, e1.direction, e2.center, e2.radius)
        if isinstance(e1, CircleEntity2D) and isinstance(e2, LineEntity2D):
            return _line_circle_intersections(e2.origin, e2.direction, e1.center, e1.radius)
        if isinstance(e1, CircleEntity2D) and isinstance(e2, CircleEntity2D):
            return _circle_circle_intersections(e1.center, e1.radius, e2.center, e2.radius)
        return []

    def route_two_entities(self, from_idx, p0, from_dir, to_idx, p1, hint_uv):
        inters = self.intersections_between(from_idx, to_idx)
        if not inters:
            return []
        best = []
        best_score = None
        for inter in inters:
            part1 = self.route_same_entity(from_idx, p0, inter, inter, from_dir)
            if not part1:
                continue
            dir1 = self.direction_on_entity(from_idx, part1, fallback=from_dir)
            if from_dir is not None and dir1 is not None and dir1 != from_dir:
                continue
            part2 = self.route_same_entity(to_idx, inter, p1, hint_uv, None)
            if not part2:
                continue
            pieces = self.merge_pieces(part1 + part2)
            total_len = self.length_of_pieces(pieces)
            bias = _dist(inter, p1) * 0.05
            dir_bias = 0.0
            if from_dir is not None:
                if isinstance(self.entities[from_idx], LineEntity2D):
                    ent = self.entities[from_idx]
                    d = _normalize(ent.direction)
                    v = (inter[0] - p0[0], inter[1] - p0[1])
                    dot = d[0]*v[0] + d[1]*v[1]
                    if from_dir > 0 and dot < 0:
                        dir_bias += 1000
                    if from_dir < 0 and dot > 0:
                        dir_bias += 1000
            score = total_len + bias + dir_bias
            if best_score is None or score < best_score:
                best_score = score
                best = pieces
        return best

    def build_local_route(self, from_idx, p0, from_dir, to_idx, p1, hint_uv):
        if from_idx == to_idx:
            return self.route_same_entity(from_idx, p0, p1, hint_uv, from_dir)
        return self.route_two_entities(from_idx, p0, from_dir, to_idx, p1, hint_uv)

    def length_of_pieces(self, pieces):
        total = 0.0
        for piece in pieces:
            if piece.get("type") == "segment":
                if _dist(piece["a"], piece["b"]) < self.tol():
                    continue
            if piece.get("type") == "arc":
                if abs(piece["delta"]) * piece["radius"] < self.tol():
                    continue
            if piece["type"] == "segment":
                total += _dist(piece["a"], piece["b"])
            else:
                total += abs(piece["delta"]) * piece["radius"]
        return total

    def direction_on_entity(self, entity_idx, pieces, fallback=None):
        for piece in reversed(pieces):
            if piece["entity"] != entity_idx:
                continue
            if piece["type"] == "segment":
                ent = self.entities[entity_idx]
                ta = _param_on_line(ent.origin, ent.direction, piece["a"])
                tb = _param_on_line(ent.origin, ent.direction, piece["b"])
                if tb > ta + 1e-9:
                    return +1
                if tb < ta - 1e-9:
                    return -1
            else:
                if piece["delta"] > 1e-9:
                    return +1
                if piece["delta"] < -1e-9:
                    return -1
        return fallback

    def _pieces_are_mergeable(self, a, b):
        if a["type"] != b["type"]:
            return False

        if a["type"] == "segment":
            if not _same_uv(a["b"], b["a"], self.tol()):
                return False

            da = (a["b"][0] - a["a"][0], a["b"][1] - a["a"][1])
            db = (b["b"][0] - b["a"][0], b["b"][1] - b["a"][1])

            na = _normalize(da)
            nb = _normalize(db)
            dot = na[0] * nb[0] + na[1] * nb[1]

            return abs(dot) > 0.999

        if a["type"] == "arc":
            if a["entity"] != b["entity"]:
                return False

            if abs(_wrap_angle(a["a1"]) - _wrap_angle(b["a0"])) > 1e-6:
                return False

            same_sign = (
                (a["delta"] >= 0 and b["delta"] >= 0) or
                (a["delta"] <= 0 and b["delta"] <= 0)
            )
            return same_sign

        return False

    def _merge_two_pieces(self, a, b):
        out = dict(a)

        if a["type"] == "segment":
            out["b"] = b["b"]
            return out

        if a["type"] == "arc":
            out["a1"] = b["a1"]
            out["delta"] = a["delta"] + b["delta"]
            return out

        return out

    def merge_pieces(self, pieces):
        if not pieces:
            return []

        out = []

        for piece in pieces:
            if piece["type"] == "segment":
                if _dist(piece["a"], piece["b"]) < self.tol():
                    continue

            if piece["type"] == "arc":
                if abs(piece["delta"]) * piece["radius"] < self.tol():
                    continue

            if not out:
                out.append(dict(piece))
                continue

            prev = out[-1]

            if self._pieces_are_mergeable(prev, piece):
                out[-1] = self._merge_two_pieces(prev, piece)
            else:
                out.append(dict(piece))

        # IMPORTANT :
        # si le path est fermé, on fusionne aussi première et dernière pièce
        # quand elles sont sur la même primitive / même sens.
        changed = True
        while len(out) >= 2 and changed:
            changed = False
            first = out[0]
            last = out[-1]

            # on veut tester la jonction "last -> first"
            if last["type"] == first["type"]:
                if last["type"] == "segment":
                    test_last = dict(last)
                    test_first = dict(first)
                    if self._pieces_are_mergeable(test_last, test_first):
                        merged = self._merge_two_pieces(test_last, test_first)
                        out = [merged] + out[1:-1]
                        changed = True

                elif last["type"] == "arc":
                    test_last = dict(last)
                    test_first = dict(first)
                    if self._pieces_are_mergeable(test_last, test_first):
                        merged = self._merge_two_pieces(test_last, test_first)
                        out = [merged] + out[1:-1]
                        changed = True

        return out

    def _show_hover_marker(self, uv):
        clear_path_markers()
        obj = _make_path_point(
            self.plane,
            uv,
            kind="hover",
            name="euSKlidPathHover",
        )
        global _PATH_MARKER_OBJECTS
        _PATH_MARKER_OBJECTS = [obj] if obj is not None else []
        try:
            App.ActiveDocument.recompute()
        except Exception:
            pass

    def _show_markers(self, markers):
        clear_path_markers()
        global _PATH_MARKER_OBJECTS
        _PATH_MARKER_OBJECTS = []
        for item in markers or []:
            try:
                uv = item[0]
                kind = item[1] if len(item) > 1 else "marker"
                name = item[2] if len(item) > 2 else "euSKlidPathMarker"
                if not isinstance(kind, str):
                    kind = "marker"
                if not _path_draw_marker("markers", self.plane, uv, kind=kind, name=name):
                    obj = _make_path_point(self.plane, uv, kind=kind, name=name)
                    if obj is not None:
                        _PATH_MARKER_OBJECTS.append(obj)
            except Exception:
                pass

    def _piece_start_uv(self, piece):
        if piece.get("type") == "segment":
            return piece.get("a")
        return (
            piece["center"][0] + piece["radius"] * math.cos(piece["a0"]),
            piece["center"][1] + piece["radius"] * math.sin(piece["a0"]),
        )

    def _piece_end_uv(self, piece):
        if piece.get("type") == "segment":
            return piece.get("b")
        return (
            piece["center"][0] + piece["radius"] * math.cos(piece["a1"]),
            piece["center"][1] + piece["radius"] * math.sin(piece["a1"]),
        )

    def _draw_piece_with_fallback(self, layer, piece, color, width, alpha, seg_name, arc_name):
        # Primary renderer: Coin3D overlay. Legacy Part::Feature is kept only as a
        # fallback if Coin3D is unavailable, so the Path interaction remains usable.
        try:
            if _path_draw_piece(layer, self.plane, piece, color, width, alpha):
                return None
        except Exception:
            pass

        if piece["type"] == "segment":
            return _make_line_segment(
                self.plane,
                piece["a"],
                piece["b"],
                color=color,
                width=width,
                transparency=alpha,
                name=seg_name,
            )

        a0 = piece["a0"]
        a1 = piece["a1"]
        if piece["delta"] < 0.0:
            a0, a1 = a1, a0
        return _make_arc_segment(
            self.plane,
            piece["center"],
            piece["radius"],
            a0,
            a1,
            color=color,
            width=width,
            transparency=alpha,
            name=arc_name,
        )

    def render_all(self):
        """Redraw the whole transient Path state in one pass.

        This avoids transient visual dropouts caused by separate active/preview
        redraws clearing one another during dense mouse/camera events. The Path
        data stays unchanged; only the visual layers are refreshed.
        """
        clear_path_active()
        clear_path_preview()
        clear_path_markers()

        active_objs = []
        preview_objs = []
        markers = []

        if self.start_point is not None:
            markers.append((self.start_point, "marker", "euSKlidPathStart"))

        if self.current_point is not None:
            markers.append((self.current_point, "marker", "euSKlidPathCurrent"))
        elif self.last_mouse_uv is not None:
            markers.append((self.last_mouse_uv, "hover", "euSKlidPathHover"))

        cur_color, cur_width, cur_alpha = _path_style("current", (1.0, 0.45, 0.0), 7.0, 0)
        for piece in self.active_pieces:
            obj = self._draw_piece_with_fallback(
                "active",
                piece,
                cur_color,
                cur_width,
                cur_alpha,
                "euSKlidPathSeg",
                "euSKlidPathArc",
            )
            if obj is not None:
                active_objs.append(obj)

        if self.preview_pieces:
            first_piece = self.preview_pieces[0]
            last_piece = self.preview_pieces[-1]
            markers.append((self._piece_start_uv(first_piece), "marker", "euSKlidPathPreviewStart"))
            markers.append((self._piece_end_uv(last_piece), "snap", "euSKlidPathPreviewEnd"))

            cand_color, cand_width, cand_alpha = _path_style("candidate", (0.35, 1.0, 0.35), 5.0, 0)
            for piece in self.preview_pieces:
                obj = self._draw_piece_with_fallback(
                    "preview",
                    piece,
                    cand_color,
                    cand_width,
                    cand_alpha,
                    "euSKlidPathPreviewSeg",
                    "euSKlidPathPreviewArc",
                )
                if obj is not None:
                    preview_objs.append(obj)

        global _PATH_ACTIVE_OBJECTS, _PATH_PREVIEW_OBJECTS
        _PATH_ACTIVE_OBJECTS = active_objs
        _PATH_PREVIEW_OBJECTS = preview_objs
        self._show_markers(markers)
        _path_request_redraw()

    def render_preview(self):
        self.render_all()

    def render_active(self):
        self.render_all()

    def freeze_closed(self):
        global _CLOSED_PATHS, _PATH_CLOSED_OBJECTS
        if not self.active_pieces:
            return
        entity_meta = {}
        try:
            for i, ent in enumerate(self.entities):
                entity_meta[i] = dict(getattr(ent, "meta", {}) or {})
        except Exception:
            entity_meta = {}

        record = {
            "plane": self.plane,
            "pieces": list(self.active_pieces),
            "entity_meta": entity_meta,
        }
        _CLOSED_PATHS.append(record)
        objs = []
        for piece in self.active_pieces:
            if piece["type"] == "segment":
                closed_color, closed_width, closed_alpha = _path_style("closed", (0.0, 0.45, 0.0), 6.0, 0)
                obj = _make_line_segment(self.plane, piece["a"], piece["b"], color=closed_color, width=closed_width, transparency=closed_alpha, name="euSKlidClosedPathSeg")
            else:
                a0 = piece["a0"]
                a1 = piece["a1"]
                if piece["delta"] < 0.0:
                    a0, a1 = a1, a0
                closed_color, closed_width, closed_alpha = _path_style("closed", (0.0, 0.45, 0.0), 6.0, 0)
                obj = _make_arc_segment(self.plane, piece["center"], piece["radius"], a0, a1, color=closed_color, width=closed_width, transparency=closed_alpha, name="euSKlidClosedPathArc")
            if obj is not None:
                objs.append(obj)
        try:
            doc = App.ActiveDocument
            if doc is not None:
                ensure_euclid_groups(doc)
                grp = get_path_group(doc)
                for o in objs:
                    if o is not None:
                        try:
                            add_to_group(o, grp)
                        except Exception:
                            pass
        except Exception:
            pass

        _PATH_CLOSED_OBJECTS.extend(objs)
        clear_path_active()
        clear_path_preview()
        clear_path_markers()

    def process_click(self, sub_name, click_uv):
        entity_idx, ent = self.entity_from_subname(sub_name)
        if ent is None:
            App.Console.PrintError("euSKlid Path: invalid selected entity\n")
            return
        target = self.project_on_entity(entity_idx, click_uv)
        if self.current_entity_idx is None:
            self.start_entity_idx = entity_idx
            self.start_point = target
            self.current_entity_idx = entity_idx
            self.current_point = target
            self.current_direction = None
            self.active_pieces = []
            self.preview_pieces = []
            self.closed = False
            self.render_active()
            self._push_history()
            return

        old_entity_idx = self.current_entity_idx
        old_direction = self.current_direction

        pieces = self.build_local_route(
            old_entity_idx, self.current_point, old_direction,
            entity_idx, target, click_uv
        )
        if not pieces:
            App.Console.PrintError("euSKlid Path: no valid local path\n")
            return
        self.active_pieces = self.merge_pieces(self.active_pieces + pieces)
        self.preview_pieces = []
        fallback_dir = old_direction if entity_idx == old_entity_idx else None
        self.current_entity_idx = entity_idx
        self.current_point = target
        self.current_direction = self.direction_on_entity(entity_idx, pieces, fallback=fallback_dir)
        self.render_active()
        self._push_history()

    def close(self):
        if self.closed:
            return
        if self.start_entity_idx is None or self.start_point is None or self.current_entity_idx is None:
            App.Console.PrintError("euSKlid Path: nothing to close\n")
            return
        pieces = self.build_local_route(
            self.current_entity_idx, self.current_point, self.current_direction,
            self.start_entity_idx, self.start_point, self.last_mouse_uv
        )
        if not pieces:
            App.Console.PrintError("euSKlid Path: cannot close current path\n")
            return
        self.active_pieces = self.merge_pieces(self.active_pieces + pieces)
        self.closed = True
        self.freeze_closed()

    def export_to_sketcher(self, record=None, target_sketch=None):
        if record is None and not _CLOSED_PATHS:
            App.Console.PrintError("euSKlid Path: no closed path available for export\n")
            return None

        if record is None:
            record = _CLOSED_PATHS[-1]
        plane = record["plane"]
        pieces = record["pieces"]
        record_entity_meta = record.get("entity_meta", {}) or {}

        doc = App.ActiveDocument
        if doc is None:
            return None

        try:
            import Sketcher
        except Exception:
            App.Console.PrintError("euSKlid Path: Sketcher module unavailable\n")
            return None

        # --- helpers -------------------------------------------------------------

        def piece_start(piece):
            if piece["type"] == "segment":
                return piece["a"]
            return (
                piece["center"][0] + piece["radius"] * math.cos(piece["a0"]),
                piece["center"][1] + piece["radius"] * math.sin(piece["a0"]),
            )

        def piece_end(piece):
            if piece["type"] == "segment":
                return piece["b"]
            return (
                piece["center"][0] + piece["radius"] * math.cos(piece["a1"]),
                piece["center"][1] + piece["radius"] * math.sin(piece["a1"]),
            )

        def avg_uv(a, b):
            return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)

        constraint_stats = {
            "added": 0,
            "failed": 0,
        }
        exported_geometry_indices = []
        exported_constraint_indices = []

        def _constraint_count():
            try:
                return len(sk.Constraints)
            except Exception:
                return 0

        def _remember_constraints_from(before_count):
            try:
                after = len(sk.Constraints)
            except Exception:
                return
            for ci in range(int(before_count), int(after)):
                exported_constraint_indices.append(ci)

        def add_constraint_safe(*args):
            before_count = _constraint_count()
            try:
                sk.addConstraint(Sketcher.Constraint(*args))
                _remember_constraints_from(before_count)
                constraint_stats["added"] += 1
                return True
            except Exception as exc:
                constraint_stats["failed"] += 1
                try:
                    elog.info("Export constraint skipped: %s %s" % (args, exc))
                except Exception:
                    pass
                return False

        def add_distance_constraint_safe(geo_index, value):
            # FreeCAD Sketcher APIs have varied; try the common line-length
            # signatures in order.
            for args in (
                ("Distance", geo_index, float(value)),
                ("Distance", geo_index, 1, geo_index, 2, float(value)),
            ):
                before_count = _constraint_count()
                try:
                    sk.addConstraint(Sketcher.Constraint(*args))
                    _remember_constraints_from(before_count)
                    constraint_stats["added"] += 1
                    return True
                except Exception as exc:
                    constraint_stats["failed"] += 1
                    try:
                        elog.info("Export distance skipped: %s %s" % (args, exc))
                    except Exception:
                        pass
            return False

        def add_axial_distance_constraint_safe(geo_index, axis, value):
            # Constrain the projected spacing, not the oblique segment length.
            # axis must be "X" or "Y" and value is an absolute UV projection.
            ctype = "DistanceY" if str(axis).upper() == "Y" else "DistanceX"
            for args in (
                (ctype, geo_index, 1, geo_index, 2, float(value)),
                (ctype, geo_index, float(value)),
            ):
                before_count = _constraint_count()
                try:
                    sk.addConstraint(Sketcher.Constraint(*args))
                    _remember_constraints_from(before_count)
                    constraint_stats["added"] += 1
                    return True
                except Exception as exc:
                    constraint_stats["failed"] += 1
                    try:
                        elog.info("Export axial distance skipped: %s %s" % (args, exc))
                    except Exception:
                        pass
            # Last-resort compatibility fallback: do not fail the export, but
            # keep this visible in the log.
            try:
                elog.info("Export axial distance fallback to Distance for geo %s" % geo_index)
            except Exception:
                pass
            return add_distance_constraint_safe(geo_index, value)

        def source_meta_for_piece(piece):
            try:
                entity = piece.get("entity")
                if entity in record_entity_meta:
                    return dict(record_entity_meta[entity])
                key = str(entity)
                if key in record_entity_meta:
                    return dict(record_entity_meta[key])
            except Exception:
                pass
            return {}

        def line_length_uv(meta):
            try:
                return _dist(meta["start"], meta["end"])
            except Exception:
                return 0.0

        # --- canonisation des jonctions -----------------------------------------
        # On force les jonctions successives à partager exactement le même UV
        # si elles sont suffisamment proches.
        tol_join = max(self.tol() * 20.0, 1e-5)

        canon_pieces = [dict(p) for p in pieces]
        n = len(canon_pieces)

        for i in range(n):
            cur = canon_pieces[i]
            nxt = canon_pieces[(i + 1) % n]

            cur_end = piece_end(cur)
            nxt_start = piece_start(nxt)

            if _dist(cur_end, nxt_start) <= tol_join:
                j = avg_uv(cur_end, nxt_start)

                # réécrit la fin de cur
                if cur["type"] == "segment":
                    cur["b"] = j
                else:
                    cur["a1"] = _angle_on_circle(cur["center"], j)

                # réécrit le début de nxt
                if nxt["type"] == "segment":
                    nxt["a"] = j
                else:
                    nxt["a0"] = _angle_on_circle(nxt["center"], j)

        # Après canonisation, on refusionne proprement
        canon_pieces = self.merge_pieces(canon_pieces)

        # --- création / sélection Sketcher --------------------------------------
        if target_sketch is None:
            sk = doc.addObject("Sketcher::SketchObject", "euSKlidPathExport")
        else:
            sk = target_sketch
            removed = _clear_previous_eusklid_export(sk)
            try:
                elog.info(
                    "Export Path: cleared previous euSKlid export from %s (%d geometry, %d constraints)"
                    % (getattr(sk, "Name", "Sketch"), removed.get("geometries", 0), removed.get("constraints", 0))
                )
            except Exception:
                pass
        normal = App.Vector(plane.normal.x, plane.normal.y, plane.normal.z)

        geom_meta = []

        for piece in canon_pieces:
            if piece["type"] == "segment":
                pa = App.Vector(*plane.uv_to_world(piece["a"]))
                pb = App.Vector(*plane.uv_to_world(piece["b"]))
                idx = sk.addGeometry(Part.LineSegment(pa, pb), False)
                exported_geometry_indices.append(int(idx))
                geom_meta.append({
                    "index": idx,
                    "type": "segment",
                    "entity": piece.get("entity"),
                    "source_meta": source_meta_for_piece(piece),
                    "start": piece["a"],
                    "end": piece["b"],
                })
            else:
                center = App.Vector(*plane.uv_to_world(piece["center"]))
                circle = Part.Circle(center, normal, float(piece["radius"]))

                a0 = piece["a0"]
                a1 = piece["a1"]
                if piece["delta"] < 0.0:
                    a0, a1 = a1, a0

                idx = sk.addGeometry(Part.ArcOfCircle(circle, float(a0), float(a1)), False)
                exported_geometry_indices.append(int(idx))

                geom_meta.append({
                    "index": idx,
                    "type": "arc",
                    "entity": piece.get("entity"),
                    "source_meta": source_meta_for_piece(piece),
                    "center": piece["center"],
                    "radius": float(piece["radius"]),
                    "a0": a0,
                    "a1": a1,
                    "delta": piece["delta"],
                    "start": (
                        piece["center"][0] + piece["radius"] * math.cos(a0),
                        piece["center"][1] + piece["radius"] * math.sin(a0),
                    ),
                    "end": (
                        piece["center"][0] + piece["radius"] * math.cos(a1),
                        piece["center"][1] + piece["radius"] * math.sin(a1),
                    ),
                })

        # --- contraintes ---------------------------------------------------------
        # Constraint export is now delegated to eusklid.export_constraints.
        # The emitter follows the v1 euSKlid policy: topology first, geometric
        # relations second, and only explicit construction dimensions last.
        constraint_result = add_path_constraints(sk, Sketcher, geom_meta, tol_join)
        exported_constraint_indices.extend(constraint_result.get("indices", []))

        _write_export_tag(sk, exported_geometry_indices, exported_constraint_indices, label="path")

        doc.recompute()
        return sk


class _SelectionObserver:
    def __init__(self, session):
        self.session = session

    def _parse_payload(self, *args):
        if len(args) >= 4:
            return args[0], args[1], args[2], args[3]
        if len(args) == 3:
            return args[0], args[1], args[2], None
        return None, None, None, None

    def addSelection(self, *args):
        try:
            try:
                if time.time() < getattr(self.session, "_ignore_selection_until", 0.0):
                    try:
                        Gui.Selection.clearSelection()
                    except Exception:
                        pass
                    return
            except Exception:
                pass
            doc_name, obj_name, sub_name, pnt = self._parse_payload(*args)
            if obj_name != self.session.sketch_obj.Name:
                return
            if not sub_name or not sub_name.startswith("Edge"):
                return
            entity_idx, ent = self.session.entity_from_subname(sub_name)
            if ent is None:
                return
            click_uv = None
            if self.session.last_mouse_uv is not None:
                click_uv = self.session.last_mouse_uv
            elif pnt is not None and hasattr(pnt, "x"):
                try:
                    click_uv = self.session.plane.world_to_uv((float(pnt.x), float(pnt.y), float(pnt.z)))
                except Exception:
                    click_uv = None
            if click_uv is None:
                click_uv = self.session.fallback_point_on_entity(entity_idx)
            self.session.process_click(sub_name, click_uv)
            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass
        except Exception as e:
            App.Console.PrintError("euSKlid Path observer error: %s\n" % str(e))

    def removeSelection(self, *args):
        pass

    def setSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass


def new_path_session():
    global _ACTIVE_PATH_SESSION
    stop_path_session()
    sketch_obj = get_or_create_euclid_sketch()
    _ACTIVE_PATH_SESSION = PathSession(sketch_obj)
    return _ACTIVE_PATH_SESSION


def close_path_session():
    global _ACTIVE_PATH_SESSION
    if _ACTIVE_PATH_SESSION is not None:
        _ACTIVE_PATH_SESSION.close()
        if _ACTIVE_PATH_SESSION.closed:
            try:
                _ACTIVE_PATH_SESSION.finish()
            except Exception:
                pass
            _ACTIVE_PATH_SESSION = None


def _closed_path_label(index, record):
    try:
        pieces = record.get("pieces", [])
        return "Path %d — %d piece(s)" % (index + 1, len(pieces))
    except Exception:
        return "Path %d" % (index + 1)


def _sketcher_objects(doc):
    out = []
    if doc is None:
        return out
    for obj in getattr(doc, "Objects", []):
        try:
            if getattr(obj, "TypeId", "") == "Sketcher::SketchObject":
                out.append(obj)
        except Exception:
            pass
    return out


class _PathExportDialog(QtWidgets.QDialog):
    def __init__(self, paths, sketches, parent=None, active_sketch=None):
        super(_PathExportDialog, self).__init__(parent)
        self.setWindowTitle("Export Path")
        self.paths = list(paths)
        self.sketches = list(sketches)
        self.active_sketch = active_sketch
        self._checks = []

        layout = QtWidgets.QVBoxLayout(self)

        group_paths = QtWidgets.QGroupBox("Paths")
        v_paths = QtWidgets.QVBoxLayout(group_paths)
        for i, record in enumerate(self.paths):
            cb = QtWidgets.QCheckBox(_closed_path_label(i, record))
            cb.setChecked(i == len(self.paths) - 1)
            v_paths.addWidget(cb)
            self._checks.append(cb)
        layout.addWidget(group_paths)

        group_mode = QtWidgets.QGroupBox("Target")
        v_mode = QtWidgets.QVBoxLayout(group_mode)
        self.rb_new = QtWidgets.QRadioButton("New Sketch")
        self.rb_existing = QtWidgets.QRadioButton("Existing Sketch")
        self.rb_new.setChecked(active_sketch is None)
        self.rb_existing.setChecked(active_sketch is not None)

        row_existing = QtWidgets.QHBoxLayout()
        row_existing.addWidget(self.rb_existing)
        self.combo = QtWidgets.QComboBox()
        active_index = -1
        for i, sk in enumerate(self.sketches):
            label = getattr(sk, "Label", getattr(sk, "Name", "Sketch"))
            if active_sketch is not None and sk is active_sketch:
                label = "%s  [active]" % label
                active_index = i
            self.combo.addItem(label, sk)
        if active_index >= 0:
            self.combo.setCurrentIndex(active_index)
        self.combo.setEnabled(active_sketch is not None)
        row_existing.addWidget(self.combo)

        v_mode.addWidget(self.rb_new)
        v_mode.addLayout(row_existing)
        layout.addWidget(group_mode)

        self.rb_existing.toggled.connect(self.combo.setEnabled)
        if not self.sketches:
            self.rb_existing.setEnabled(False)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_records(self):
        return [record for cb, record in zip(self._checks, self.paths) if cb.isChecked()]

    def target_sketch(self):
        if not self.rb_existing.isChecked():
            return None
        try:
            return self.combo.itemData(self.combo.currentIndex())
        except Exception:
            return None


def export_path_to_sketcher():
    global _ACTIVE_PATH_SESSION

    if _ACTIVE_PATH_SESSION is not None and _ACTIVE_PATH_SESSION.closed:
        try:
            _ACTIVE_PATH_SESSION.finish()
        except Exception:
            pass
        _ACTIVE_PATH_SESSION = None

    if not _CLOSED_PATHS:
        App.Console.PrintError("euSKlid Path: no closed path available for export\n")
        return None

    doc = App.ActiveDocument
    if doc is None:
        return None

    paths = list(_CLOSED_PATHS)
    sketches = _sketcher_objects(doc)
    active_sketch = _active_edit_sketch()

    if len(paths) == 1 and active_sketch is not None:
        dummy = PathSession(get_or_create_euclid_sketch())
        try:
            dummy.finish()
        except Exception:
            pass
        return dummy.export_to_sketcher(record=paths[0], target_sketch=active_sketch)

    if len(paths) == 1 and not sketches:
        dummy = PathSession(get_or_create_euclid_sketch())
        try:
            dummy.finish()
        except Exception:
            pass
        return dummy.export_to_sketcher(record=paths[0], target_sketch=None)

    dlg = _PathExportDialog(paths, sketches, active_sketch=active_sketch)
    if not dlg.exec_():
        return None

    selected = dlg.selected_records()
    if not selected:
        App.Console.PrintError("euSKlid Path: no path selected for export\n")
        return None

    target = dlg.target_sketch()
    created_or_target = target
    dummy = PathSession(get_or_create_euclid_sketch())
    try:
        dummy.finish()
    except Exception:
        pass

    elog.info("Export Path: exporting %d path(s) to %s" % (
        len(selected),
        "existing sketch" if target is not None else "new sketch",
    ))

    for i, record in enumerate(selected):
        sk = dummy.export_to_sketcher(record=record, target_sketch=created_or_target)
        if sk is not None and created_or_target is None:
            created_or_target = sk

    return created_or_target
def stop_path_session(clear_closed=False):
    global _ACTIVE_PATH_SESSION, _PATH_CLOSED_OBJECTS
    if _ACTIVE_PATH_SESSION is not None:
        try:
            _ACTIVE_PATH_SESSION.finish()
        except Exception:
            pass
    _ACTIVE_PATH_SESSION = None

    try:
        clear_path_preview()
    except Exception:
        pass
    try:
        clear_path_markers()
    except Exception:
        pass
    try:
        clear_path_active()
    except Exception:
        pass

    if clear_closed:
        try:
            _PATH_CLOSED_OBJECTS = _remove_objects(_PATH_CLOSED_OBJECTS)
        except Exception:
            pass



def refresh_path_visuals():
    """Refresh visible Path overlays and closed path styling after config changes."""
    try:
        if _ACTIVE_PATH_SESSION is not None:
            _ACTIVE_PATH_SESSION.render_all()
    except Exception:
        pass

    try:
        closed_color, closed_width, closed_alpha = _path_style("closed", (0.0, 0.45, 0.0), 6.0, 0)
        for obj in list(_PATH_CLOSED_OBJECTS):
            try:
                vo = getattr(obj, "ViewObject", None)
                if vo is None:
                    continue
                vo.LineColor = closed_color
                vo.ShapeColor = closed_color
                vo.PointColor = closed_color
                vo.LineWidth = closed_width
                vo.Transparency = closed_alpha
            except Exception:
                pass
    except Exception:
        pass

    try:
        _path_request_redraw()
    except Exception:
        pass

def has_active_path_session():
    return _ACTIVE_PATH_SESSION is not None


def undo_path_session():
    if _ACTIVE_PATH_SESSION is None:
        return False
    return _ACTIVE_PATH_SESSION.undo_last_point()
