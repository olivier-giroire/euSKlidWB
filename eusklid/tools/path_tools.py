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
from ..runtime import get_or_create_euclid_sketch, get_data, set_data
from ..core.groups import ensure_euclid_groups, get_path_group, get_transient_group, ensure_path_instance_group, add_to_group
from ..core.config import get_config, get_overload_color, get_overload_style
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


def _refresh_exported_sketch_now(sk, doc):
    """Force FreeCAD/Sketcher to refresh solver state after generated export."""
    try:
        sk.solve()
    except Exception:
        pass
    try:
        sk.touch()
    except Exception:
        pass
    try:
        doc.recompute()
    except Exception:
        pass
    try:
        sk.solve()
    except Exception:
        pass
    try:
        doc.recompute()
    except Exception:
        pass

    try:
        Gui.ActiveDocument.ActiveView.redraw()
    except Exception:
        pass


def _refresh_exported_sketch(sk, doc):
    _refresh_exported_sketch_now(sk, doc)

_PATH_ACTIVE_OBJECTS = []
_PATH_PREVIEW_OBJECTS = []
_PATH_MARKER_OBJECTS = []
_PATH_CLOSED_OBJECTS = []

# Coin3D transient Path overlays. Document objects are kept only for closed paths.
_PATH_OVERLAY_ROOTS = {}

_CLOSED_PATHS = []
_ACTIVE_PATH_SESSION = None
_ACTIVE_OVERLOAD_SESSION = None
_ACTIVE_OVERLOAD_EDIT = None



def _path_record_id(index):
    return "path_%03d" % int(index + 1)


def _path_record_label(index):
    return "Path%03d" % int(index + 1)


def _plane_to_storage(plane):
    try:
        return plane.to_dict()
    except Exception:
        return {"name": "XY"}


def _plane_from_storage(value):
    try:
        from ..plane import SketchPlane
        if isinstance(value, SketchPlane):
            return value
        return SketchPlane.XY()
    except Exception:
        return None


def _path_piece_to_storage(piece):
    out = dict(piece or {})
    for key in ("a", "b", "center"):
        if key in out and out[key] is not None:
            try:
                out[key] = [float(out[key][0]), float(out[key][1])]
            except Exception:
                pass
    for key in ("radius", "a0", "a1", "delta"):
        if key in out:
            try:
                out[key] = float(out[key])
            except Exception:
                pass
    return out


def _path_piece_from_storage(piece):
    out = dict(piece or {})
    for key in ("a", "b", "center"):
        if key in out and out[key] is not None:
            try:
                out[key] = (float(out[key][0]), float(out[key][1]))
            except Exception:
                pass
    for key in ("radius", "a0", "a1", "delta"):
        if key in out:
            try:
                out[key] = float(out[key])
            except Exception:
                pass
    return out


def _path_record_to_storage(record):
    rec = dict(record or {})
    rec["plane"] = _plane_to_storage(rec.get("plane"))
    rec["pieces"] = [_path_piece_to_storage(p) for p in rec.get("pieces", [])]
    rec["entity_meta"] = rec.get("entity_meta", {}) or {}
    rec["overloads"] = list(rec.get("overloads", []) or [])
    return rec


def _path_record_from_storage(record):
    rec = dict(record or {})
    rec["plane"] = _plane_from_storage(rec.get("plane"))
    rec["pieces"] = [_path_piece_from_storage(p) for p in rec.get("pieces", [])]
    rec["entity_meta"] = rec.get("entity_meta", {}) or {}
    rec["overloads"] = list(rec.get("overloads", []) or [])
    return rec


def _sync_closed_paths_to_sketch(sketch_obj=None):
    try:
        sketch_obj = sketch_obj or get_or_create_euclid_sketch()
        data = get_data(sketch_obj)
        data.paths = [_path_record_to_storage(r) for r in _CLOSED_PATHS]
        set_data(sketch_obj, data)
    except Exception as e:
        App.Console.PrintError("euSKlid Path: cannot save closed paths: %s\n" % str(e))


def restore_closed_paths_from_sketch(sketch_obj=None, redraw_missing=False):
    """Reload persisted closed paths from SketchJson into the runtime cache.

    The FreeCAD document stores the visible objects; this routine restores the
    semantic path records needed by export dialogs after reopening a document.
    If redraw_missing is true, it also creates missing per-path groups/objects.
    """
    global _CLOSED_PATHS, _PATH_CLOSED_OBJECTS
    try:
        sketch_obj = sketch_obj or get_or_create_euclid_sketch()
        data = get_data(sketch_obj)
        paths = getattr(data, "paths", []) or []
        _CLOSED_PATHS = [_path_record_from_storage(r) for r in paths if isinstance(r, dict)]
        if redraw_missing:
            _PATH_CLOSED_OBJECTS = []
            for idx, record in enumerate(_CLOSED_PATHS):
                _draw_closed_path_record(record, idx)
        return list(_CLOSED_PATHS)
    except Exception as e:
        App.Console.PrintError("euSKlid Path: cannot restore closed paths: %s\n" % str(e))
        return []


def _ensure_closed_paths_loaded():
    if not _CLOSED_PATHS:
        restore_closed_paths_from_sketch(redraw_missing=False)
    return list(_CLOSED_PATHS)



def _make_overload_polyline(plane, uv_points, color, width=5.0, transparency=0, name="euSKlidOverloadPortion", group=None):
    """Create a non-selectable visual overload polyline from UV points.

    Overloads are visual intent markers.  They should mark exactly the portion
    selected by the user, not necessarily the whole underlying Path piece.
    """
    doc = App.ActiveDocument
    if doc is None or plane is None or not hasattr(plane, "uv_to_world"):
        return None
    pts = []
    try:
        for uv in uv_points or []:
            if uv is None:
                continue
            pts.append(App.Vector(*plane.uv_to_world((float(uv[0]), float(uv[1])))))
    except Exception:
        pts = []
    if len(pts) < 2:
        return None
    try:
        ensure_euclid_groups(doc)
    except Exception:
        pass
    obj = doc.addObject("Part::Feature", name)
    try:
        grp = group if group is not None else get_path_group(doc)
        add_to_group(obj, grp)
    except Exception:
        pass
    try:
        obj.Shape = Part.makePolygon(pts)
    except Exception:
        try:
            obj.Shape = Part.makeLine(pts[0], pts[-1])
        except Exception:
            return None
    try:
        obj.ViewObject.LineColor = color
        obj.ViewObject.PointColor = color
        obj.ViewObject.LineWidth = width
        obj.ViewObject.Transparency = transparency
        obj.ViewObject.Selectable = False
    except Exception:
        pass
    return obj


def _piece_length(piece):
    try:
        if piece.get("type") == "segment":
            return _dist(piece.get("a"), piece.get("b"))
        return abs(float(piece.get("delta", 0.0))) * abs(float(piece.get("radius", 0.0)))
    except Exception:
        return 0.0


def _piece_point_at_t(piece, t):
    t = max(0.0, min(1.0, float(t)))
    try:
        if piece.get("type") == "segment":
            a = piece.get("a")
            b = piece.get("b")
            return (float(a[0]) + (float(b[0]) - float(a[0])) * t, float(a[1]) + (float(b[1]) - float(a[1])) * t)
        c = piece.get("center")
        r = float(piece.get("radius"))
        a = float(piece.get("a0")) + float(piece.get("delta", 0.0)) * t
        return (float(c[0]) + r * math.cos(a), float(c[1]) + r * math.sin(a))
    except Exception:
        return None


def _piece_center_uv(piece):
    try:
        if piece.get("type") in {"arc", "circle"}:
            c = piece.get("center")
            return (float(c[0]), float(c[1]))
    except Exception:
        pass
    return None


def _piece_portion_uv_points(piece, t0, t1):
    try:
        t0 = max(0.0, min(1.0, float(t0)))
        t1 = max(0.0, min(1.0, float(t1)))
        if piece.get("type") == "segment":
            return [_piece_point_at_t(piece, t0), _piece_point_at_t(piece, t1)]
        steps = max(4, min(96, int(abs(t1 - t0) * abs(float(piece.get("delta", 0.0))) * 24.0) + 4))
        return [_piece_point_at_t(piece, t0 + (t1 - t0) * i / float(steps)) for i in range(steps + 1)]
    except Exception:
        return []


def _project_uv_to_piece(piece, uv):
    """Return a clicked point projected to the path piece as {'uv':..., 't':...}."""
    try:
        if uv is None:
            return {"uv": _piece_point_at_t(piece, 0.5), "t": 0.5}
        x, y = float(uv[0]), float(uv[1])
        if piece.get("type") == "segment":
            a = piece.get("a")
            b = piece.get("b")
            ax, ay = float(a[0]), float(a[1])
            bx, by = float(b[0]), float(b[1])
            vx, vy = bx - ax, by - ay
            den = vx * vx + vy * vy
            t = 0.5 if den <= 1e-18 else ((x - ax) * vx + (y - ay) * vy) / den
            t = max(0.0, min(1.0, t))
            return {"uv": _piece_point_at_t(piece, t), "t": float(t)}
        # Arc projection: robust sampled closest parameter along the directed arc.
        best_t, best_d = 0.5, None
        steps = 96
        for i in range(steps + 1):
            t = i / float(steps)
            p = _piece_point_at_t(piece, t)
            if p is None:
                continue
            d = (float(p[0]) - x) ** 2 + (float(p[1]) - y) ** 2
            if best_d is None or d < best_d:
                best_d = d
                best_t = t
        return {"uv": _piece_point_at_t(piece, best_t), "t": float(best_t)}
    except Exception:
        return {"uv": _piece_point_at_t(piece, 0.5), "t": 0.5}


def _range_portions_between_points(record, start, end):
    """Return the shortest directed portions between two piece points.

    Each portion is (piece_index, t0, t1).  t can decrease for reverse travel.
    """
    pieces = record.get("pieces", []) or []
    n = len(pieces)
    if n <= 0:
        return []
    try:
        i0 = int(start.get("piece"))
        i1 = int(end.get("piece"))
        t0 = float(start.get("t", 0.0))
        t1 = float(end.get("t", 1.0))
    except Exception:
        return []

    def build_forward(a_idx, a_t, b_idx, b_t):
        out = []
        total = 0.0
        idx = a_idx
        while True:
            piece = pieces[idx]
            if idx == a_idx and idx == b_idx:
                if b_t >= a_t:
                    out.append((idx, a_t, b_t))
                    total += _piece_length(piece) * abs(b_t - a_t)
                    return out, total
                # same piece but forward wraps around: first a_t->1 then later 0->b_t
                out.append((idx, a_t, 1.0))
                total += _piece_length(piece) * abs(1.0 - a_t)
            elif idx == a_idx:
                out.append((idx, a_t, 1.0))
                total += _piece_length(piece) * abs(1.0 - a_t)
            elif idx == b_idx:
                out.append((idx, 0.0, b_t))
                total += _piece_length(piece) * abs(b_t - 0.0)
                return out, total
            else:
                out.append((idx, 0.0, 1.0))
                total += _piece_length(piece)
            idx = (idx + 1) % n
            if idx == a_idx:
                return out, total

    fwd, fwd_len = build_forward(i0, t0, i1, t1)
    rev, rev_len = build_forward(i1, t1, i0, t0)
    # Reverse the reverse trip so portions are still ordered from user click A to B.
    rev = [(pi, b, a) for (pi, a, b) in reversed(rev)]
    return fwd if fwd_len <= rev_len else rev


def _pieces_from_portions(portions):
    vals = []
    for pi, _t0, _t1 in portions or []:
        try:
            if int(pi) not in vals:
                vals.append(int(pi))
        except Exception:
            pass
    return vals


def _path_draw_overload_marker(layer, plane, uv, group=None):
    """Draw an overload marker as a true circular screen-scale ring.

    No SoPointSet is used here because OpenGL points render as squares on many
    drivers. The ring remains visually stable because it is recomputed at each
    redraw.
    """
    try:
        color, _width, alpha = _path_overload_style()
        return _path_draw_marker_circle(layer, plane, uv, color, alpha, size_px=_path_point_size(), width_px=2.0)
    except Exception:
        return False


def _make_overload_marker(plane, uv, group=None, name="euSKlidOverloadPoint"):
    """Create a visible endpoint marker for an overload range."""
    try:
        if _path_draw_overload_marker("overloads", plane, uv, group=group):
            return None
    except Exception:
        pass
    doc = App.ActiveDocument
    if doc is None or plane is None or uv is None or not hasattr(plane, "uv_to_world"):
        return None
    try:
        color, width, alpha = _path_overload_style()
        # Keep markers readable, but avoid huge balls when line width is high.
        radius = max(_path_pixels_to_world(plane, uv, max(5.0, float(width) * 1.6)), 1e-6)
        center = App.Vector(*plane.uv_to_world((float(uv[0]), float(uv[1]))))
        obj = doc.addObject("Part::Feature", name)
        try:
            grp = group if group is not None else get_path_group(doc)
            add_to_group(obj, grp)
        except Exception:
            pass
        obj.Shape = Part.makeSphere(float(radius), center)
        try:
            obj.ViewObject.ShapeColor = color
            obj.ViewObject.LineColor = color
            obj.ViewObject.PointColor = color
            obj.ViewObject.Transparency = alpha
            obj.ViewObject.Selectable = False
        except Exception:
            pass
        return obj
    except Exception:
        return None


