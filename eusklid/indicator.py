
import math

import FreeCAD as App
import FreeCADGui as Gui
import Part
from .core.groups import (
    ensure_euclid_groups,
    get_frame_group,
    get_indicators_group,
    get_transient_group,
)
from .core.config import get_config

_REFRESH_TIMER = None
_REFRESH_GUARD = False
_LAST_CAMERA_SIG = None
_FRAME_STATE = None
_ARROW_STATE = None
_SNAP_STATE = None
_SELECTED_STATE = None
_MANUAL_STATE = None

_FRAME_OBJECTS = []
_ARROW_OBJECTS = []
_CANDIDATE_OBJECTS = []
_SNAP_OBJECTS = []
_PREVIEW_OBJECTS = []
_HIGHLIGHT_OBJECTS = []
_SELECTED_OBJECTS = []
_MANUAL_OBJECTS = []


_REMOVE_OBJS_GUARD = False

# ---------------------------------------------------------------------------
# Configuration access
# ---------------------------------------------------------------------------

def _cfg():
    return get_config()

def _cfg_uv():
    return _cfg()["gui"]["uv"]

def _cfg_arrows():
    return _cfg()["gui"]["arrows"]

def _cfg_points():
    return _cfg()["gui"]["points"]

def _cfg_point_size():
    return float(_cfg_points().get("size", 20.0))

def _cfg_point_alpha():
    return int(_cfg_points().get("alpha", 30))


def _cfg_refresh_interval_ms():
    try:
        cfg = get_config()
        return int(cfg.get("feeling", {}).get("refresh_interval_ms", 120))
    except Exception:
        return 120

# ---------------------------------------------------------------------------
# Grouping helpers
# ---------------------------------------------------------------------------


def _cfg_highlight():
    try:
        return _cfg().get("work", {}).get("highlight", _cfg().get("highlight", {}))
    except Exception:
        return {}


def _highlight_style():
    cfg = _cfg_highlight()
    try:
        color = tuple(cfg.get("color", (1.0, 0.8, 0.1)))
        width = float(cfg.get("thickness", 3.0))
        alpha = int(cfg.get("alpha", 40))
        return color, width, alpha
    except Exception:
        return (1.0, 0.8, 0.1), 3.0, 40

def _group_frame(obj):
    try:
        doc = App.ActiveDocument
        if doc:
            ensure_euclid_groups(doc)
            get_frame_group(doc).addObject(obj)
    except Exception:
        pass
    return obj

def _group_indicators(obj):
    try:
        doc = App.ActiveDocument
        if doc:
            ensure_euclid_groups(doc)
            get_indicators_group(doc).addObject(obj)
    except Exception:
        pass
    return obj

def _group_transient(obj):
    try:
        doc = App.ActiveDocument
        if doc:
            ensure_euclid_groups(doc)
            get_transient_group(doc).addObject(obj)
    except Exception:
        pass
    return obj

# ---------------------------------------------------------------------------
# View / screen scaling helpers
# ---------------------------------------------------------------------------


def _pixels_to_world(plane, uv, px):
    try:
        view = Gui.ActiveDocument.ActiveView
        cam = view.getCameraNode()

        try:
            w, h = view.getSize()
            vh = max(1.0, float(h))
        except Exception:
            vh = 1000.0

        world = App.Vector(*plane.uv_to_world(uv))

        # caméra orthographique
        try:
            cam_height = float(cam.height.getValue())
            return max(1e-6, cam_height * float(px) / vh)
        except Exception:
            pass

        # caméra perspective : utiliser la profondeur selon l'axe de vue,
        # pas la distance euclidienne brute caméra->point
        try:
            pos = cam.position.getValue()
            cam_pos = App.Vector(float(pos[0]), float(pos[1]), float(pos[2]))

            ori = cam.orientation.getValue()
            rot = App.Rotation(float(ori[0]), float(ori[1]), float(ori[2]), float(ori[3]))

            # axe optique caméra (FreeCAD/Coin : -Z local vers l'avant)
            view_dir = rot.multVec(App.Vector(0.0, 0.0, -1.0))
            delta = world.sub(cam_pos)
            depth = max(1e-6, delta.dot(view_dir))

            angle = float(cam.heightAngle.getValue())
            visible_h = 2.0 * depth * math.tan(angle * 0.5)
            return max(1e-6, visible_h * float(px) / vh)
        except Exception:
            pass

    except Exception:
        pass

    return max(1e-6, float(px) * 0.01)