def _draw_overload_portions(record, portions, group=None):
    objs = []
    plane = record.get("plane")
    if plane is None or not hasattr(plane, "uv_to_world"):
        return objs
    color, width, alpha = _path_overload_style()
    for pi, t0, t1 in portions or []:
        try:
            piece = (record.get("pieces", []) or [])[int(pi)]
            uv_points = _piece_portion_uv_points(piece, t0, t1)
            obj = _make_overload_polyline(plane, uv_points, color=color, width=width, transparency=alpha, group=group)
            if obj is not None:
                objs.append(obj)
        except Exception:
            pass
    return objs



def _piece_tangent_dir_at_t(piece, t):
    """Unit tangent direction for a path piece at parameter t."""
    try:
        t = max(0.0, min(1.0, float(t)))
        if piece.get("type") == "segment":
            a = piece.get("a")
            b = piece.get("b")
            return _normalize((float(b[0]) - float(a[0]), float(b[1]) - float(a[1])))
        a = float(piece.get("a0")) + float(piece.get("delta", 0.0)) * t
        sign = 1.0 if float(piece.get("delta", 0.0)) >= 0.0 else -1.0
        return _normalize((-math.sin(a) * sign, math.cos(a) * sign))
    except Exception:
        return (0.0, 0.0)


def _path_draw_overload_tangent_glyph(layer, plane, uv, direction, group=None):
    """Draw a short local tangent glyph centered on uv."""
    if coin is None:
        return False
    root = _path_overlay_root(layer)
    if root is None or uv is None or direction is None or plane is None or not hasattr(plane, "uv_to_world"):
        return False
    try:
        color, width, alpha = _path_overload_style()
        d = _normalize((float(direction[0]), float(direction[1])))
        if abs(d[0]) + abs(d[1]) <= 1e-12:
            return False

        px = max(float(_path_point_size()) * 1.20, 10.0)
        half = _path_pixels_to_world(plane, uv, px * 0.5)

        p0 = (float(uv[0]) - d[0] * half, float(uv[1]) - d[1] * half)
        p1 = (float(uv[0]) + d[0] * half, float(uv[1]) + d[1] * half)

        w0 = App.Vector(*plane.uv_to_world(p0))
        w1 = App.Vector(*plane.uv_to_world(p1))

        sep = coin.SoSeparator()
        sep.addChild(_path_material(color, alpha))

        draw = coin.SoDrawStyle()
        draw.lineWidth.setValue(max(1.0, float(width)))
        sep.addChild(draw)

        coords = coin.SoCoordinate3()
        coords.point.setValues(0, 2, [
            (float(w0.x), float(w0.y), float(w0.z)),
            (float(w1.x), float(w1.y), float(w1.z)),
        ])
        sep.addChild(coords)

        line = coin.SoLineSet()
        line.numVertices.set1Value(0, 2)
        sep.addChild(line)

        root.addChild(sep)
        return True
    except Exception:
        return False


def _render_tangent_overload(record, range_data, group=None):
    """Render tangent overload as a local semantic event only.

    Tangency is an event at the arc/segment junction. Do not draw the selected
    range, clicked endpoints, or full pieces for this overload kind.
    """
    objs = []
    range_data = range_data or {}
    plane = record.get("plane")
    pieces = record.get("pieces", []) or []
    if plane is None or not hasattr(plane, "uv_to_world") or not pieces:
        return objs

    portions = list(range_data.get("portions", []) or [])
    if len(portions) < 2:
        return objs

    def _junction_score(prev_portion, next_portion):
        try:
            pi0, _t00, t01 = prev_portion
            pi1, t10, _t11 = next_portion
            p0 = pieces[int(pi0)]
            p1 = pieces[int(pi1)]
            types = {str(p0.get("type")), str(p1.get("type"))}
            type_score = 3.0 if types == {"arc", "segment"} else 0.5
            d0 = _piece_tangent_dir_at_t(p0, float(t01))
            d1 = _piece_tangent_dir_at_t(p1, float(t10))
            align = abs(float(d0[0]) * float(d1[0]) + float(d0[1]) * float(d1[1]))
            # Prefer real piece boundaries: t01 close to 0/1 and t10 close to 0/1.
            boundary = max(abs(float(t01) - 0.0), abs(float(t01) - 1.0)) + max(abs(float(t10) - 0.0), abs(float(t10) - 1.0))
            return type_score + align + 0.25 * boundary
        except Exception:
            return 0.0

    best_i = None
    best_score = -1.0
    for i in range(len(portions) - 1):
        sc = _junction_score(portions[i], portions[i + 1])
        if sc > best_score:
            best_score = sc
            best_i = i

    if best_i is None:
        return objs

    try:
        pi0, _t00, t01 = portions[best_i]
        pi1, t10, _t11 = portions[best_i + 1]
        piece0 = pieces[int(pi0)]
        piece1 = pieces[int(pi1)]

        j0 = _piece_point_at_t(piece0, float(t01))
        j1 = _piece_point_at_t(piece1, float(t10))
        if j0 is None and j1 is None:
            return objs
        if j0 is not None and j1 is not None:
            j = ((float(j0[0]) + float(j1[0])) * 0.5, (float(j0[1]) + float(j1[1])) * 0.5)
        else:
            j = j0 if j0 is not None else j1

        marker = _make_overload_marker(plane, j, group=group, name="euSKlidOverloadTangentPoint")
        if marker is not None:
            objs.append(marker)

        d0 = _piece_tangent_dir_at_t(piece0, float(t01))
        d1 = _piece_tangent_dir_at_t(piece1, float(t10))

        _path_draw_overload_tangent_glyph("overloads", plane, j, d0, group=group)
        _path_draw_overload_tangent_glyph("overloads", plane, j, d1, group=group)

        return objs
    except Exception:
        return objs



def _segment_direction_uv(piece):
    """Return a normalized segment direction in UV coordinates, or None."""
    try:
        if (piece or {}).get("type") != "segment":
            return None
        a = piece.get("a")
        b = piece.get("b")
        dx = float(b[0]) - float(a[0])
        dy = float(b[1]) - float(a[1])
        ln = math.hypot(dx, dy)
        if ln <= 1e-12:
            return None
        return (dx / ln, dy / ln)
    except Exception:
        return None


def _piece_midpoint_uv(piece):
    try:
        return _piece_point_at_t(piece, 0.5)
    except Exception:
        return None


def _draw_colinearity_axis_glyph(record, piece_index, group=None):
    """Draw a small double axial mark on a segment.

    It deliberately differs from tangent overloads:
    - the segment itself is highlighted;
    - a compact double slash/axis glyph is drawn near its midpoint.
    """
    try:
        pieces = record.get("pieces", []) or []
        piece = pieces[int(piece_index)]
        plane = record.get("plane")
        if plane is None or not hasattr(plane, "uv_to_world"):
            return []
        direction = _segment_direction_uv(piece)
        mid = _piece_midpoint_uv(piece)
        if direction is None or mid is None:
            return []
        ux, uy = direction
        # Normal to the segment, used to make two short parallel axial marks.
        nx, ny = -uy, ux

        color, width, alpha = _path_overload_style()
        objs = []

        # Scale in UV units.  This is intentionally conservative because the
        # main segment highlight already carries the overload.
        length = max(0.08, min(0.35, _piece_length(piece) * 0.18))
        gap = max(0.035, min(0.12, _piece_length(piece) * 0.05))
        half = length * 0.5

        centers = [
            (float(mid[0]) - nx * gap, float(mid[1]) - ny * gap),
            (float(mid[0]) + nx * gap, float(mid[1]) + ny * gap),
        ]

        for cx, cy in centers:
            p0 = (cx - ux * half, cy - uy * half)
            p1 = (cx + ux * half, cy + uy * half)
            obj = _make_overload_polyline(
                plane,
                [p0, p1],
                color=color,
                width=max(width + 1.0, 4.0),
                transparency=alpha,
                name="euSKlidOverloadColinearityGlyph",
                group=group,
            )
            if obj is not None:
                objs.append(obj)
        return objs
    except Exception:
        return []


def _render_colinearity_overload(record, pieces, group=None):
    """Render Preserve Colinearity as highlighted segments plus axial glyphs."""
    objs = []
    try:
        for pi in pieces or []:
            try:
                obj = _draw_overload_piece(record, int(pi), group=group)
                if obj is not None:
                    objs.append(obj)
                objs.extend(_draw_colinearity_axis_glyph(record, int(pi), group=group))
            except Exception:
                pass
    except Exception:
        pass
    return objs



def _point_close_uv(a, b, tol=1e-7):
    try:
        return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1])) <= tol
    except Exception:
        return False


def _segment_endpoints_uv(piece):
    try:
        if (piece or {}).get("type") != "segment":
            return None
        a = piece.get("a")
        b = piece.get("b")
        return ((float(a[0]), float(a[1])), (float(b[0]), float(b[1])))
    except Exception:
        return None


def _angle_vectors_for_segments(piece_a, piece_b):
    """Return (vertex, v1, v2) for two segments.

    Prefer a real shared endpoint.  If the two segments do not touch, use the
    midpoint of the first segment as a visual anchor and the two segment
    directions as the displayed angle.
    """
    try:
        ends_a = _segment_endpoints_uv(piece_a)
        ends_b = _segment_endpoints_uv(piece_b)
        if ends_a is None or ends_b is None:
            return None

        a0, a1 = ends_a
        b0, b1 = ends_b

        shared = None
        other_a = None
        other_b = None
        for pa, oa in ((a0, a1), (a1, a0)):
            for pb, ob in ((b0, b1), (b1, b0)):
                if _point_close_uv(pa, pb):
                    shared = pa
                    other_a = oa
                    other_b = ob
                    break
            if shared is not None:
                break

        if shared is not None:
            v1 = (float(other_a[0]) - float(shared[0]), float(other_a[1]) - float(shared[1]))
            v2 = (float(other_b[0]) - float(shared[0]), float(other_b[1]) - float(shared[1]))
            return (shared, v1, v2)

        mid = _piece_midpoint_uv(piece_a)
        d1 = _segment_direction_uv(piece_a)
        d2 = _segment_direction_uv(piece_b)
        if mid is None or d1 is None or d2 is None:
            return None
        return (mid, d1, d2)
    except Exception:
        return None


def _angle_value_for_piece_pair(record, piece_a_index, piece_b_index):
    """Return the signed displayed/user-intended angle value in radians."""
    try:
        pieces = record.get("pieces", []) or []
        piece_a = pieces[int(piece_a_index)]
        piece_b = pieces[int(piece_b_index)]
        data = _angle_vectors_for_segments(piece_a, piece_b)
        if data is None:
            return None
        _vertex, v1, v2 = data
        l1 = math.hypot(float(v1[0]), float(v1[1]))
        l2 = math.hypot(float(v2[0]), float(v2[1]))
        if l1 <= 1e-9 or l2 <= 1e-9:
            return None
        dot = (float(v1[0]) * float(v2[0]) + float(v1[1]) * float(v2[1])) / (l1 * l2)
        cross = (float(v1[0]) * float(v2[1]) - float(v1[1]) * float(v2[0])) / (l1 * l2)
        dot = max(-1.0, min(1.0, dot))
        cross = max(-1.0, min(1.0, cross))
        value = math.atan2(cross, dot)
        if abs(value) <= 1e-9:
            return None
        return float(value)
    except Exception:
        return None


def _angle_ref_for_selection(record, piece_index, click_uv=None):
    try:
        pieces = record.get("pieces", []) or []
        piece = pieces[int(piece_index)]
        if click_uv is None:
            return {
                "kind": "segment",
                "piece": int(piece_index),
                "uv": None,
                "t": 0.5,
            }
        projected = _project_uv_to_piece(piece, click_uv)
        uv = projected.get("uv")
        t = float(projected.get("t", 0.5))
        point_id = 1 if t <= 0.5 else 2
        return {
            "kind": "segment",
            "piece": int(piece_index),
            "uv": uv,
            "t": float(t),
            "point_id": int(point_id),
        }
    except Exception:
        return {
            "kind": "segment",
            "piece": int(piece_index),
            "uv": click_uv,
            "t": 0.5,
        }


def _draw_angle_arc_glyph(record, piece_a_index, piece_b_index, group=None):
    """Draw a compact angle arc between two straight segment directions."""
    try:
        pieces = record.get("pieces", []) or []
        piece_a = pieces[int(piece_a_index)]
        piece_b = pieces[int(piece_b_index)]
        plane = record.get("plane")
        if plane is None or not hasattr(plane, "uv_to_world"):
            return []

        data = _angle_vectors_for_segments(piece_a, piece_b)
        if data is None:
            return []
        vertex, v1, v2 = data

        a1 = math.atan2(float(v1[1]), float(v1[0]))
        a2 = math.atan2(float(v2[1]), float(v2[0]))
        delta = (a2 - a1 + math.pi * 2.0) % (math.pi * 2.0)
        if delta > math.pi:
            delta = delta - math.pi * 2.0

        if abs(delta) <= 1e-6:
            return []

        # Radius follows local segment size but stays modest.
        l1 = _piece_length(piece_a)
        l2 = _piece_length(piece_b)
        base = max(0.001, min(l1 if l1 > 0 else 1.0, l2 if l2 > 0 else 1.0))
        radius = max(0.10, min(0.45, base * 0.30))

        steps = max(8, min(32, int(abs(delta) / (math.pi / 24.0)) + 3))
        pts = []
        for i in range(steps + 1):
            t = i / float(steps)
            a = a1 + delta * t
            pts.append((float(vertex[0]) + radius * math.cos(a), float(vertex[1]) + radius * math.sin(a)))

        color, width, alpha = _path_overload_style()
        objs = []

        arc = _make_overload_polyline(
            plane,
            pts,
            color=color,
            width=max(width + 1.0, 4.0),
            transparency=alpha,
            name="euSKlidOverloadAngleArc",
            group=group,
        )
        if arc is not None:
            objs.append(arc)

        # Add a tiny vertex marker so the angle origin is unambiguous.
        marker = _make_overload_marker(plane, vertex, group=group, name="euSKlidOverloadAngleVertex")
        if marker is not None:
            objs.append(marker)

        return objs
    except Exception:
        return []


def _render_angle_overload(record, pieces, group=None):
    """Render Preserve Angle as two highlighted segments plus an angle arc."""
    objs = []
    try:
        uniq = list(dict.fromkeys([int(pi) for pi in (pieces or [])]))
        if len(uniq) < 2:
            return objs

        for pi in uniq[:2]:
            obj = _draw_overload_piece(record, int(pi), group=group)
            if obj is not None:
                objs.append(obj)

        objs.extend(_draw_angle_arc_glyph(record, uniq[0], uniq[1], group=group))
    except Exception:
        pass
    return objs


def _render_radius_overload(record, pieces, group=None):
    """Render Preserve Radius on circular path pieces."""
    objs = []
    try:
        plane = record.get("plane")
        record_pieces = record.get("pieces", []) or []
        if plane is None or not hasattr(plane, "uv_to_world"):
            return objs
        for pi in pieces or []:
            try:
                piece = record_pieces[int(pi)]
                if piece.get("type") != "arc":
                    continue
                obj = _draw_overload_piece(record, int(pi), group=group)
                if obj is not None:
                    objs.append(obj)
                center = _piece_center_uv(piece)
                edge = _piece_point_at_t(piece, 0.5)
                if center is not None and edge is not None:
                    color, width, alpha = _path_overload_style()
                    radius = _make_overload_polyline(
                        plane,
                        [center, edge],
                        color=color,
                        width=max(width + 1.0, 4.0),
                        transparency=alpha,
                        name="euSKlidOverloadRadiusLine",
                        group=group,
                    )
                    if radius is not None:
                        objs.append(radius)
                    marker = _make_overload_marker(plane, center, group=group, name="euSKlidOverloadRadiusCenter")
                    if marker is not None:
                        objs.append(marker)
            except Exception:
                pass
    except Exception:
        pass
    return objs




_DISTANCE_ENDPOINT_TOL = 0.12


def _distance_path_bbox_diag(record):
    try:
        pts = []
        for piece in record.get("pieces", []) or []:
            for t in (0.0, 1.0):
                p = _piece_point_at_t(piece, t)
                if p is not None:
                    pts.append((float(p[0]), float(p[1])))
        if not pts:
            return 1.0
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return max(1e-9, math.hypot(max(xs) - min(xs), max(ys) - min(ys)))
    except Exception:
        return 1.0


def _distance_nearest_path_endpoint(record, click_uv, selected_piece_index=None):
    """Return nearest real contour vertex to a click, or None.

    FreeCAD often reports the selected object as the segment even when the user
    clicks visually on a junction.  For Preserve Distance, endpoints must win,
    so we look at the selected segment and its immediate neighbours first.
    """
    if click_uv is None:
        return None

    try:
        cx = float(click_uv[0])
        cy = float(click_uv[1])
    except Exception:
        return None

    pieces = record.get("pieces", []) or []
    n = len(pieces)
    if n <= 0:
        return None

    candidate_indices = []

    try:
        spi = int(selected_piece_index)
        candidate_indices.extend([spi])
        if n > 1:
            candidate_indices.extend([(spi - 1) % n, (spi + 1) % n])
    except Exception:
        candidate_indices = []

    # Then all pieces as fallback.
    for i in range(n):
        if i not in candidate_indices:
            candidate_indices.append(i)

    best = None
    best_d = None
    best_local_len = None

    try:
        for pi in candidate_indices:
            piece = pieces[int(pi)]
            local_len = max(_piece_length(piece), 1e-9)
            for t in (0.0, 1.0):
                p = _piece_point_at_t(piece, t)
                if p is None:
                    continue
                d = math.hypot(cx - float(p[0]), cy - float(p[1]))
                if best_d is None or d < best_d:
                    best_d = d
                    best_local_len = local_len
                    best = {
                        "kind": "point",
                        "piece": int(pi),
                        "uv": (float(p[0]), float(p[1])),
                        "t": float(t),
                    }
    except Exception:
        return None

    if best is None:
        return None

    # Endpoint picking tolerance:
    # - local enough for small segments,
    # - but large enough for FreeCAD hit points that are approximate.
    bbox = _distance_path_bbox_diag(record)
    local = best_local_len or bbox or 1.0
    tol = max(0.06 * local, 0.015 * bbox, 0.25)

    if best_d is not None and best_d <= tol:
        return best

    return None


def _distance_nearest_arc_center(record, click_uv, selected_piece_index=None):
    """Return nearest arc/circle center reference to a click, or None."""
    if click_uv is None:
        return None

    try:
        cx = float(click_uv[0])
        cy = float(click_uv[1])
    except Exception:
        return None

    pieces = record.get("pieces", []) or []
    n = len(pieces)
    if n <= 0:
        return None

    candidate_indices = []
    try:
        spi = int(selected_piece_index)
        candidate_indices.append(spi)
    except Exception:
        pass
    for i in range(n):
        if i not in candidate_indices:
            candidate_indices.append(i)

    best = None
    best_d = None
    best_radius = None
    try:
        for pi in candidate_indices:
            piece = pieces[int(pi)]
            center = _piece_center_uv(piece)
            if center is None:
                continue
            d = math.hypot(cx - float(center[0]), cy - float(center[1]))
            if best_d is None or d < best_d:
                best_d = d
                best_radius = abs(float(piece.get("radius", 0.0)))
                best = {
                    "kind": "center",
                    "piece": int(pi),
                    "uv": (float(center[0]), float(center[1])),
                    "t": 0.5,
                }
    except Exception:
        return None

    if best is None:
        return None

    bbox = _distance_path_bbox_diag(record)
    radius = best_radius or bbox or 1.0
    tol = max(0.06 * radius, 0.015 * bbox, 0.25)
    if best_d is not None and best_d <= tol:
        return best
    return None



def _distance_world_to_uv(plane, value):
    """Convert a FreeCAD selection hit point to UV.

    FreeCAD selection observers are not consistent across versions:
    the point can be a Base.Vector, a tuple/list, or sometimes absent.
    """
    if value is None or plane is None or not hasattr(plane, "world_to_uv"):
        return None

    try:
        return plane.world_to_uv((float(value.x), float(value.y), float(value.z)))
    except Exception:
        pass

    try:
        if isinstance(value, (tuple, list)) and len(value) >= 3:
            return plane.world_to_uv((float(value[0]), float(value[1]), float(value[2])))
    except Exception:
        pass

    try:
        if isinstance(value, (tuple, list)) and len(value) >= 2:
            return (float(value[0]), float(value[1]))
    except Exception:
        pass

    return None


def _distance_selectionex_uv(path_id, obj_name=None):
    """Try to recover the actual picked point from FreeCAD SelectionEx."""
    try:
        ex_list = Gui.Selection.getSelectionEx()
    except Exception:
        return None

    try:
        record_idx, record = _find_closed_path_record(path_id)
        plane = record.get("plane") if record is not None else None
    except Exception:
        plane = None

    for ex in reversed(ex_list or []):
        try:
            if obj_name is not None and getattr(ex.Object, "Name", None) != obj_name:
                continue
        except Exception:
            pass

        # FreeCAD usually exposes the mouse-picked 3D point here.
        for attr in ("PickedPoints", "PickedPoint"):
            try:
                value = getattr(ex, attr, None)
                if value is None:
                    continue
                if isinstance(value, (list, tuple)):
                    if not value:
                        continue
                    value = value[-1]
                uv = _distance_world_to_uv(plane, value)
                if uv is not None:
                    return uv
            except Exception:
                pass

        # Some versions expose Points.
        try:
            pts = getattr(ex, "Points", None)
            if pts:
                uv = _distance_world_to_uv(plane, pts[-1])
                if uv is not None:
                    return uv
        except Exception:
            pass

    return None


def _distance_selection_kind(record, piece_index, click_uv):
    """
    endpoint > center > segment

    For Preserve Distance, a click near a contour vertex must be interpreted as
    a POINT even if FreeCAD reports the selected object as a segment.
    """
    pieces = record.get("pieces", []) or []
    piece = pieces[int(piece_index)]

    # Global vertex priority first: raccord points are shared by several
    # pieces, and FreeCAD may report either adjacent segment.
    endpoint = _distance_nearest_path_endpoint(record, click_uv, selected_piece_index=piece_index)
    if endpoint is not None:
        return endpoint

    center = _distance_nearest_arc_center(record, click_uv, selected_piece_index=piece_index)
    if center is not None:
        return center

    try:
        projected = _project_uv_to_piece(piece, click_uv)
    except Exception:
        projected = {"uv": None, "t": 0.5}

    t = float(projected.get("t", 0.5))
    uv = projected.get("uv")

    # Secondary endpoint priority from projected parameter.  This catches cases
    # where the click was snapped close to the selected segment endpoint but the
    # global vertex distance is slightly outside tolerance.
    if t <= _DISTANCE_ENDPOINT_TOL:
        p = _piece_point_at_t(piece, 0.0)
        return {
            "kind": "point",
            "piece": int(piece_index),
            "uv": p,
            "t": 0.0,
        }

    if t >= (1.0 - _DISTANCE_ENDPOINT_TOL):
        p = _piece_point_at_t(piece, 1.0)
        return {
            "kind": "point",
            "piece": int(piece_index),
            "uv": p,
            "t": 1.0,
        }

    return {
        "kind": "segment",
        "piece": int(piece_index),
        "uv": uv,
        "t": t,
    }


def _infer_distance_mode(sel0, sel1, record):
    """
    Semantic mode inference with strict endpoint priority.

    endpoint/point selections are NEVER downgraded to segment selections.
    """

    k0 = sel0.get("kind")
    k1 = sel1.get("kind")
    point_kinds = {"point", "center"}

    if k0 in point_kinds and k1 in point_kinds:
        return "point_point"

    if (
        (k0 == "segment" and k1 in point_kinds)
        or
        (k0 in point_kinds and k1 == "segment")
    ):
        return "segment_point"

    return "segment_segment"


def _distance_parallel_segments(record, sel0, sel1):
    pieces = record.get("pieces", []) or []

    p0 = pieces[int(sel0["piece"])]
    p1 = pieces[int(sel1["piece"])]

    d0 = _segment_direction_uv(p0)
    d1 = _segment_direction_uv(p1)

    if d0 is None or d1 is None:
        return None

    nx = -d0[1]
    ny = d0[0]

    mid0 = _piece_midpoint_uv(p0)
    mid1 = _piece_midpoint_uv(p1)

    v01 = (
        mid1[0] - mid0[0],
        mid1[1] - mid0[1],
    )

    dist = v01[0] * nx + v01[1] * ny

    a = mid0

    b = (
        mid0[0] + nx * dist,
        mid0[1] + ny * dist,
    )

    return {
        "a": a,
        "b": b,
        "normal": (nx, ny),
    }