def _make_screen_scaled_point(plane, uv, color, size=20.0, transparency=30, name="euSKlidPoint"):
    doc = App.ActiveDocument
    if doc is None:
        return None

    if size is None:
        size = _cfg_point_size()

    try:
        size = float(size)
    except Exception:
        size = 20.0
    if size <= 0.0:
        size = 20.0

    ensure_euclid_groups(doc)
    center = App.Vector(*plane.uv_to_world(uv))
    radius = _pixels_to_world(plane, uv, size * 0.5)
    min_radius = _pixels_to_world(plane, uv, 4.0)
    radius = max(radius, min_radius)

    obj = _make_sphere(
        center,
        radius,
        color,
        transparency=transparency,
        name=name,
    )
    if obj is not None:
        _group_transient(obj)
    return obj

def _safe_import_draft():
    try:
        import Draft
        return Draft
    except Exception:
        return None

def _set_fc_axis_cross_visible(visible):
    try:
        if Gui.ActiveDocument is not None:
            Gui.ActiveDocument.ActiveView.setAxisCross(bool(visible))
    except Exception:
        pass

def _remove_objs(objs):
    return []

def _pixels_to_fontsize(px):
    try:
        return max(8, int(round(float(px))))
    except Exception:
        return 12

def _camera_signature():
    try:
        view = Gui.ActiveDocument.ActiveView

        parts = []

        # position caméra / centre via camera node si dispo
        try:
            cam = view.getCameraNode()
            pos = cam.position.getValue()
            parts.extend([
                round(float(pos[0]), 6),
                round(float(pos[1]), 6),
                round(float(pos[2]), 6),
            ])
        except Exception:
            pass

        # taille viewport
        try:
            w, h = view.getSize()
            parts.extend([int(w), int(h)])
        except Exception:
            pass

        # paramètres ortho / perspective
        try:
            cam = view.getCameraNode()
            try:
                parts.append(round(float(cam.height.getValue()), 6))
            except Exception:
                pass
            try:
                parts.append(round(float(cam.heightAngle.getValue()), 6))
            except Exception:
                pass
        except Exception:
            pass

        if not parts:
            return None

        return tuple(parts)
    except Exception:
        return None

def _ensure_refresh_timer():
    global _REFRESH_TIMER
    if _REFRESH_TIMER is not None:
        return

    from .qt_compat import QtCore, QtGui

    app = QtGui.QApplication.instance()
    if app is None:
        return

    _REFRESH_TIMER = QtCore.QTimer(app)
    _REFRESH_TIMER.setInterval(max(50, _cfg_refresh_interval_ms()))
    _REFRESH_TIMER.timeout.connect(refresh_all_indicators)
    _REFRESH_TIMER.start()

    try:
        print("euSKlid indicator refresh timer started")
    except Exception:
        pass

def _show_point(plane, uv, kind="snap", size=None, manual=False, bucket="snap"):
    doc = App.ActiveDocument
    if doc is None:
        return None

    if size is None:
        size = _cfg_point_size()

    try:
        size = float(size)
    except Exception:
        size = 20.0
    if size <= 0.0:
        size = 20.0

    try:
        ensure_euclid_groups(doc)
        center = App.Vector(*plane.uv_to_world(uv))
        radius = _pixels_to_world(plane, uv, size * 0.5)
        min_radius = _pixels_to_world(plane, uv, 4.0)
        radius = max(radius, min_radius)

        obj = _make_sphere(
            center,
            radius,
            _point_color(kind, manual),
            transparency=_cfg_point_alpha(),
            name="euSKlidPoint",
        )
        if obj is None:
            return None
        _group_transient(obj)

        if bucket == "snap":
            global _SNAP_OBJECTS
            clear_snap()
            _SNAP_OBJECTS = [obj]
        elif bucket == "manual":
            global _MANUAL_OBJECTS
            clear_manual()
            _MANUAL_OBJECTS = [obj]
        elif bucket == "selected":
            global _SELECTED_OBJECTS
            clear_selected()
            _SELECTED_OBJECTS = [obj]

        try:
            doc.recompute()
        except Exception:
            pass
        return obj
    except Exception as e:
        import traceback
        print("_show_point error:", e)
        traceback.print_exc()
        return None

def _point_color(kind="snap", manual=False):
    colors = _cfg_points().get("colors", {})
    if kind == "selected":
        return tuple(colors.get("selected", (0.0, 0.5, 1.0)))
    if kind == "manual":
        return tuple(colors.get("fixed", (0.7, 0.2, 1.0)))
    if kind == "hover":
        return tuple(colors.get("hover", (1.0, 0.0, 1.0)))
    if kind == "marker":
        return tuple(colors.get("marker", (1.0, 0.5, 0.0)))
    return tuple(colors.get("snap", (0.2, 0.9, 0.2)))

def _make_frame_glyph_lines(doc, plane, segments_uv, color, width=4, base_name="euSKlidFrameGlyph"):
    objs = []

    def W(uv):
        return App.Vector(*plane.uv_to_world(uv))

    for i, (a_uv, b_uv) in enumerate(segments_uv):
        obj = Draft.make_line(W(a_uv), W(b_uv))
        _group_frame(obj)
        try:
            obj.ViewObject.LineWidth = width
            obj.ViewObject.LineColor = color
            obj.ViewObject.Selectable = False
        except Exception:
            pass
        objs.append(obj)

    return objs

# ---------------------------------------------------------------------------
# Refresh loop
# ---------------------------------------------------------------------------


def refresh_all_indicators():
    global _REFRESH_GUARD, _LAST_CAMERA_SIG

    try:
        if _REFRESH_TIMER is not None:
            desired = max(50, _cfg_refresh_interval_ms())
            if _REFRESH_TIMER.interval() != desired:
                _REFRESH_TIMER.setInterval(desired)
    except Exception:
        pass

    if _REFRESH_GUARD:
        return

    sig = _camera_signature()
    if sig is None:
        return

    if sig == _LAST_CAMERA_SIG:
        return

    _LAST_CAMERA_SIG = sig
    _REFRESH_GUARD = True

    try:
        if _FRAME_STATE is not None:
            show_uv_frame(
                _FRAME_STATE["plane"],
                _FRAME_STATE.get("origin_uv", (0.0, 0.0)),
                from_refresh=True,
            )

        if _ARROW_STATE is not None:
            if _ARROW_STATE.get("kind") == "arrow":
                show_arrow(
                    _ARROW_STATE["plane"],
                    _ARROW_STATE["origin_uv"],
                    _ARROW_STATE["direction_uv"],
                )
            elif _ARROW_STATE.get("kind") == "direction_field":
                show_direction_field(
                    _ARROW_STATE["plane"],
                    _ARROW_STATE["origin_uv"],
                    _ARROW_STATE["ref_direction_uv"],
                    _ARROW_STATE["normal_uv"],
                    count=_ARROW_STATE.get("count", 10),
                )

        if _SNAP_STATE is not None and _SNAP_STATE.get("kind") == "snap":
            show_snap_point(
                _SNAP_STATE["plane"],
                _SNAP_STATE["uv"],
                kind=_SNAP_STATE.get("snap_kind", "snap"),
                size=_SNAP_STATE.get("size", _cfg_point_size()),
            )

        if _MANUAL_STATE is not None and _MANUAL_STATE.get("kind") == "manual":
            show_manual_point(
                _MANUAL_STATE["plane"],
                _MANUAL_STATE["uv"],
                size=_MANUAL_STATE.get("size", _cfg_point_size()),
            )

        if _SELECTED_STATE is not None:
            skind = _SELECTED_STATE.get("kind")
            if skind == "anchors":
                show_selected_anchors(
                    _SELECTED_STATE["plane"],
                    _SELECTED_STATE.get("anchors", []),
                )
            else:
                show_selected_point(
                    _SELECTED_STATE["plane"],
                    _SELECTED_STATE["uv"],
                    size=_SELECTED_STATE.get("size", _cfg_point_size()),
                    manual=_SELECTED_STATE.get("manual", False),
                )
    except Exception:
        pass
    finally:
        _REFRESH_GUARD = False

# ---------------------------------------------------------------------------
# Clear / reset helpers
# ---------------------------------------------------------------------------


def clear_frame():
    global _FRAME_OBJECTS
    _FRAME_OBJECTS = _remove_objs(_FRAME_OBJECTS)

def clear_arrow():
    global _ARROW_OBJECTS
    _ARROW_OBJECTS = _remove_objs(_ARROW_OBJECTS)

def clear_candidates():
    global _CANDIDATE_OBJECTS
    _CANDIDATE_OBJECTS = _remove_objs(_CANDIDATE_OBJECTS)

def clear_snap():
    global _SNAP_OBJECTS
    _SNAP_OBJECTS = _remove_objs(_SNAP_OBJECTS)

def clear_manual():
    global _MANUAL_OBJECTS
    _MANUAL_OBJECTS = _remove_objs(_MANUAL_OBJECTS)

def clear_preview():
    global _PREVIEW_OBJECTS
    _PREVIEW_OBJECTS = _remove_objs(_PREVIEW_OBJECTS)