def _distance_segment_point(record, seg_sel, pt_sel):
    """
    True orthogonal distance from a point/center to a segment support.

    IMPORTANT:
    FreeCAD Sketcher constrains a point-to-segment distance against the support
    line of the segment, not against the finite segment span.  Do not clamp the
    projection to [0, 1], otherwise a user center-to-segment dimension becomes
    an endpoint chord when the normal foot lies outside the visible segment.
    """
    pieces = record.get("pieces", []) or []

    piece = pieces[int(seg_sel["piece"])]

    pt = pt_sel["uv"]

    a = piece.get("a")
    b = piece.get("b")

    ax = float(a[0])
    ay = float(a[1])

    bx = float(b[0])
    by = float(b[1])

    px = float(pt[0])
    py = float(pt[1])

    vx = bx - ax
    vy = by - ay

    seg_len2 = vx * vx + vy * vy

    if seg_len2 <= 1e-12:
        proj = a
    else:
        # Orthogonal projection on the infinite support line.
        t = ((px - ax) * vx + (py - ay) * vy) / seg_len2

        proj = (
            ax + vx * t,
            ay + vy * t,
        )

    return {
        "a": proj,
        "b": pt,
    }


def _distance_point_point(sel0, sel1):
    a = sel0.get("uv")
    b = sel1.get("uv")

    if a is None or b is None:
        return None

    return {
        "a": a,
        "b": b,
    }


def _distance_ref_uv(record, ref):
    """Return a UV point for a distance reference.

    Preserve Distance is point-based when the click location is available.
    If older FreeCAD selection data lacks the clicked UV, fall back to the
    representative point of the selected piece.
    """
    try:
        ref = ref or {}
        uv = ref.get("uv")
        if uv is not None:
            return (float(uv[0]), float(uv[1]))
        pi = int(ref.get("piece"))
        if str(ref.get("kind") or "") == "center":
            return _piece_center_uv((record.get("pieces", []) or [])[pi])
        t = float(ref.get("t", 0.5))
        return _piece_point_at_t((record.get("pieces", []) or [])[pi], t)
    except Exception:
        return None


def _distance_value_for_refs(record, ref0, ref1):
    try:
        ref0 = ref0 or {}
        ref1 = ref1 or {}
        mode = _infer_distance_mode(ref0, ref1, record)
        if mode == "segment_segment":
            data = _distance_parallel_segments(record, ref0, ref1)
        elif mode == "segment_point":
            if ref0.get("kind") == "segment" and ref1.get("kind") in {"point", "center"}:
                data = _distance_segment_point(record, ref0, ref1)
            elif ref1.get("kind") == "segment" and ref0.get("kind") in {"point", "center"}:
                data = _distance_segment_point(record, ref1, ref0)
            else:
                data = None
        else:
            data = _distance_point_point(ref0, ref1)

        if not data:
            return None
        a = data.get("a")
        b = data.get("b")
        return math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))
    except Exception:
        return None


def _render_distance_overload(record, range_data, group=None):
    """Render Preserve Distance using inferred semantic modes."""
    objs = []
    try:
        plane = record.get("plane")
        if plane is None or not hasattr(plane, "uv_to_world"):
            return objs

        sel0 = (range_data or {}).get("start") or {}
        sel1 = (range_data or {}).get("end") or {}

        mode = _infer_distance_mode(sel0, sel1, record)

        if mode == "segment_segment":
            data = _distance_parallel_segments(record, sel0, sel1)
        elif mode == "segment_point":
            # STRICT semantic dispatch.
            #
            # DO NOT silently fall back to segment/segment behaviour.
            # If one entity is a point selection, it MUST remain point-based.
            #
            # Endpoint clicks are authoritative.

            if sel0.get("kind") == "segment" and sel1.get("kind") in {"point", "center"}:
                data = _distance_segment_point(record, sel0, sel1)

            elif sel1.get("kind") == "segment" and sel0.get("kind") in {"point", "center"}:
                data = _distance_segment_point(record, sel1, sel0)

            elif sel0.get("kind") in {"point", "center"} and sel1.get("kind") in {"point", "center"}:
                data = _distance_point_point(sel0, sel1)

            else:
                # No semantic reinterpretation allowed here.
                # Better to show nothing than to display a wrong constraint.
                return objs
        else:
            data = _distance_point_point(sel0, sel1)

        if not data:
            return objs

        start_uv = data.get("a")
        end_uv = data.get("b")

        dx = float(end_uv[0]) - float(start_uv[0])
        dy = float(end_uv[1]) - float(start_uv[1])
        d = math.hypot(dx, dy)

        if d <= 1e-9:
            return objs

        color, width, alpha = _path_overload_style()

        # Point/point and point/segment must remain visually obvious.
        render_width = max(width + 2.0, 5.0)

        line = _make_overload_polyline(
            plane,
            [start_uv, end_uv],
            color=color,
            width=render_width,
            transparency=max(0, alpha - 10),
            name="euSKlidOverloadDistanceLine",
            group=group,
        )

        if line is not None:
            objs.append(line)

        for uv in (start_uv, end_uv):
            marker = _make_overload_marker(
                plane,
                uv,
                group=group,
                name="euSKlidOverloadDistancePoint",
            )

            # Additional endpoint visibility for point-based distances.
            try:
                halo = _make_overload_marker(
                    plane,
                    uv,
                    group=group,
                    name="euSKlidOverloadDistancePointHalo",
                )
                if halo is not None:
                    objs.append(halo)
            except Exception:
                pass
            if marker is not None:
                objs.append(marker)

        return objs
    except Exception:
        return objs


def _draw_overload_range(record, range_data, group=None):
    """Draw only the user-selected overload range, with robust fallback markers.

    The range renderer must never silently draw nothing: if the exact partial
    path cannot be reconstructed, the two clicked points are still shown and a
    straight fallback marker is drawn between them.  This keeps Preserve Tangent
    usable while preserving the rule that full pieces are not highlighted.
    """
    objs = []
    range_data = range_data or {}
    plane = record.get("plane")
    if plane is None or not hasattr(plane, "uv_to_world"):
        return objs

    try:
        portions = range_data.get("portions", []) or []
        objs.extend(_draw_overload_portions(record, portions, group=group))
    except Exception:
        portions = []

    def _uv_from_ref(ref):
        try:
            uv = (ref or {}).get("uv")
            if uv is not None:
                return (float(uv[0]), float(uv[1]))
            pi = int((ref or {}).get("piece"))
            t = float((ref or {}).get("t", 0.5))
            return _piece_point_at_t((record.get("pieces", []) or [])[pi], t)
        except Exception:
            return None

    start_uv = _uv_from_ref(range_data.get("start"))
    end_uv = _uv_from_ref(range_data.get("end"))

    # Mark clicked endpoints even when the selected range itself is very short.
    for uv in (start_uv, end_uv):
        marker = _make_overload_marker(plane, uv, group=group)
        if marker is not None:
            objs.append(marker)

    if not objs and start_uv is not None and end_uv is not None:
        color, width, alpha = _path_overload_style()
        obj = _make_overload_polyline(plane, [start_uv, end_uv], color=color, width=width, transparency=alpha, group=group)
        if obj is not None:
            objs.append(obj)

    if not objs:
        try:
            App.Console.PrintWarning("euSKlid Path: overload range has no drawable portion.\n")
        except Exception:
            pass
    return objs


def _draw_overload_piece(record, piece_index, group=None):
    try:
        portions = [(int(piece_index), 0.0, 1.0)]
        objs = _draw_overload_portions(record, portions, group=group)
        return objs[0] if objs else None
    except Exception:
        return None


def _draw_overloads_for_record(record, index, group=None):
    objs = []
    path_id = record.get("id") or _path_record_id(index)
    overloads = record.get("overloads", []) or []
    for ov in overloads:
        try:
            if ov.get("range"):
                if str(ov.get("kind", "")) == "tangent":
                    objs.extend(_render_tangent_overload(record, ov.get("range", {}) or {}, group=group))
                elif str(ov.get("kind", "")) in ("colinearity", "collinearity"):
                    objs.extend(_render_colinearity_overload(record, ov.get("pieces", []) or [], group=group))
                elif str(ov.get("kind", "")) == "angle":
                    objs.extend(_render_angle_overload(record, ov.get("pieces", []) or [], group=group))
                elif str(ov.get("kind", "")) == "radius":
                    objs.extend(_render_radius_overload(record, ov.get("pieces", []) or [], group=group))
                elif str(ov.get("kind", "")) == "distance":
                    objs.extend(_render_distance_overload(record, ov.get("range", {}) or {}, group=group))
                else:
                    objs.extend(_draw_overload_range(record, ov.get("range", {}) or {}, group=group))
                continue
            if str(ov.get("kind", "")) in ("colinearity", "collinearity"):
                objs.extend(_render_colinearity_overload(record, ov.get("pieces", []) or [], group=group))
                continue
            if str(ov.get("kind", "")) == "angle":
                objs.extend(_render_angle_overload(record, ov.get("pieces", []) or [], group=group))
                continue
            if str(ov.get("kind", "")) == "radius":
                objs.extend(_render_radius_overload(record, ov.get("pieces", []) or [], group=group))
                continue
            for pi in ov.get("pieces", []) or []:
                obj = _draw_overload_piece(record, int(pi), group=group)
                if obj is not None:
                    objs.append(obj)
        except Exception:
            pass
    for obj in objs:
        _tag_path_owned_object(obj, path_id)
    return objs

def _draw_closed_path_record(record, index):
    global _PATH_CLOSED_OBJECTS
    doc = App.ActiveDocument
    if doc is None:
        return []
    plane = record.get("plane")
    if plane is None or not hasattr(plane, "uv_to_world"):
        try:
            from ..plane import SketchPlane
            plane = SketchPlane.XY()
        except Exception:
            return []
    path_id = record.get("id") or _path_record_id(index)
    label = record.get("label") or _path_record_label(index)
    group = ensure_path_instance_group(doc, path_id=path_id, label=label)
    closed_color, closed_width, closed_alpha = _path_style("closed", (0.0, 0.45, 0.0), 6.0, 0)
    objs = []
    for piece_index, piece in enumerate(record.get("pieces", [])):
        if piece.get("type") == "segment":
            obj = _make_line_segment(plane, piece.get("a"), piece.get("b"), color=closed_color, width=closed_width, transparency=closed_alpha, name="euSKlidClosedPathSeg", group=group)
        else:
            a0 = piece.get("a0")
            a1 = piece.get("a1")
            if piece.get("delta", 1.0) < 0.0:
                a0, a1 = a1, a0
            obj = _make_arc_segment(plane, piece.get("center"), piece.get("radius"), a0, a1, color=closed_color, width=closed_width, transparency=closed_alpha, name="euSKlidClosedPathArc", group=group)
        if obj is not None:
            _tag_path_piece_object(obj, path_id, piece_index, piece.get("type", ""))
            objs.append(obj)
        center_uv = _piece_center_uv(piece)
        if center_uv is not None:
            center_obj = _make_path_point(plane, center_uv, kind="fixed", name="euSKlidClosedPathCenter")
            if center_obj is not None:
                try:
                    add_to_group(center_obj, group)
                except Exception:
                    pass
                _tag_path_piece_object(center_obj, path_id, piece_index, "center")
                objs.append(center_obj)
    objs.extend(_draw_overloads_for_record(record, index, group=group))
    _PATH_CLOSED_OBJECTS.extend(objs)
    return objs



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



def _path_draw_marker_circle(layer, plane, uv, color, alpha=0, size_px=None, width_px=2.0):
    """Draw a true circular screen-scale marker."""
    if coin is None:
        return False
    root = _path_overlay_root(layer)
    if root is None or uv is None or plane is None or not hasattr(plane, "uv_to_world"):
        return False
    try:
        size_px = float(size_px if size_px is not None else _path_point_size())
        radius = max(_path_pixels_to_world(plane, uv, size_px * 0.50), 1e-6)
        ux, uy = float(uv[0]), float(uv[1])
        steps = 48
        pts = []
        for i in range(steps + 1):
            a = 2.0 * math.pi * float(i) / float(steps)
            p = (ux + math.cos(a) * radius, uy + math.sin(a) * radius)
            w = App.Vector(*plane.uv_to_world(p))
            pts.append((float(w.x), float(w.y), float(w.z)))

        sep = coin.SoSeparator()
        sep.addChild(_path_material(color, alpha))

        draw = coin.SoDrawStyle()
        draw.lineWidth.setValue(max(1.0, float(width_px)))
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


def _path_overload_style():
    try:
        style = get_overload_style()
        color = tuple(style.get("color", get_overload_color()))
        width = float(style.get("thickness", 8.0))
        alpha = int(style.get("alpha", 20))
        return color, max(1.0, width), max(0, min(100, alpha))
    except Exception:
        return (1.0, 0.55, 0.55), 8.0, 20