def clear_highlight():
    global _HIGHLIGHT_OBJECTS
    _HIGHLIGHT_OBJECTS = _remove_objs(_HIGHLIGHT_OBJECTS)

def clear_selected():
    global _SELECTED_OBJECTS
    _SELECTED_OBJECTS = _remove_objs(_SELECTED_OBJECTS)

def clear_all():
    reset_overlay_states(clear_frame_too=True)
    try:
        if App.ActiveDocument:
            App.ActiveDocument.recompute()
    except Exception:
        pass
def reset_overlay_states(clear_frame_too=False):
    global _FRAME_STATE, _ARROW_STATE, _SNAP_STATE, _MANUAL_STATE, _SELECTED_STATE
    try:
        clear_snap()
    except Exception:
        pass
    try:
        clear_manual()
    except Exception:
        pass
    try:
        clear_selected()
    except Exception:
        pass
    try:
        clear_preview()
    except Exception:
        pass
    try:
        clear_highlight()
    except Exception:
        pass
    try:
        clear_candidates()
    except Exception:
        pass
    try:
        clear_arrow()
    except Exception:
        pass

    _SNAP_STATE = None
    _MANUAL_STATE = None
    _SELECTED_STATE = None
    _ARROW_STATE = None

    if clear_frame_too:
        try:
            clear_frame()
        except Exception:
            pass
        _FRAME_STATE = None
        try:
            _set_fc_axis_cross_visible(True)
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Primitive overlay factories
# ---------------------------------------------------------------------------


def _make_sphere(center, radius, color, transparency=50, name="euSKlidMarker"):
    doc = App.ActiveDocument
    obj = doc.addObject("Part::Feature", name)
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

# ---------------------------------------------------------------------------
# Point overlays
# ---------------------------------------------------------------------------


def show_snap_point(plane, uv, kind="snap", size=None):
    global _SNAP_STATE
    _SNAP_STATE = {
        "kind": "snap",
        "plane": plane,
        "uv": uv,
        "snap_kind": kind,
        "size": size,
    }
    _ensure_refresh_timer()
    return _show_point(plane, uv, kind=kind, size=size, bucket="snap")

def show_manual_point(plane, uv, size=None):
    global _MANUAL_STATE
    _MANUAL_STATE = {
        "kind": "manual",
        "plane": plane,
        "uv": uv,
        "size": size,
    }
    _ensure_refresh_timer()
    return _show_point(plane, uv, kind="manual", size=size, bucket="manual")

def show_selected_point(plane, uv, size=None, manual=False):
    global _SELECTED_OBJECTS, _SELECTED_STATE

    if size is None:
        size = _cfg_point_size()

    _SELECTED_STATE = {
        "plane": plane,
        "uv": uv,
        "size": size,
        "manual": manual,
    }

    clear_selected()
    _ensure_refresh_timer()

    doc = App.ActiveDocument
    if doc is None:
        return None

    try:
        obj = _make_screen_scaled_point(
            plane,
            uv,
            color=_point_color("selected", manual=manual),
            size=size,
            transparency=_cfg_point_alpha(),
            name="euSKlidSelectedPoint",
        )
        _SELECTED_OBJECTS = [obj] if obj is not None else []
        if doc is not None:
            doc.recompute()
        return obj
    except Exception as e:
        import traceback
        print("show_selected_point error:", e)
        traceback.print_exc()
        clear_selected()
        return None

def show_hover_point(plane, uv, size=None):
    global _SNAP_STATE
    _SNAP_STATE = {
        "kind": "snap",
        "plane": plane,
        "uv": uv,
        "snap_kind": "hover",
        "size": size,
    }
    _ensure_refresh_timer()
    return _show_point(plane, uv, kind="hover", size=size, bucket="snap")

def show_marker_point(plane, uv, size=None):
    global _SNAP_STATE
    _SNAP_STATE = {
        "kind": "snap",
        "plane": plane,
        "uv": uv,
        "snap_kind": "marker",
        "size": size,
    }
    _ensure_refresh_timer()
    return _show_point(plane, uv, kind="marker", size=size, bucket="snap")

# ---------------------------------------------------------------------------
# Selected anchor overlays
# ---------------------------------------------------------------------------


def show_selected_line(plane, origin_uv, direction_uv, half_len=1000.0):
    from .math2d import visible_segment_for_line

    doc = App.ActiveDocument
    if doc is None:
        return None

    a_uv, b_uv = visible_segment_for_line(origin_uv, direction_uv, half_len)
    a = App.Vector(*plane.uv_to_world(a_uv))
    b = App.Vector(*plane.uv_to_world(b_uv))

    obj = doc.addObject("Part::Feature", "euSKlidSelectedLine")
    _group_transient(obj)
    obj.Shape = Part.makeLine(a, b)

    try:
        obj.ViewObject.LineColor = (0.0, 0.5, 1.0)
        obj.ViewObject.LineWidth = 3
        obj.ViewObject.Transparency = 20
        obj.ViewObject.Selectable = False
    except Exception:
        pass

    return obj

def show_selected_circle(plane, center_uv, radius):
    doc = App.ActiveDocument
    if doc is None:
        return None
    center = App.Vector(*plane.uv_to_world(center_uv))
    obj = doc.addObject("Part::Feature", "euSKlidSelectedCircle")
    obj.Shape = Part.Circle(center, App.Vector(plane.normal.x, plane.normal.y, plane.normal.z), float(radius)).toShape()
    try:
        obj.ViewObject.LineColor = (0.0, 0.5, 1.0)
        obj.ViewObject.LineWidth = 3
        obj.ViewObject.Transparency = 20
        obj.ViewObject.Selectable = False
    except Exception:
        pass
    return obj

def show_selected_anchors(plane, anchors):
    global _SELECTED_OBJECTS, _SELECTED_STATE

    clear_selected()
    _ensure_refresh_timer()

    doc = App.ActiveDocument
    if doc is None:
        return

    objs = []
    state_anchors = []

    try:
        for a in anchors or []:
            ak = a.get("kind")
            if ak == "point":
                uv = a.get("point")
                if uv is None:
                    continue
                size = a.get("size", _cfg_point_size())
                manual = bool(a.get("manual", False))
                obj = _make_screen_scaled_point(
                    plane,
                    uv,
                    color=_point_color("selected", manual=manual),
                    size=size,
                    transparency=_cfg_point_alpha(),
                    name="euSKlidSelectedPoint",
                )
                if obj is not None:
                    objs.append(obj)
                    state_anchors.append({
                        "kind": "point",
                        "point": uv,
                        "size": size,
                        "manual": manual,
                    })
            elif ak == "line":
                obj = show_selected_line(plane, a["origin"], a["direction"])
                if obj is not None:
                    objs.append(obj)
                    state_anchors.append({
                        "kind": "line",
                        "origin": a["origin"],
                        "direction": a["direction"],
                    })
            elif ak == "circle":
                obj = show_selected_circle(plane, a["center"], a["radius"])
                if obj is not None:
                    objs.append(obj)
                    state_anchors.append({
                        "kind": "circle",
                        "center": a["center"],
                        "radius": a["radius"],
                    })

        _SELECTED_OBJECTS = [o for o in objs if o is not None]
        _SELECTED_STATE = {
            "kind": "anchors",
            "plane": plane,
            "anchors": state_anchors,
        }

        doc.recompute()
    except Exception as e:
        import traceback
        print("show_selected_anchors error:", e)
        traceback.print_exc()
        clear_selected()

# ---------------------------------------------------------------------------
# Frame and direction overlays
# ---------------------------------------------------------------------------