def _ensure_obj_prop(obj, prop_type, name, group="euSKlid", desc=""):
    try:
        if name not in getattr(obj, "PropertiesList", []):
            obj.addProperty(prop_type, name, group, desc or name)
        return True
    except Exception:
        return False


def _tag_path_piece_object(obj, path_id, piece_index, piece_type):
    if obj is None:
        return
    try:
        if _ensure_obj_prop(obj, "App::PropertyString", "EuSKlidPathId", desc="euSKlid path id"):
            obj.EuSKlidPathId = str(path_id)
        if _ensure_obj_prop(obj, "App::PropertyInteger", "EuSKlidPieceIndex", desc="euSKlid path piece index"):
            obj.EuSKlidPieceIndex = int(piece_index)
        if _ensure_obj_prop(obj, "App::PropertyString", "EuSKlidPieceType", desc="euSKlid path piece type"):
            obj.EuSKlidPieceType = str(piece_type)
        try:
            obj.ViewObject.Selectable = True
        except Exception:
            pass
    except Exception:
        pass


def _tag_path_owned_object(obj, path_id):
    """Tag a path-owned visual object without making it selectable as a piece."""
    if obj is None:
        return
    try:
        if _ensure_obj_prop(obj, "App::PropertyString", "EuSKlidPathId", desc="euSKlid path id"):
            obj.EuSKlidPathId = str(path_id)
    except Exception:
        pass


def _track_closed_path_objects(objs, path_id=None):
    """Remember newly created closed-path visuals for refresh/cleanup."""
    try:
        for obj in list(objs or []):
            if obj is None:
                continue
            if path_id is not None:
                _tag_path_owned_object(obj, path_id)
            if obj not in _PATH_CLOSED_OBJECTS:
                _PATH_CLOSED_OBJECTS.append(obj)
    except Exception:
        pass


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
        obj.ViewObject.Selectable = bool(str(name).startswith("euSKlidClosedPath"))
    except Exception:
        pass
    return obj


def _make_line_segment(plane, a_uv, b_uv, color, width=5.0, transparency=0, name="euSKlidPathSeg", group=None):
    doc = App.ActiveDocument
    if doc is None:
        return None
    a = App.Vector(*plane.uv_to_world(a_uv))
    b = App.Vector(*plane.uv_to_world(b_uv))
    ensure_euclid_groups(doc)
    obj = doc.addObject("Part::Feature", name)
    try:
        grp = group if group is not None else (get_path_group(doc) if name.startswith("euSKlidClosedPath") else get_transient_group(doc))
        add_to_group(obj, grp)
    except Exception:
        pass
    obj.Shape = Part.makeLine(a, b)
    try:
        obj.ViewObject.LineColor = color
        obj.ViewObject.LineWidth = width
        obj.ViewObject.Transparency = transparency
        obj.ViewObject.Selectable = bool(str(name).startswith("euSKlidClosedPath"))
    except Exception:
        pass
    return obj


def _make_arc_segment(plane, center_uv, radius, a0, a1, color, width=5.0, transparency=0, name="euSKlidPathArc", group=None):
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
        grp = group if group is not None else (get_path_group(doc) if name.startswith("euSKlidClosedPath") else get_transient_group(doc))
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


def _is_path_undo_key(info):
    """Return True for Ctrl+Z in the active Path scene callback."""
    try:
        if str(info.get("State", "")).upper() != "DOWN":
            return False
    except Exception:
        return False
    try:
        key = str(info.get("Key", "")).upper()
        if key not in ("Z", "KEY_Z"):
            return False
    except Exception:
        return False
    try:
        v = str(info.get("CtrlDown", info.get("ControlDown", info.get("Ctrl", "")))).upper()
        if v in ("TRUE", "1", "YES"):
            return True
    except Exception:
        pass
    try:
        mods = str(info.get("Modifiers", info.get("Modifier", ""))).upper()
        return "CTRL" in mods or "CONTROL" in mods
    except Exception:
        return False


def _is_path_escape_key(info):
    try:
        if str(info.get("State", "")).upper() != "DOWN":
            return False
    except Exception:
        return False
    try:
        key = str(info.get("Key", "")).upper()
        return key in ("ESCAPE", "ESC", "KEY_ESCAPE")
    except Exception:
        return False


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
        self._cb_key = self._view.addEventCallback("SoKeyboardEvent", self.on_key)
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

    def on_key(self, info):
        try:
            if _is_path_undo_key(info):
                if self.undo_last_point():
                    return
            if _is_path_escape_key(info):
                try:
                    stop_path_session()
                except Exception:
                    pass
        except Exception:
            pass

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
        try:
            self._view.removeEventCallback("SoKeyboardEvent", self._cb_key)
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

        path_index = len(_CLOSED_PATHS)
        record = {
            "id": _path_record_id(path_index),
            "label": _path_record_label(path_index),
            "plane": self.plane,
            "pieces": list(self.active_pieces),
            "entity_meta": entity_meta,
            "overloads": [],
        }
        try:
            from ..core.undo import push_sketch_undo
            push_sketch_undo(self.sketch_obj)
        except Exception:
            pass
        _CLOSED_PATHS.append(record)
        _draw_closed_path_record(record, path_index)
        _sync_closed_paths_to_sketch(self.sketch_obj)
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

        # Après canonisation, on refusionne proprement.  If user overloads are
        # attached to the path, preserve the stored piece indexes because export
        # user intents resolve against piece_order.
        if not record.get("overloads"):
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

        try:
            export_geometry_start = len(sk.Geometry)
        except Exception:
            export_geometry_start = None

        geom_meta = []

        for piece_order, piece in enumerate(canon_pieces):
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
                    "piece_order": int(piece_order),
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
                    "piece_order": int(piece_order),
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
        constraint_result = add_path_constraints(sk, Sketcher, geom_meta, tol_join, overloads=record.get("overloads", []) or [])
        exported_constraint_indices.extend(constraint_result.get("indices", []))
        try:
            if export_geometry_start is not None:
                exported_geometry_indices = sorted(
                    set(exported_geometry_indices).union(range(int(export_geometry_start), len(sk.Geometry)))
                )
        except Exception:
            pass

        _write_export_tag(sk, exported_geometry_indices, exported_constraint_indices, label="path")

        _refresh_exported_sketch(sk, doc)
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
_ACTIVE_OVERLOAD_SESSION = None


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

    if not _ensure_closed_paths_loaded():
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
        overload_color, overload_width, overload_alpha = _path_overload_style()
        for obj in list(_PATH_CLOSED_OBJECTS):
            try:
                vo = getattr(obj, "ViewObject", None)
                if vo is None:
                    continue
                if "EuSKlidPieceIndex" in getattr(obj, "PropertiesList", []):
                    color, width, alpha = closed_color, closed_width, closed_alpha
                else:
                    color, width, alpha = overload_color, overload_width, overload_alpha
                vo.LineColor = color
                vo.ShapeColor = color
                vo.PointColor = color
                vo.LineWidth = width
                vo.Transparency = alpha
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



def _path_id_from_group_object(obj):
    """Return a Path id from a PathXXX group or a tagged Path piece."""
    try:
        if obj is None:
            return None
        if "EuSKlidPathId" in getattr(obj, "PropertiesList", []):
            return str(getattr(obj, "EuSKlidPathId"))
        label = str(getattr(obj, "Label", "") or getattr(obj, "Name", ""))
        name = str(getattr(obj, "Name", "") or "")
        for idx, record in enumerate(_ensure_closed_paths_loaded()):
            rid = str(record.get("id") or _path_record_id(idx))
            rlabel = str(record.get("label") or _path_record_label(idx))
            if label == rlabel or name == rlabel or name == rid or label == rid:
                return rid
    except Exception:
        pass
    return None


def _selected_path_id_for_overload_edit():
    try:
        sel = list(Gui.Selection.getSelection() or [])
    except Exception:
        sel = []
    for obj in sel:
        pid = _path_id_from_group_object(obj)
        if pid:
            return pid
    paths = _ensure_closed_paths_loaded()
    if len(paths) == 1:
        return str(paths[0].get("id") or _path_record_id(0))
    return None


def _remove_overload_edit_objects():
    global _ACTIVE_OVERLOAD_EDIT
    state = _ACTIVE_OVERLOAD_EDIT or {}
    doc = App.ActiveDocument
    for obj in list(state.get("objects", []) or []):
        try:
            if doc is not None:
                doc.removeObject(obj.Name)
        except Exception:
            pass
    for obj, vis in list(state.get("visibility", []) or []):
        try:
            obj.ViewObject.Visibility = bool(vis)
        except Exception:
            pass
    _ACTIVE_OVERLOAD_EDIT = None
    try:
        Gui.Selection.clearSelection()
    except Exception:
        pass
    try:
        Gui.updateGui()
    except Exception:
        pass


def finish_path_overload_edit():
    """Close the temporary overload edit view and restore the closed Path."""
    if _ACTIVE_OVERLOAD_EDIT is None:
        try:
            App.Console.PrintMessage("euSKlid Path: no overload edit session active.\n")
        except Exception:
            pass
        return False
    _remove_overload_edit_objects()
    try:
        App.Console.PrintMessage("euSKlid Path: overload edit session closed.\n")
    except Exception:
        pass
    return True


def start_path_overload_edit():
    """Open a closed Path as selectable temporary pieces for overload marking.

    The original closed Path is hidden while editable copies are shown in the
    configured overload color.  The copies carry the same EuSKlidPathId and
    EuSKlidPieceIndex tags, so Preserve Tangent and future overload tools can
    select them exactly like normal closed-path pieces.
    """
    global _ACTIVE_OVERLOAD_EDIT
    _stop_active_overload_session()
    if _ACTIVE_OVERLOAD_EDIT is not None:
        _remove_overload_edit_objects()

    path_id = _selected_path_id_for_overload_edit()
    if not path_id:
        elog.help("Select one Path group or piece to edit overloads.")
        return False

    record_idx, record = _find_closed_path_record(path_id)
    if record is None:
        QtWidgets.QMessageBox.warning(None, "euSKlid", "Cannot find the selected Path record.")
        return False

    doc = App.ActiveDocument
    if doc is None:
        return False

    # Hide existing visible pieces for this Path, including existing overload markers.
    previous_visibility = []
    try:
        for obj in list(doc.Objects):
            try:
                if "EuSKlidPathId" in getattr(obj, "PropertiesList", []) and str(getattr(obj, "EuSKlidPathId")) == str(path_id):
                    previous_visibility.append((obj, bool(getattr(obj.ViewObject, "Visibility", True))))
                    obj.ViewObject.Visibility = False
            except Exception:
                pass
    except Exception:
        pass

    color, width, alpha = _path_overload_style()
    plane = record.get("plane")
    if plane is None or not hasattr(plane, "uv_to_world"):
        try:
            from ..plane import SketchPlane
            plane = SketchPlane.XY()
        except Exception:
            QtWidgets.QMessageBox.warning(None, "euSKlid", "Cannot open this Path for overload editing.")
            return False

    edit_objects = []
    group = None
    try:
        group = get_transient_group(doc)
    except Exception:
        group = None
    for piece_index, piece in enumerate(record.get("pieces", []) or []):
        obj = None
        try:
            if piece.get("type") == "segment":
                obj = _make_line_segment(plane, piece.get("a"), piece.get("b"), color=color, width=max(float(width), 7.0), transparency=alpha, name="euSKlidOverloadEditSeg", group=group)
            else:
                a0 = piece.get("a0")
                a1 = piece.get("a1")
                if piece.get("delta", 1.0) < 0.0:
                    a0, a1 = a1, a0
                obj = _make_arc_segment(plane, piece.get("center"), piece.get("radius"), a0, a1, color=color, width=max(float(width), 7.0), transparency=alpha, name="euSKlidOverloadEditArc", group=group)
            if obj is not None:
                _tag_path_piece_object(obj, path_id, piece_index, piece.get("type", ""))
                try:
                    obj.ViewObject.Selectable = True
                except Exception:
                    pass
                edit_objects.append(obj)
            center_uv = _piece_center_uv(piece)
            if center_uv is not None:
                center_obj = _make_path_point(plane, center_uv, kind="fixed", name="euSKlidOverloadEditCenter")
                if center_obj is not None:
                    _tag_path_piece_object(center_obj, path_id, piece_index, "center")
                    try:
                        center_obj.ViewObject.Selectable = True
                    except Exception:
                        pass
                    edit_objects.append(center_obj)
        except Exception as e:
            try:
                App.Console.PrintError("euSKlid Path: cannot create overload edit piece %s: %s\n" % (piece_index, str(e)))
            except Exception:
                pass
    if not edit_objects:
        for obj, vis in previous_visibility:
            try:
                obj.ViewObject.Visibility = bool(vis)
            except Exception:
                pass
        QtWidgets.QMessageBox.warning(None, "euSKlid", "No selectable Path pieces could be created.")
        return False

    _ACTIVE_OVERLOAD_EDIT = {"path_id": str(path_id), "record_idx": int(record_idx), "objects": edit_objects, "visibility": previous_visibility}
    try:
        Gui.Selection.clearSelection()
    except Exception:
        pass
    try:
        App.Console.PrintMessage("euSKlid Path: overload edit opened for %s. Use Preserve Tangent, then Finish Overload Edit.\n" % str(path_id))
    except Exception:
        pass
    return True