def show_uv_frame(plane, origin_uv=(0.0, 0.0), axis_len=140.0, head=35.0, from_refresh=False):
    global _FRAME_OBJECTS, _FRAME_STATE

    _FRAME_STATE = {
        "plane": plane,
        "origin_uv": origin_uv,
    }
    if not from_refresh:
        _ensure_refresh_timer()

    clear_frame()
    _set_fc_axis_cross_visible(False)

    Draft = _safe_import_draft()
    if Draft is None or App.ActiveDocument is None:
        return

    from .math2d import normalize, perp, scale, add

    doc = App.ActiveDocument
    ensure_euclid_groups(doc)

    uv_cfg = _cfg_uv()

    FRAME_PX = float(uv_cfg.get("size", 150.0))
    ARROW_PX = float(uv_cfg.get("arrow_size", 30.0))
    LABEL_PX = max(10.0, FRAME_PX * 0.12)
    LINE_W = int(uv_cfg.get("thickness", 3))

    axis_len = _pixels_to_world(plane, origin_uv, FRAME_PX)
    head = _pixels_to_world(plane, origin_uv, ARROW_PX)
    font_size = _pixels_to_fontsize(LABEL_PX)

    def W(uv):
        return App.Vector(*plane.uv_to_world(uv))

    udir = (1.0, 0.0)
    vdir = (0.0, 1.0)
    upn = normalize(perp(udir))
    vpn = normalize(perp(vdir))

    o = origin_uv
    u_tip = add(o, scale(udir, axis_len))
    v_tip = add(o, scale(vdir, axis_len))

    u_h1 = add(u_tip, add(scale(udir, -head), scale(upn, head * 0.55)))
    u_h2 = add(u_tip, add(scale(udir, -head), scale(upn, -head * 0.55)))

    v_h1 = add(v_tip, add(scale(vdir, -head), scale(vpn, head * 0.55)))
    v_h2 = add(v_tip, add(scale(vdir, -head), scale(vpn, -head * 0.55)))

    objs = []

    for a, b in [(o, u_tip), (u_tip, u_h1), (u_tip, u_h2)]:
        obj = Draft.make_line(W(a), W(b))
        _group_frame(obj)
        try:
            obj.ViewObject.LineWidth = LINE_W
            obj.ViewObject.LineColor = (1.0, 0.0, 0.0)
            obj.ViewObject.Selectable = False
        except Exception:
            pass
        objs.append(obj)

    for a, b in [(o, v_tip), (v_tip, v_h1), (v_tip, v_h2)]:
        obj = Draft.make_line(W(a), W(b))
        _group_frame(obj)
        try:
            obj.ViewObject.LineWidth = LINE_W
            obj.ViewObject.LineColor = (0.0, 1.0, 0.0)
            obj.ViewObject.Selectable = False
        except Exception:
            pass
        objs.append(obj)


    # --- tags U / V comme glyphes géométriques screen-scaled ---
    try:
        TAG_PX = 18.0
        tag = _pixels_to_world(plane, origin_uv, TAG_PX)
        half = tag * 0.5

        # base U
        u_base = add(u_tip, scale(udir, head * 1.25))
        ux, uy = u_base

        u_segments = [
            ((ux - half * 0.45, uy + half * 0.50), (ux - half * 0.45, uy - half * 0.50)),
            ((ux - half * 0.45, uy - half * 0.50), (ux + half * 0.45, uy - half * 0.50)),
            ((ux + half * 0.45, uy + half * 0.50), (ux + half * 0.45, uy - half * 0.50)),
        ]

        for i, (a_uv, b_uv) in enumerate(u_segments):
            obj = Draft.make_line(W(a_uv), W(b_uv))
            _group_frame(obj)
            try:
                obj.ViewObject.LineWidth = LINE_W
                obj.ViewObject.LineColor = (1.0, 0.0, 0.0)
                obj.ViewObject.Selectable = False
            except Exception:
                pass
            objs.append(obj)

        # base V
        v_base = add(v_tip, scale(vdir, head * 1.25))
        vx, vy = v_base

        v_segments = [
            ((vx - half * 0.45, vy + half * 0.50), (vx, vy - half * 0.50)),
            ((vx, vy - half * 0.50), (vx + half * 0.45, vy + half * 0.50)),
        ]

        for i, (a_uv, b_uv) in enumerate(v_segments):
            obj = Draft.make_line(W(a_uv), W(b_uv))
            _group_frame(obj)
            try:
                obj.ViewObject.LineWidth = LINE_W
                obj.ViewObject.LineColor = (0.0, 1.0, 0.0)
                obj.ViewObject.Selectable = False
            except Exception:
                pass
            objs.append(obj)

    except Exception as e:
        print("UV glyph error:", e)

    _FRAME_OBJECTS = objs
    _set_fc_axis_cross_visible(False)
    doc.recompute()

def show_arrow(plane, origin_uv, direction_uv, length=80.0, head=20.0):
    global _ARROW_OBJECTS, _ARROW_STATE
    _ARROW_STATE = {
        "kind": "arrow",
        "plane": plane,
        "origin_uv": origin_uv,
        "direction_uv": direction_uv,
    }

    clear_arrow()
    _ensure_refresh_timer()

    Draft = _safe_import_draft()
    if Draft is None or App.ActiveDocument is None:
        return

    from .math2d import normalize, scale, add, perp

    doc = App.ActiveDocument
    ensure_euclid_groups(doc)

    ar_cfg = _cfg_arrows()

    ARROW_LEN_PX = float(ar_cfg.get("length", 60.0))
    ARROW_HEAD_PX = float(ar_cfg.get("arrow_size", 10.0))
    LINE_W = int(ar_cfg.get("thickness", 5))
    COLOR = tuple(ar_cfg.get("color", (0.0, 0.5, 1.0)))
    ALPHA = int(ar_cfg.get("alpha", 0))

    length = _pixels_to_world(plane, origin_uv, ARROW_LEN_PX)
    head = _pixels_to_world(plane, origin_uv, ARROW_HEAD_PX)

    d = normalize(direction_uv)
    if d == (0.0, 0.0):
        return

    n = normalize(perp(d))
    tail = origin_uv
    tip = add(tail, scale(d, float(length)))
    left = add(tip, add(scale(d, -float(head)), scale(n, float(head) * 0.6)))
    right = add(tip, add(scale(d, -float(head)), scale(n, -float(head) * 0.6)))

    objs = []

    def W(uv):
        return App.Vector(*plane.uv_to_world(uv))

    for a, b in [(tail, tip), (tip, left), (tip, right)]:
        obj = Draft.make_line(W(a), W(b))
        _group_indicators(obj)
        try:
            obj.ViewObject.LineWidth = LINE_W
            obj.ViewObject.LineColor = COLOR
            obj.ViewObject.Transparency = ALPHA
            obj.ViewObject.Selectable = False
        except Exception:
            pass
        objs.append(obj)

    _ARROW_OBJECTS = objs
    doc.recompute()