def _selected_closed_path_pieces():
    """Return selected closed-path piece objects as (path_id, piece_index, obj)."""
    out = []
    try:
        selection = list(Gui.Selection.getSelection() or [])
    except Exception:
        selection = []
    seen = set()
    for obj in selection:
        try:
            if "EuSKlidPathId" not in getattr(obj, "PropertiesList", []):
                continue
            if "EuSKlidPieceIndex" not in getattr(obj, "PropertiesList", []):
                continue
            path_id = str(getattr(obj, "EuSKlidPathId"))
            piece_index = int(getattr(obj, "EuSKlidPieceIndex"))
            piece_type = str(getattr(obj, "EuSKlidPieceType", "") or "")
            key = (path_id, piece_index, piece_type)
            if key in seen:
                continue
            seen.add(key)
            out.append((path_id, piece_index, obj))
        except Exception:
            pass
    return out


def _find_closed_path_record(path_id):
    try:
        _ensure_closed_paths_loaded()
    except Exception:
        pass
    for idx, record in enumerate(_CLOSED_PATHS):
        try:
            if str(record.get("id", _path_record_id(idx))) == str(path_id):
                return idx, record
        except Exception:
            pass
    return None, None


def _overload_exists(record, kind, pieces):
    want = tuple(sorted(int(p) for p in pieces))
    for ov in record.get("overloads", []) or []:
        try:
            if str(ov.get("kind")) != str(kind):
                continue
            have = tuple(sorted(int(p) for p in (ov.get("pieces", []) or [])))
            if have == want:
                return True
        except Exception:
            pass
    return False


def _object_closed_path_piece(obj):
    """Return (path_id, piece_index, obj) for a closed Path document object."""
    try:
        if obj is None:
            return None
        if "EuSKlidPathId" not in getattr(obj, "PropertiesList", []):
            return None
        if "EuSKlidPieceIndex" not in getattr(obj, "PropertiesList", []):
            return None
        path_id = str(getattr(obj, "EuSKlidPathId"))
        piece_index = int(getattr(obj, "EuSKlidPieceIndex"))
        return (path_id, piece_index, obj)
    except Exception:
        return None



def _selected_item_path_piece(item):
    """Normalize overload selection item to (path_id, piece_index, click_uv)."""
    try:
        if isinstance(item, dict):
            return str(item.get("path_id")), int(item.get("piece")), item.get("uv")
        return str(item[0]), int(item[1]), None
    except Exception:
        return None, None, None


def _add_tangent_overload_for_pieces(selected, interactive=False):
    """Store a protected tangent overload for the shortest user-selected path range."""
    if len(selected) != 2:
        elog.help("Select exactly two points on the same opened contour, then run Preserve Tangent.")
        return False

    norm = [_selected_item_path_piece(item) for item in selected]
    path_ids = {item[0] for item in norm if item[0] is not None}
    if len(path_ids) != 1:
        QtWidgets.QMessageBox.warning(None, "euSKlid", "Selected points must belong to the same Path.")
        return False

    path_id = norm[0][0]
    record_idx, record = _find_closed_path_record(path_id)
    if record is None:
        QtWidgets.QMessageBox.warning(None, "euSKlid", "Cannot find the selected Path record.")
        return False

    pieces = [int(norm[0][1]), int(norm[1][1])]
    if pieces[0] == pieces[1]:
        # Same piece is allowed only if the clicks are meaningfully different.
        pass

    try:
        max_index = len(record.get("pieces", []) or []) - 1
        if pieces[0] < 0 or pieces[1] < 0 or pieces[0] > max_index or pieces[1] > max_index:
            QtWidgets.QMessageBox.warning(None, "euSKlid", "Selected Path piece index is invalid.")
            return False
    except Exception:
        pass

    try:
        p0 = _project_uv_to_piece((record.get("pieces", []) or [])[pieces[0]], norm[0][2])
        p1 = _project_uv_to_piece((record.get("pieces", []) or [])[pieces[1]], norm[1][2])
        start_ref = {"piece": int(pieces[0]), "uv": p0.get("uv"), "t": float(p0.get("t", 0.0))}
        end_ref = {"piece": int(pieces[1]), "uv": p1.get("uv"), "t": float(p1.get("t", 1.0))}
        portions = _range_portions_between_points(record, start_ref, end_ref)
        range_pieces = _pieces_from_portions(portions)
    except Exception:
        start_ref = {"piece": int(pieces[0]), "uv": None, "t": 0.0}
        end_ref = {"piece": int(pieces[1]), "uv": None, "t": 1.0}
        portions = [(int(pieces[0]), 0.0, 1.0), (int(pieces[1]), 0.0, 1.0)]
        range_pieces = [int(pieces[0]), int(pieces[1])]

    if not range_pieces:
        QtWidgets.QMessageBox.warning(None, "euSKlid", "Cannot compute selected contour portion.")
        return False

    # Duplicate check now uses the visual range, not just the two clicked pieces.
    if _overload_exists(record, "tangent", range_pieces):
        QtWidgets.QMessageBox.information(None, "euSKlid", "This tangent overload already exists.")
        return True

    try:
        from ..core.undo import push_sketch_undo
        push_sketch_undo(get_or_create_euclid_sketch())
    except Exception:
        pass

    overload = {
        "kind": "tangent",
        "pieces": [int(p) for p in range_pieces],
        "range": {
            "mode": "shortest",
            "start": start_ref,
            "end": end_ref,
            "portions": [(int(pi), float(t0), float(t1)) for (pi, t0, t1) in portions],
        },
        "strength": "protected",
        "source": "user",
    }
    try:
        record.setdefault("overloads", []).append(overload)
        _CLOSED_PATHS[int(record_idx)] = record
    except Exception:
        QtWidgets.QMessageBox.warning(None, "euSKlid", "Cannot store tangent overload.")
        return False

    try:
        doc = App.ActiveDocument
        group = None
        if doc is not None:
            group = ensure_path_instance_group(
                doc,
                path_id=record.get("id") or _path_record_id(record_idx),
                label=record.get("label") or _path_record_label(record_idx),
            )
        drawn = _render_tangent_overload(record, overload.get("range", {}) or {}, group=group)
        _track_closed_path_objects(drawn, path_id=record.get("id") or path_id)
        if not drawn:
            App.Console.PrintWarning("euSKlid Path: tangent overload stored, but no visual marker could be drawn.\n")
    except Exception:
        pass

    _sync_closed_paths_to_sketch()
    try:
        Gui.Selection.clearSelection()
    except Exception:
        pass
    try:
        _path_request_redraw()
    except Exception:
        pass
    try:
        App.Console.PrintMessage(
            "euSKlid Path: tangent overload added on %s pieces %s via shortest range %s\n" % (path_id, pieces, range_pieces)
        )
    except Exception:
        pass
    return True