def show_direction_field(plane, origin_uv, ref_direction_uv, normal_uv, count=10, spacing=30.0, length=30.0, head=5.0):
    global _ARROW_OBJECTS, _ARROW_STATE
    _ARROW_STATE = {
        "kind": "direction_field",
        "plane": plane,
        "origin_uv": origin_uv,
        "ref_direction_uv": ref_direction_uv,
        "normal_uv": normal_uv,
        "count": count,
    }

    clear_arrow()
    _ensure_refresh_timer()

    Draft = _safe_import_draft()
    if Draft is None or App.ActiveDocument is None:
        return

    from .math2d import normalize, scale, add, sub

    doc = App.ActiveDocument
    ensure_euclid_groups(doc)

    ar_cfg = _cfg_arrows()

    STEP_PX = float(ar_cfg.get("step", 30.0))
    LEN_PX = float(ar_cfg.get("length", 60.0))
    HEAD_PX = float(ar_cfg.get("arrow_size", 10.0))
    LINE_W = int(ar_cfg.get("thickness", 5))
    COLOR = tuple(ar_cfg.get("color", (0.0, 0.5, 1.0)))
    ALPHA = int(ar_cfg.get("alpha", 0))
    count = int(ar_cfg.get("count", count))

    spacing = _pixels_to_world(plane, origin_uv, STEP_PX)
    length = _pixels_to_world(plane, origin_uv, LEN_PX)
    head = _pixels_to_world(plane, origin_uv, HEAD_PX)

    ref_d = normalize(ref_direction_uv)
    n = normalize(normal_uv)
    if ref_d == (0.0, 0.0) or n == (0.0, 0.0):
        return

    start = sub(origin_uv, scale(ref_d, spacing * (count - 1) * 0.5))
    objs = []

    def W(uv):
        return App.Vector(*plane.uv_to_world(uv))

    for i in range(count):
        base = add(start, scale(ref_d, spacing * i))
        tip = add(base, scale(n, length))
        left = add(tip, add(scale(n, -head), scale(ref_d, head * 0.35)))
        right = add(tip, add(scale(n, -head), scale(ref_d, -head * 0.35)))

        for a, b in [(base, tip), (tip, left), (tip, right)]:
            obj = Draft.make_line(W(a), W(b))
            _group_indicators(obj)
            try:
                obj.ViewObject.LineWidth = LINE_W
                obj.ViewObject.LineColor = COLOR
                obj.ViewObject.Transparency = ALPHA
                obj.ViewObject.Selectable = False
            except Exception:
                pass
            objs.append(obj)

    _ARROW_OBJECTS = objs
    doc.recompute()

# ---------------------------------------------------------------------------
# Candidate / preview / highlight overlays
# ---------------------------------------------------------------------------


def show_circle_candidates(plane, candidates):
    clear_candidates()
    doc = App.ActiveDocument
    if doc is None:
        return
    items = []
    def world(uv):
        return App.Vector(*plane.uv_to_world(uv))
    try:
        for i, cand in enumerate(candidates):
            center = world(cand["center"])
            radius = float(cand["radius"])
            cobj = doc.addObject("Part::Feature", f"euSKlidCandidateCircle{i+1}")
            cobj.Shape = Part.Circle(center, App.Vector(plane.normal.x, plane.normal.y, plane.normal.z), radius).toShape()
            try:
                cobj.ViewObject.LineColor = (0.2, 0.5, 1.0)
                cobj.ViewObject.LineWidth = 2.0
                cobj.ViewObject.Transparency = 60
                cobj.ViewObject.Selectable = False
            except Exception:
                pass
            items.append(cobj)
        global _CANDIDATE_OBJECTS
        _CANDIDATE_OBJECTS = items
        doc.recompute()
    except Exception:
        clear_candidates()

def show_preview_line(plane, p1_uv, p2_uv):
    clear_preview()
    doc = App.ActiveDocument
    if doc is None:
        return
    try:
        obj = doc.addObject("Part::Feature", "euSKlidPreviewLine")
        p1 = App.Vector(*plane.uv_to_world(p1_uv))
        p2 = App.Vector(*plane.uv_to_world(p2_uv))
        obj.Shape = Part.makeLine(p1, p2)
        obj.ViewObject.LineColor = (0.1, 0.4, 1.0)
        obj.ViewObject.LineWidth = 2.0
        obj.ViewObject.Transparency = 70
        obj.ViewObject.Selectable = False
        global _PREVIEW_OBJECTS
        _PREVIEW_OBJECTS = [obj]
        doc.recompute()
    except Exception:
        clear_preview()

def show_preview_circle(plane, center_uv, radius):
    clear_preview()
    doc = App.ActiveDocument
    if doc is None:
        return
    try:
        obj = doc.addObject("Part::Feature", "euSKlidPreviewCircle")
        center = App.Vector(*plane.uv_to_world(center_uv))
        obj.Shape = Part.Circle(center, App.Vector(plane.normal.x, plane.normal.y, plane.normal.z), float(radius)).toShape()
        obj.ViewObject.LineColor = (0.1, 0.4, 1.0)
        obj.ViewObject.LineWidth = 2.0
        obj.ViewObject.Transparency = 70
        obj.ViewObject.Selectable = False
        global _PREVIEW_OBJECTS
        _PREVIEW_OBJECTS = [obj]
        doc.recompute()
    except Exception:
        clear_preview()

def show_highlight_line(plane, origin_uv, direction_uv, half_len=1000.0):
    clear_highlight()
    from .math2d import visible_segment_for_line
    doc = App.ActiveDocument
    if doc is None:
        return
    try:
        a_uv, b_uv = visible_segment_for_line(origin_uv, direction_uv, half_len)
        a = App.Vector(*plane.uv_to_world(a_uv))
        b = App.Vector(*plane.uv_to_world(b_uv))
        obj = doc.addObject("Part::Feature", "euSKlidHighlightLine")
        obj.Shape = Part.makeLine(a, b)
        color, width, alpha = _highlight_style()
        obj.ViewObject.LineColor = color
        obj.ViewObject.LineWidth = width
        obj.ViewObject.Transparency = alpha
        obj.ViewObject.Selectable = False
        global _HIGHLIGHT_OBJECTS
        _HIGHLIGHT_OBJECTS = [obj]
        doc.recompute()
    except Exception:
        clear_highlight()

def show_highlight_circle(plane, center_uv, radius):
    clear_highlight()
    doc = App.ActiveDocument
    if doc is None:
        return
    try:
        center = App.Vector(*plane.uv_to_world(center_uv))
        obj = doc.addObject("Part::Feature", "euSKlidHighlightCircle")
        obj.Shape = Part.Circle(center, App.Vector(plane.normal.x, plane.normal.y, plane.normal.z), float(radius)).toShape()
        color, width, alpha = _highlight_style()
        obj.ViewObject.LineColor = color
        obj.ViewObject.LineWidth = width
        obj.ViewObject.Transparency = alpha
        obj.ViewObject.Selectable = False
        global _HIGHLIGHT_OBJECTS
        _HIGHLIGHT_OBJECTS = [obj]
        doc.recompute()
    except Exception:
        clear_highlight()

def refresh_camera_scaled_overlays():
    return


def show_preview_polygon(plane, vertices_uv):
    clear_preview()
    doc = App.ActiveDocument
    if doc is None:
        return
    try:
        objs = []
        if not vertices_uv or len(vertices_uv) < 2:
            return
        for i in range(len(vertices_uv)):
            a_uv = vertices_uv[i]
            b_uv = vertices_uv[(i + 1) % len(vertices_uv)]
            obj = doc.addObject("Part::Feature", "euSKlidPreviewPolygonEdge")
            a = App.Vector(*plane.uv_to_world(a_uv))
            b = App.Vector(*plane.uv_to_world(b_uv))
            obj.Shape = Part.makeLine(a, b)
            try:
                obj.ViewObject.LineColor = (0.1, 0.4, 1.0)
                obj.ViewObject.LineWidth = 2.0
                obj.ViewObject.Transparency = 70
                obj.ViewObject.Selectable = False
            except Exception:
                pass
            objs.append(obj)
        global _PREVIEW_OBJECTS
        _PREVIEW_OBJECTS = objs
        doc.recompute()
    except Exception:
        clear_preview()