def _add_colinearity_overload_for_pieces(selected, interactive=False):
    """Store a protected colinearity overload on two selected Path segments."""
    if len(selected) != 2:
        elog.help("Select exactly two segments on the same opened contour, then run Preserve Colinearity.")
        return False

    norm = [_selected_item_path_piece(item) for item in selected]
    path_ids = {item[0] for item in norm if item[0] is not None}
    if len(path_ids) != 1:
        QtWidgets.QMessageBox.warning(None, "euSKlid", "Selected segments must belong to the same Path.")
        return False

    path_id = norm[0][0]
    record_idx, record = _find_closed_path_record(path_id)
    if record is None:
        QtWidgets.QMessageBox.warning(None, "euSKlid", "Cannot find the selected Path record.")
        return False

    pieces = [int(norm[0][1]), int(norm[1][1])]
    try:
        max_index = len(record.get("pieces", []) or []) - 1
        if pieces[0] < 0 or pieces[1] < 0 or pieces[0] > max_index or pieces[1] > max_index:
            QtWidgets.QMessageBox.warning(None, "euSKlid", "Selected Path piece index is invalid.")
            return False
    except Exception:
        pass

    record_pieces = record.get("pieces", []) or []
    valid_pieces = []
    for pi in pieces:
        try:
            piece = record_pieces[int(pi)]
            if piece.get("type") != "segment":
                QtWidgets.QMessageBox.warning(None, "euSKlid", "Preserve Colinearity currently applies to straight segments only.")
                return False
            valid_pieces.append(int(pi))
        except Exception:
            QtWidgets.QMessageBox.warning(None, "euSKlid", "Selected Path piece is invalid.")
            return False

    overload = {
        "kind": "colinearity",
        "pieces": list(dict.fromkeys(valid_pieces)),
        "strength": "protected_user_intent",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    record.setdefault("overloads", []).append(overload)
    _sync_closed_paths_to_sketch()

    try:
        record_idx, record = _find_closed_path_record(path_id)
        group = ensure_path_instance_group(App.ActiveDocument, path_id=record.get("id") or path_id, label=record.get("label") or path_id)
        drawn = _render_colinearity_overload(record, overload.get("pieces", []) or [], group=group)
        _track_closed_path_objects(drawn, path_id=record.get("id") or path_id)
        App.ActiveDocument.recompute()
    except Exception:
        pass

    App.Console.PrintMessage("euSKlid Path: colinearity overload preserved.\n")
    return True



def _add_angle_overload_for_pieces(selected, interactive=False):
    """Store a protected angle overload on two selected straight Path segments."""
    if len(selected) != 2:
        elog.help("Select exactly two segments on the same opened contour, then run Preserve Angle.")
        return False

    norm = [_selected_item_path_piece(item) for item in selected]
    path_ids = {item[0] for item in norm if item[0] is not None}
    if len(path_ids) != 1:
        QtWidgets.QMessageBox.warning(None, "euSKlid", "Selected segments must belong to the same Path.")
        return False

    path_id = norm[0][0]
    record_idx, record = _find_closed_path_record(path_id)
    if record is None:
        QtWidgets.QMessageBox.warning(None, "euSKlid", "Cannot find the selected Path record.")
        return False

    pieces = [int(norm[0][1]), int(norm[1][1])]
    if pieces[0] == pieces[1]:
        QtWidgets.QMessageBox.warning(None, "euSKlid", "Preserve Angle requires two distinct straight segments.")
        return False

    try:
        max_index = len(record.get("pieces", []) or []) - 1
        if pieces[0] < 0 or pieces[1] < 0 or pieces[0] > max_index or pieces[1] > max_index:
            QtWidgets.QMessageBox.warning(None, "euSKlid", "Selected Path piece index is invalid.")
            return False
    except Exception:
        pass

    record_pieces = record.get("pieces", []) or []
    for pi in pieces:
        try:
            piece = record_pieces[int(pi)]
            if piece.get("type") != "segment":
                QtWidgets.QMessageBox.warning(None, "euSKlid", "Preserve Angle currently applies to straight segments only.")
                return False
        except Exception:
            QtWidgets.QMessageBox.warning(None, "euSKlid", "Selected Path piece is invalid.")
            return False

    refs = []
    for idx, item in enumerate(selected[:2]):
        click_uv = item.get("uv") if isinstance(item, dict) else None
        if click_uv is None and not isinstance(item, dict):
            try:
                obj = item[2]
                click_uv = _distance_selectionex_uv(path_id, obj_name=str(getattr(obj, "Name", "")))
            except Exception:
                click_uv = None
        refs.append(_angle_ref_for_selection(record, pieces[idx], click_uv))

    angle_value = _angle_value_for_piece_pair(record, pieces[0], pieces[1])
    if angle_value is None:
        QtWidgets.QMessageBox.warning(None, "euSKlid", "Cannot compute the selected angle.")
        return False
    angle_value = abs(float(angle_value))

    overload = {
        "kind": "angle",
        "pieces": list(dict.fromkeys(pieces)),
        "range": {
            "mode": "segment_pair",
            "start": refs[0],
            "end": refs[1],
            "value": float(angle_value),
            "abs_value": float(angle_value),
            "value_degrees": float(math.degrees(angle_value)),
        },
        "strength": "protected_user_intent",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    record.setdefault("overloads", []).append(overload)
    _sync_closed_paths_to_sketch()

    try:
        record_idx, record = _find_closed_path_record(path_id)
        group = ensure_path_instance_group(App.ActiveDocument, path_id=record.get("id") or path_id, label=record.get("label") or path_id)
        drawn = _render_angle_overload(record, overload.get("pieces", []) or [], group=group)
        _track_closed_path_objects(drawn, path_id=record.get("id") or path_id)
        App.ActiveDocument.recompute()
    except Exception:
        pass

    App.Console.PrintMessage("euSKlid Path: angle overload preserved.\n")
    return True



def _add_radius_overload_for_pieces(selected, interactive=False):
    """Store a protected radius overload on one selected circular Path piece."""
    if len(selected) != 1:
        elog.help("Select exactly one arc on the opened contour, then run Preserve Radius.")
        return False

    path_id, piece_index, _uv = _selected_item_path_piece(selected[0])
    if path_id is None or piece_index is None:
        QtWidgets.QMessageBox.warning(None, "euSKlid", "Selected arc must belong to a Path.")
        return False

    record_idx, record = _find_closed_path_record(path_id)
    if record is None:
        QtWidgets.QMessageBox.warning(None, "euSKlid", "Cannot find the selected Path record.")
        return False

    try:
        piece_index = int(piece_index)
        piece = (record.get("pieces", []) or [])[piece_index]
        if piece.get("type") != "arc":
            QtWidgets.QMessageBox.warning(None, "euSKlid", "Preserve Radius currently applies to arcs only.")
            return False
        value = abs(float(piece.get("radius")))
        if value <= 0.0:
            QtWidgets.QMessageBox.warning(None, "euSKlid", "Selected arc radius is invalid.")
            return False
    except Exception:
        QtWidgets.QMessageBox.warning(None, "euSKlid", "Selected Path arc is invalid.")
        return False

    if _overload_exists(record, "radius", [piece_index]):
        QtWidgets.QMessageBox.information(None, "euSKlid", "This radius overload already exists.")
        return True

    overload = {
        "kind": "radius",
        "pieces": [int(piece_index)],
        "range": {
            "mode": "arc_radius",
            "piece": int(piece_index),
            "value": float(value),
        },
        "strength": "protected_user_intent",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    record.setdefault("overloads", []).append(overload)
    _sync_closed_paths_to_sketch()

    try:
        record_idx, record = _find_closed_path_record(path_id)
        group = ensure_path_instance_group(App.ActiveDocument, path_id=record.get("id") or path_id, label=record.get("label") or path_id)
        drawn = _render_radius_overload(record, overload.get("pieces", []) or [], group=group)
        _track_closed_path_objects(drawn, path_id=record.get("id") or path_id)
        App.ActiveDocument.recompute()
    except Exception:
        pass

    App.Console.PrintMessage("euSKlid Path: radius overload preserved.\n")
    return True



def _add_distance_overload_for_pieces(selected, interactive=False):
    """Store a protected distance overload between two clicked Path references."""
    if len(selected) != 2:
        elog.help("Select exactly two points/references on the same opened contour, then run Preserve Distance.")
        return False

    norm = [_selected_item_path_piece(item) for item in selected]
    path_ids = {item[0] for item in norm if item[0] is not None}
    if len(path_ids) != 1:
        QtWidgets.QMessageBox.warning(None, "euSKlid", "Selected references must belong to the same Path.")
        return False

    path_id = norm[0][0]
    record_idx, record = _find_closed_path_record(path_id)
    if record is None:
        QtWidgets.QMessageBox.warning(None, "euSKlid", "Cannot find the selected Path record.")
        return False

    pieces = [int(norm[0][1]), int(norm[1][1])]
    try:
        max_index = len(record.get("pieces", []) or []) - 1
        if pieces[0] < 0 or pieces[1] < 0 or pieces[0] > max_index or pieces[1] > max_index:
            QtWidgets.QMessageBox.warning(None, "euSKlid", "Selected Path piece index is invalid.")
            return False
    except Exception:
        pass

    refs = []
    for idx, item in enumerate(selected[:2]):
        # The observer already resolved the semantic selection. Keep it as the
        # source of truth. Do not reproject it, otherwise point selections can
        # be downgraded back to segment selections.
        kind = item.get("kind") if isinstance(item, dict) else None
        uv = item.get("uv") if isinstance(item, dict) else None
        t = item.get("t", None) if isinstance(item, dict) else None
        if kind is None and not isinstance(item, dict):
            try:
                obj = item[2]
                if str(getattr(obj, "EuSKlidPieceType", "") or "") == "center":
                    kind = "center"
            except Exception:
                pass

        if kind not in ("point", "segment", "center"):
            kind = "segment"

        if uv is None:
            try:
                piece = (record.get("pieces", []) or [])[pieces[idx]]
                if kind == "center":
                    uv = _piece_center_uv(piece)
                elif kind == "point":
                    uv = _piece_point_at_t(piece, 0.0 if float(t or 0.5) <= 0.5 else 1.0)
                else:
                    uv = _piece_point_at_t(piece, 0.5)
            except Exception:
                uv = None

        refs.append({
            "piece": int(pieces[idx]),
            "uv": uv,
            "t": float(t if t is not None else (0.0 if kind == "point" else 0.5)),
            "kind": kind,
        })

    start_ref, end_ref = refs
    distance_value = _distance_value_for_refs(record, start_ref, end_ref)

    overload = {
        "kind": "distance",
        "pieces": list(dict.fromkeys(pieces)),
        "range": {
            "mode": "distance_refs",
            "start": start_ref,
            "end": end_ref,
            "value": distance_value,
        },
        "strength": "protected_user_intent",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    record.setdefault("overloads", []).append(overload)
    _sync_closed_paths_to_sketch()

    try:
        record_idx, record = _find_closed_path_record(path_id)
        group = ensure_path_instance_group(App.ActiveDocument, path_id=record.get("id") or path_id, label=record.get("label") or path_id)
        drawn = _render_distance_overload(record, overload.get("range", {}) or {}, group=group)
        _track_closed_path_objects(drawn, path_id=record.get("id") or path_id)
        App.ActiveDocument.recompute()
    except Exception:
        pass

    try:
        App.Console.PrintMessage(
            "euSKlid Path: distance overload preserved (%s/%s).\n" % (
                start_ref.get("kind"),
                end_ref.get("kind"),
            )
        )
    except Exception:
        App.Console.PrintMessage("euSKlid Path: distance overload preserved.\n")

    return True


class _TangentOverloadSelectionObserver:
    def __init__(self):
        self.selected = []
        self.seen = set()

    def _parse_payload(self, *args):
        # FreeCAD usually calls addSelection(doc, obj, sub, pnt).
        # Older paths may provide only (doc, obj).
        if len(args) >= 4:
            return args[0], args[1], args[3]
        if len(args) >= 2:
            return args[0], args[1], None
        return None, None, None

    def addSelection(self, *args):
        try:
            doc_name, obj_name, hit_world = self._parse_payload(*args)
            obj = None
            try:
                doc = App.getDocument(str(doc_name)) if doc_name else App.ActiveDocument
                obj = doc.getObject(str(obj_name)) if doc is not None and obj_name else None
            except Exception:
                obj = None
            item = _object_closed_path_piece(obj)
            if item is None:
                try:
                    Gui.Selection.clearSelection()
                except Exception:
                    pass
                App.Console.PrintMessage("euSKlid Path: Preserve Tangent accepts only closed Path pieces.\n")
                return
            click_uv = None
            try:
                record_idx, record = _find_closed_path_record(item[0])
                plane = record.get("plane") if record is not None else None
                if hit_world is not None and plane is not None and hasattr(plane, "world_to_uv"):
                    click_uv = plane.world_to_uv((float(hit_world.x), float(hit_world.y), float(hit_world.z)))
            except Exception:
                click_uv = None
            try:
                record_idx, record = _find_closed_path_record(item[0])
                semantic = _distance_selection_kind(record, int(item[1]), click_uv)
            except Exception:
                semantic = {
                    "kind": "segment",
                    "piece": int(item[1]),
                    "uv": click_uv,
                    "t": 0.5,
                }

            sel_item = {
                "path_id": item[0],
                "piece": int(item[1]),
                "uv": semantic.get("uv"),
                "object": item[2],
                "kind": semantic.get("kind"),
                "t": semantic.get("t", 0.5),
            }
            key = (item[0], int(item[1]), round(float(click_uv[0]), 7) if click_uv is not None else None, round(float(click_uv[1]), 7) if click_uv is not None else None)
            if key in self.seen:
                try:
                    Gui.Selection.clearSelection()
                except Exception:
                    pass
                return
            if self.selected and item[0] != _selected_item_path_piece(self.selected[0])[0]:
                QtWidgets.QMessageBox.warning(None, "euSKlid", "Selected pieces must belong to the same Path.")
                self.stop(clear=True)
                return
            self.seen.add(key)
            self.selected.append(sel_item)
            try:
                App.Console.PrintMessage(
                    "euSKlid Path: Preserve Tangent selected piece %s/%s (%d/2).\n" % (item[0], item[1], len(self.selected))
                )
            except Exception:
                pass
            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass
            if len(self.selected) >= 2:
                selected = list(self.selected[:2])
                self.stop(clear=True)
                _add_tangent_overload_for_pieces(selected, interactive=True)
        except Exception as e:
            try:
                self.stop(clear=True)
            except Exception:
                pass
            App.Console.PrintError("euSKlid Path Preserve Tangent observer error: %s\n" % str(e))

    def removeSelection(self, *args):
        pass

    def setSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass

    def stop(self, clear=False):
        global _ACTIVE_OVERLOAD_SESSION
        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass
        if clear:
            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass
        if _ACTIVE_OVERLOAD_SESSION is self:
            _ACTIVE_OVERLOAD_SESSION = None
        try:
            Gui.updateGui()
        except Exception:
            pass



class _ColinearityOverloadSelectionObserver:
    def __init__(self):
        self.selected = []
        self.seen = set()

    def _parse_payload(self, *args):
        if len(args) >= 4:
            return args[0], args[1], args[3]
        if len(args) >= 2:
            return args[0], args[1], None
        return None, None, None

    def addSelection(self, *args):
        try:
            doc_name, obj_name, hit_world = self._parse_payload(*args)
            obj = None
            try:
                doc = App.getDocument(str(doc_name)) if doc_name else App.ActiveDocument
                obj = doc.getObject(str(obj_name)) if doc is not None and obj_name else None
            except Exception:
                obj = None
            item = _object_closed_path_piece(obj)
            if item is None:
                try:
                    Gui.Selection.clearSelection()
                except Exception:
                    pass
                App.Console.PrintMessage("euSKlid Path: Preserve Colinearity accepts only closed Path pieces.\n")
                return

            sel_item = {"path_id": item[0], "piece": int(item[1]), "uv": None, "object": item[2]}
            key = (item[0], int(item[1]))
            if key in self.seen:
                try:
                    Gui.Selection.clearSelection()
                except Exception:
                    pass
                return
            if self.selected and item[0] != _selected_item_path_piece(self.selected[0])[0]:
                QtWidgets.QMessageBox.warning(None, "euSKlid", "Selected segments must belong to the same Path.")
                self.stop(clear=True)
                return

            self.seen.add(key)
            self.selected.append(sel_item)
            try:
                App.Console.PrintMessage(
                    "euSKlid Path: Preserve Colinearity selected segment %s/%s (%d/2).\n" % (item[0], item[1], len(self.selected))
                )
            except Exception:
                pass
            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass
            if len(self.selected) >= 2:
                selected = list(self.selected[:2])
                self.stop(clear=True)
                _add_colinearity_overload_for_pieces(selected, interactive=True)
        except Exception as e:
            try:
                self.stop(clear=True)
            except Exception:
                pass
            App.Console.PrintError("euSKlid Path Preserve Colinearity observer error: %s\n" % str(e))

    def removeSelection(self, *args):
        pass

    def setSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass

    def stop(self, clear=False):
        global _ACTIVE_OVERLOAD_SESSION
        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass
        if clear:
            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass
        if _ACTIVE_OVERLOAD_SESSION is self:
            _ACTIVE_OVERLOAD_SESSION = None
        try:
            Gui.updateGui()
        except Exception:
            pass



class _AngleOverloadSelectionObserver:
    def __init__(self):
        self.selected = []
        self.seen = set()

    def _parse_payload(self, *args):
        if len(args) >= 4:
            return args[0], args[1], args[3]
        if len(args) >= 2:
            return args[0], args[1], None
        return None, None, None

    def addSelection(self, *args):
        try:
            doc_name, obj_name, hit_world = self._parse_payload(*args)
            obj = None
            try:
                doc = App.getDocument(str(doc_name)) if doc_name else App.ActiveDocument
                obj = doc.getObject(str(obj_name)) if doc is not None and obj_name else None
            except Exception:
                obj = None

            item = _object_closed_path_piece(obj)
            if item is None:
                try:
                    Gui.Selection.clearSelection()
                except Exception:
                    pass
                App.Console.PrintMessage("euSKlid Path: Preserve Angle accepts only closed Path pieces.\n")
                return

            click_uv = None
            try:
                record_idx, record = _find_closed_path_record(item[0])
                plane = record.get("plane") if record is not None else None
                click_uv = _distance_world_to_uv(plane, hit_world)
                if click_uv is None:
                    click_uv = _distance_selectionex_uv(item[0], obj_name=str(obj_name) if obj_name else None)
            except Exception:
                click_uv = None

            sel_item = {"path_id": item[0], "piece": int(item[1]), "uv": click_uv, "object": item[2]}
            key = (item[0], int(item[1]))
            if key in self.seen:
                try:
                    Gui.Selection.clearSelection()
                except Exception:
                    pass
                return
            if self.selected and item[0] != _selected_item_path_piece(self.selected[0])[0]:
                QtWidgets.QMessageBox.warning(None, "euSKlid", "Selected segments must belong to the same Path.")
                self.stop(clear=True)
                return

            self.seen.add(key)
            self.selected.append(sel_item)
            try:
                App.Console.PrintMessage(
                    "euSKlid Path: Preserve Angle selected segment %s/%s (%d/2).\n" % (item[0], item[1], len(self.selected))
                )
            except Exception:
                pass

            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass

            if len(self.selected) >= 2:
                selected = list(self.selected[:2])
                self.stop(clear=True)
                _add_angle_overload_for_pieces(selected, interactive=True)
        except Exception as e:
            try:
                self.stop(clear=True)
            except Exception:
                pass
            App.Console.PrintError("euSKlid Path Preserve Angle observer error: %s\n" % str(e))

    def removeSelection(self, *args):
        pass

    def setSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass

    def stop(self, clear=False):
        global _ACTIVE_OVERLOAD_SESSION
        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass
        if clear:
            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass
        if _ACTIVE_OVERLOAD_SESSION is self:
            _ACTIVE_OVERLOAD_SESSION = None
        try:
            Gui.updateGui()
        except Exception:
            pass



class _RadiusOverloadSelectionObserver:
    def _parse_payload(self, *args):
        if len(args) >= 2:
            return args[0], args[1]
        return None, None

    def addSelection(self, *args):
        try:
            doc_name, obj_name = self._parse_payload(*args)
            obj = None
            try:
                doc = App.getDocument(str(doc_name)) if doc_name else App.ActiveDocument
                obj = doc.getObject(str(obj_name)) if doc is not None and obj_name else None
            except Exception:
                obj = None
            item = _object_closed_path_piece(obj)
            if item is None:
                try:
                    Gui.Selection.clearSelection()
                except Exception:
                    pass
                App.Console.PrintMessage("euSKlid Path: Preserve Radius accepts only closed Path arcs.\n")
                return
            selected = [{"path_id": item[0], "piece": int(item[1]), "uv": None, "object": item[2]}]
            self.stop(clear=True)
            _add_radius_overload_for_pieces(selected, interactive=True)
        except Exception as e:
            try:
                self.stop(clear=True)
            except Exception:
                pass
            App.Console.PrintError("euSKlid Path Preserve Radius observer error: %s\n" % str(e))

    def removeSelection(self, *args):
        pass

    def setSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass

    def stop(self, clear=False):
        global _ACTIVE_OVERLOAD_SESSION
        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass
        if clear:
            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass
        if _ACTIVE_OVERLOAD_SESSION is self:
            _ACTIVE_OVERLOAD_SESSION = None
        try:
            Gui.updateGui()
        except Exception:
            pass



class _DistanceOverloadSelectionObserver:
    def __init__(self):
        self.selected = []
        self.seen = set()

    def _parse_payload(self, *args):
        if len(args) >= 4:
            return args[0], args[1], args[3]
        if len(args) >= 2:
            return args[0], args[1], None
        return None, None, None

    def addSelection(self, *args):
        try:
            doc_name, obj_name, hit_world = self._parse_payload(*args)
            obj = None
            try:
                doc = App.getDocument(str(doc_name)) if doc_name else App.ActiveDocument
                obj = doc.getObject(str(obj_name)) if doc is not None and obj_name else None
            except Exception:
                obj = None

            item = _object_closed_path_piece(obj)
            if item is None:
                try:
                    Gui.Selection.clearSelection()
                except Exception:
                    pass
                App.Console.PrintMessage("euSKlid Path: Preserve Distance accepts only closed Path pieces.\n")
                return

            click_uv = None
            try:
                record_idx, record = _find_closed_path_record(item[0])
                plane = record.get("plane") if record is not None else None

                click_uv = _distance_world_to_uv(plane, hit_world)

                if click_uv is None:
                    click_uv = _distance_selectionex_uv(item[0], obj_name=str(obj_name) if obj_name else None)

            except Exception:
                click_uv = None

            try:
                record_idx, record = _find_closed_path_record(item[0])
                if str(getattr(obj, "EuSKlidPieceType", "") or "") == "center":
                    piece = (record.get("pieces", []) or [])[int(item[1])]
                    center_uv = _piece_center_uv(piece)
                    semantic = {
                        "kind": "center",
                        "piece": int(item[1]),
                        "uv": center_uv,
                        "t": 0.5,
                    }
                else:
                    semantic = _distance_selection_kind(record, int(item[1]), click_uv)
            except Exception:
                semantic = {
                    "kind": "segment",
                    "piece": int(item[1]),
                    "uv": click_uv,
                    "t": 0.5,
                }

            sel_item = {
                "path_id": item[0],
                "piece": int(item[1]),
                "uv": semantic.get("uv"),
                "object": item[2],
                "kind": semantic.get("kind"),
                "t": semantic.get("t", 0.5),
            }
            key = (item[0], int(item[1]), round(float(click_uv[0]), 7) if click_uv is not None else None, round(float(click_uv[1]), 7) if click_uv is not None else None)
            if key in self.seen:
                try:
                    Gui.Selection.clearSelection()
                except Exception:
                    pass
                return
            if self.selected and item[0] != _selected_item_path_piece(self.selected[0])[0]:
                QtWidgets.QMessageBox.warning(None, "euSKlid", "Selected references must belong to the same Path.")
                self.stop(clear=True)
                return

            self.seen.add(key)
            self.selected.append(sel_item)
            try:
                App.Console.PrintMessage(
                    "euSKlid Path: Preserve Distance %s reference %d/2 selected%s.\n" % (
                        str(semantic.get("kind", "unknown")),
                        len(self.selected),
                        "" if click_uv is not None else " (no pick point)",
                    )
                )
            except Exception:
                pass

            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass

            if len(self.selected) >= 2:
                selected = list(self.selected[:2])
                self.stop(clear=True)
                _add_distance_overload_for_pieces(selected, interactive=True)
        except Exception as e:
            try:
                self.stop(clear=True)
            except Exception:
                pass
            App.Console.PrintError("euSKlid Path Preserve Distance observer error: %s\n" % str(e))

    def removeSelection(self, *args):
        pass

    def setSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass

    def stop(self, clear=False):
        global _ACTIVE_OVERLOAD_SESSION
        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass
        if clear:
            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass
        if _ACTIVE_OVERLOAD_SESSION is self:
            _ACTIVE_OVERLOAD_SESSION = None
        try:
            Gui.updateGui()
        except Exception:
            pass


def _stop_active_overload_session():
    global _ACTIVE_OVERLOAD_SESSION
    sess = _ACTIVE_OVERLOAD_SESSION
    if sess is None:
        return False
    try:
        sess.stop(clear=True)
    except Exception:
        _ACTIVE_OVERLOAD_SESSION = None
    return True



def mark_selected_path_tangent_overload():
    """Start an interactive tool to mark two closed Path pieces as tangent overload.

    If exactly two closed Path pieces are already selected, the overload is
    added immediately for compatibility.  Otherwise, the command installs a
    FreeCAD selection observer and waits for two clicks on closed Path pieces.
    """
    global _ACTIVE_OVERLOAD_SESSION

    # Compatibility path: use an existing valid selection when available.
    selected = _selected_closed_path_pieces()
    if len(selected) == 2:
        return _add_tangent_overload_for_pieces(selected, interactive=False)

    # Start/restart an interactive selection session.
    _stop_active_overload_session()
    try:
        Gui.Selection.clearSelection()
    except Exception:
        pass
    observer = _TangentOverloadSelectionObserver()
    try:
        Gui.Selection.addObserver(observer)
        _ACTIVE_OVERLOAD_SESSION = observer
        elog.help("Preserve Tangent active: click two closed Path pieces.")
        return True
    except Exception as e:
        _ACTIVE_OVERLOAD_SESSION = None
        App.Console.PrintError("euSKlid Path: cannot start Preserve Tangent selection: %s\n" % str(e))
        return False


def mark_selected_path_colinearity_overload():
    """Start an interactive tool to mark two closed Path segments as colinear."""
    global _ACTIVE_OVERLOAD_SESSION

    selected = _selected_closed_path_pieces()
    if len(selected) == 2:
        return _add_colinearity_overload_for_pieces(selected, interactive=False)

    _stop_active_overload_session()
    try:
        Gui.Selection.clearSelection()
    except Exception:
        pass
    observer = _ColinearityOverloadSelectionObserver()
    try:
        Gui.Selection.addObserver(observer)
        _ACTIVE_OVERLOAD_SESSION = observer
        elog.help("Preserve Colinearity active: click two closed Path segments.")
        return True
    except Exception as e:
        _ACTIVE_OVERLOAD_SESSION = None
        App.Console.PrintError("euSKlid Path: cannot start Preserve Colinearity selection: %s\n" % str(e))
        return False



def mark_selected_path_angle_overload():
    """Start an interactive tool to mark two closed Path segments as angle overload."""
    global _ACTIVE_OVERLOAD_SESSION

    selected = _selected_closed_path_pieces()
    if len(selected) == 2:
        enriched = []
        for path_id, piece_index, obj in selected:
            uv = None
            try:
                uv = _distance_selectionex_uv(path_id, obj_name=str(getattr(obj, "Name", "")))
            except Exception:
                uv = None
            if uv is None:
                enriched = []
                break
            enriched.append({
                "path_id": str(path_id),
                "piece": int(piece_index),
                "uv": uv,
                "object": obj,
            })
        if len(enriched) == 2:
            return _add_angle_overload_for_pieces(enriched, interactive=False)
        try:
            App.Console.PrintMessage("euSKlid Path: Preserve Angle needs two clicked segment references; starting interactive selection.\n")
        except Exception:
            pass

    _stop_active_overload_session()
    try:
        Gui.Selection.clearSelection()
    except Exception:
        pass
    observer = _AngleOverloadSelectionObserver()
    try:
        Gui.Selection.addObserver(observer)
        _ACTIVE_OVERLOAD_SESSION = observer
        elog.help("Preserve Angle active: click two closed Path segments.")
        return True
    except Exception as e:
        _ACTIVE_OVERLOAD_SESSION = None
        App.Console.PrintError("euSKlid Path: cannot start Preserve Angle selection: %s\n" % str(e))
        return False



def mark_selected_path_radius_overload():
    """Start an interactive tool to mark one closed Path arc as radius overload."""
    global _ACTIVE_OVERLOAD_SESSION

    selected = _selected_closed_path_pieces()
    if len(selected) == 1:
        return _add_radius_overload_for_pieces(selected, interactive=False)

    _stop_active_overload_session()
    try:
        Gui.Selection.clearSelection()
    except Exception:
        pass
    observer = _RadiusOverloadSelectionObserver()
    try:
        Gui.Selection.addObserver(observer)
        _ACTIVE_OVERLOAD_SESSION = observer
        elog.help("Preserve Radius active: click one closed Path arc.")
        return True
    except Exception as e:
        _ACTIVE_OVERLOAD_SESSION = None
        App.Console.PrintError("euSKlid Path: cannot start Preserve Radius selection: %s\n" % str(e))
        return False



def mark_selected_path_distance_overload():
    """Start an interactive tool to mark two Path references as distance overload."""
    global _ACTIVE_OVERLOAD_SESSION

    selected = _selected_closed_path_pieces()
    if len(selected) == 2:
        return _add_distance_overload_for_pieces(selected, interactive=False)

    _stop_active_overload_session()
    try:
        Gui.Selection.clearSelection()
    except Exception:
        pass
    observer = _DistanceOverloadSelectionObserver()
    try:
        Gui.Selection.addObserver(observer)
        _ACTIVE_OVERLOAD_SESSION = observer
        elog.help("Preserve Distance active: click two closed Path references.")
        return True
    except Exception as e:
        _ACTIVE_OVERLOAD_SESSION = None
        App.Console.PrintError("euSKlid Path: cannot start Preserve Distance selection: %s\n" % str(e))
        return False
