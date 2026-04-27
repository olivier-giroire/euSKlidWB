import math

import FreeCAD as App
import FreeCADGui as Gui
from pivy import coin

from .core.config import get_config

# ---------------------------------------------------------------------------
# euSKlid indicator overlay - Coin3D implementation
#
# Document objects are reserved for persistent geometry. All interactive
# indicators in this module are Coin3D scenegraph nodes:
# - snap / hover / selected / manual points
# - preview lines / circles / polygons
# - highlight lines / circles
# - circle candidates
# - arrows / direction fields (compatibility helpers)
# ---------------------------------------------------------------------------

_ROOTS = {}

_LAYER_POINTS = "points"
_LAYER_SELECTED = "selected"
_LAYER_PREVIEW = "preview"
_LAYER_HIGHLIGHT = "highlight"
_LAYER_CANDIDATES = "candidates"
_LAYER_ARROW = "arrow"
_LAYER_FRAME = "frame"

# Keep state minimal; refresh is explicit through show_* calls.
_SNAP_STATE = None
_MANUAL_STATE = None
_SELECTED_STATE = None


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _config():
    try:
        return get_config() or {}
    except Exception:
        return {}


def _dict_get(path, default):
    cur = _config()
    try:
        for key in str(path).split("."):
            if not isinstance(cur, dict) or key not in cur:
                return default
            cur = cur[key]
        return cur
    except Exception:
        return default


def _as_color(value, default):
    try:
        if value is None:
            return tuple(default)
        if isinstance(value, str):
            s = value.strip().lstrip("#")
            if len(s) == 6:
                return (
                    int(s[0:2], 16) / 255.0,
                    int(s[2:4], 16) / 255.0,
                    int(s[4:6], 16) / 255.0,
                )
        vals = tuple(float(v) for v in value)
        if len(vals) >= 3:
            return (vals[0], vals[1], vals[2])
    except Exception:
        pass
    return tuple(default)


def _as_float(value, default):
    try:
        return float(value)
    except Exception:
        return float(default)


def _as_int(value, default):
    try:
        return int(value)
    except Exception:
        return int(default)


def _points_cfg():
    return _dict_get("gui.points", {}) or {}


def _point_colors_cfg():
    cfg = _points_cfg()
    return cfg.get("colors", {}) if isinstance(cfg, dict) else {}


def _point_size_px():
    cfg = _points_cfg()
    return _as_float(cfg.get("size", 20.0) if isinstance(cfg, dict) else 20.0, 20.0)


def _point_alpha():
    cfg = _points_cfg()
    return _as_int(cfg.get("alpha", 30) if isinstance(cfg, dict) else 30, 30)


def _point_color(kind="snap", manual=False):
    colors = _point_colors_cfg()
    if manual or kind == "manual":
        return _as_color(colors.get("fixed"), (0.7, 0.2, 1.0))
    if kind == "selected":
        return _as_color(colors.get("selected"), (0.0, 0.5, 1.0))
    if kind == "hover":
        return _as_color(colors.get("hover"), (1.0, 0.0, 1.0))
    if kind == "marker":
        return _as_color(colors.get("marker"), (1.0, 0.5, 0.0))
    return _as_color(colors.get("snap"), (0.2, 0.9, 0.2))


def _style_from_config(path, fallback_color, fallback_width, fallback_alpha=0):
    cfg = _dict_get(path, {}) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    color = _as_color(cfg.get("color"), fallback_color)
    # Historical config sometimes uses "thickness" rather than "width".
    width = _as_float(cfg.get("thickness", cfg.get("width", fallback_width)), fallback_width)
    alpha = _as_int(cfg.get("alpha", fallback_alpha), fallback_alpha)
    return color, width, alpha


def _preview_style(kind="preview"):
    # Single construction-preview style shared by line/circle/polygon previews.
    return _style_from_config("preview", (0.1, 0.4, 1.0), 2.0, 70)


def _highlight_style():
    return _style_from_config("highlight", (1.0, 0.8, 0.1), 3.0, 40)


def _candidate_style():
    return _preview_style("candidate")


def _arrow_style():
    cfg = _dict_get("gui.arrows", {}) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    color = _as_color(cfg.get("color"), (0.0, 0.5, 1.0))
    width = _as_float(cfg.get("thickness", 4.0), 4.0)
    alpha = _as_int(cfg.get("alpha", 0), 0)
    return color, width, alpha


# ---------------------------------------------------------------------------
# Scenegraph helpers
# ---------------------------------------------------------------------------

def _active_scene_graph():
    try:
        if Gui.ActiveDocument is None:
            return None
        view = Gui.ActiveDocument.ActiveView
        if view is None:
            return None
        return view.getSceneGraph()
    except Exception:
        return None


def _ensure_root(layer):
    root = _ROOTS.get(layer)
    if root is not None:
        return root
    sg = _active_scene_graph()
    if sg is None:
        return None
    root = coin.SoSeparator()
    # Overlay nodes are visual only; make them unpickable so they do not intercept mouse clicks.
    try:
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        root.addChild(pick)
    except Exception:
        pass
    try:
        root.ref()
    except Exception:
        pass
    sg.addChild(root)
    _ROOTS[layer] = root
    return root


def _clear_layer(layer):
    root = _ROOTS.get(layer)
    if root is None:
        return
    try:
        root.removeAllChildren()
    except Exception:
        pass


def _clear_layers(layers):
    for layer in layers:
        _clear_layer(layer)


def _material(color, alpha=0):
    mat = coin.SoMaterial()
    try:
        mat.diffuseColor.setValue(float(color[0]), float(color[1]), float(color[2]))
        transparency = max(0.0, min(1.0, float(alpha) / 100.0))
        mat.transparency.setValue(transparency)
    except Exception:
        pass
    return mat


def _line_style(width=2.0):
    style = coin.SoDrawStyle()
    try:
        style.lineWidth.setValue(float(width))
    except Exception:
        try:
            style.lineWidth = float(width)
        except Exception:
            pass
    return style


def _coord_node(points):
    coords = coin.SoCoordinate3()
    vals = []
    for p in points:
        try:
            vals.append((float(p.x), float(p.y), float(p.z)))
        except Exception:
            vals.append((float(p[0]), float(p[1]), float(p[2])))
    try:
        coords.point.setValues(0, len(vals), vals)
    except Exception:
        for i, v in enumerate(vals):
            coords.point.set1Value(i, *v)
    return coords


def _line_node(points, color, width=2.0, alpha=0):
    sep = coin.SoSeparator()
    sep.addChild(_material(color, alpha))
    sep.addChild(_line_style(width))
    sep.addChild(_coord_node(points))
    line = coin.SoLineSet()
    try:
        line.numVertices.setValues(0, 1, [len(points)])
    except Exception:
        pass
    sep.addChild(line)
    return sep


def _plane_world(plane, uv):
    return App.Vector(*plane.uv_to_world(uv))


def _pixels_to_world(plane, uv, px):
    try:
        view = Gui.ActiveDocument.ActiveView
        cam = view.getCameraNode()
        try:
            _w, h = view.getSize()
            vh = max(1.0, float(h))
        except Exception:
            vh = 1000.0
        world = _plane_world(plane, uv)
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


def _point_radius_world(plane, uv, size_px=None):
    if size_px is None:
        size_px = _point_size_px()
    try:
        size_px = float(size_px)
    except Exception:
        size_px = _point_size_px()
    # radius is half the configured point diameter-ish size.
    r = _pixels_to_world(plane, uv, max(1.0, size_px) * 0.5)
    return max(r, _pixels_to_world(plane, uv, 3.0))


def _sphere_node(world, radius, color, alpha=0):
    sep = coin.SoSeparator()
    tr = coin.SoTranslation()
    tr.translation.setValue(float(world.x), float(world.y), float(world.z))
    sphere = coin.SoSphere()
    try:
        sphere.radius.setValue(float(radius))
    except Exception:
        sphere.radius = float(radius)
    sep.addChild(_material(color, alpha))
    sep.addChild(tr)
    sep.addChild(sphere)
    return sep


def _arc_points(plane, center_uv, radius, a0, a1, steps=96):
    try:
        radius = float(radius)
        a0 = float(a0)
        a1 = float(a1)
    except Exception:
        return []
    delta = a1 - a0
    steps = max(8, min(192, int(abs(delta) / (2.0 * math.pi) * steps) + 8))
    pts = []
    for i in range(steps + 1):
        t = i / float(steps)
        a = a0 + delta * t
        uv = (center_uv[0] + radius * math.cos(a), center_uv[1] + radius * math.sin(a))
        pts.append(_plane_world(plane, uv))
    return pts


def _circle_points(plane, center_uv, radius, steps=128):
    return _arc_points(plane, center_uv, radius, 0.0, 2.0 * math.pi, steps=steps)


# ---------------------------------------------------------------------------
# Point overlays
# ---------------------------------------------------------------------------

def _draw_layer_point(layer, plane, uv, color, size=None, manual=False):
    root = _ensure_root(layer)
    if root is None:
        return None
    _clear_layer(layer)
    try:
        world = _plane_world(plane, uv)
        radius = _point_radius_world(plane, uv, size)
        alpha = _point_alpha()
        root.addChild(_sphere_node(world, radius, color, alpha=alpha))
    except Exception:
        return None
    return None


def show_snap_point(plane, uv, kind="snap", size=None):
    global _SNAP_STATE
    _SNAP_STATE = {"kind": kind, "plane": plane, "uv": uv, "size": size}
    return _draw_layer_point(_LAYER_POINTS, plane, uv, _point_color(kind), size=size)


def show_hover_point(plane, uv, size=None):
    global _SNAP_STATE
    _SNAP_STATE = {"kind": "hover", "plane": plane, "uv": uv, "size": size}
    return _draw_layer_point(_LAYER_POINTS, plane, uv, _point_color("hover"), size=size)


def show_marker_point(plane, uv, size=None):
    global _SNAP_STATE
    _SNAP_STATE = {"kind": "marker", "plane": plane, "uv": uv, "size": size}
    return _draw_layer_point(_LAYER_POINTS, plane, uv, _point_color("marker"), size=size)


def show_manual_point(plane, uv, size=None):
    global _MANUAL_STATE
    _MANUAL_STATE = {"kind": "manual", "plane": plane, "uv": uv, "size": size}
    return _draw_layer_point(_LAYER_POINTS, plane, uv, _point_color("manual", manual=True), size=size)


def show_selected_point(plane, uv, size=None, manual=False):
    global _SELECTED_STATE
    _SELECTED_STATE = {"kind": "point", "plane": plane, "uv": uv, "size": size, "manual": manual}
    return _draw_layer_point(_LAYER_SELECTED, plane, uv, _point_color("selected", manual=manual), size=size)


def show_selected_anchors(plane, anchors):
    global _SELECTED_STATE
    root = _ensure_root(_LAYER_SELECTED)
    if root is None:
        return None
    _clear_layer(_LAYER_SELECTED)
    stored = []
    for a in anchors or []:
        try:
            ak = a.get("kind")
        except Exception:
            continue
        if ak == "point":
            uv = a.get("point")
            if uv is None:
                continue
            size = a.get("size", _point_size_px())
            manual = bool(a.get("manual", False))
            try:
                world = _plane_world(plane, uv)
                radius = _point_radius_world(plane, uv, size)
                root.addChild(_sphere_node(world, radius, _point_color("selected", manual=manual), alpha=_point_alpha()))
                stored.append(dict(a))
            except Exception:
                pass
        elif ak == "line":
            try:
                show_selected_line(plane, a["origin"], a["direction"], clear=False)
                stored.append(dict(a))
            except Exception:
                pass
        elif ak == "circle":
            try:
                show_selected_circle(plane, a["center"], a["radius"], clear=False)
                stored.append(dict(a))
            except Exception:
                pass
    _SELECTED_STATE = {"kind": "anchors", "plane": plane, "anchors": stored}
    return None


# ---------------------------------------------------------------------------
# Selected line/circle overlays
# ---------------------------------------------------------------------------

def _visible_segment_for_line(origin_uv, direction_uv, half_len=1000.0):
    try:
        from .math2d import visible_segment_for_line
        return visible_segment_for_line(origin_uv, direction_uv, half_len)
    except Exception:
        dx, dy = direction_uv
        n = math.hypot(dx, dy) or 1.0
        dx, dy = dx / n, dy / n
        return (
            (origin_uv[0] - dx * half_len, origin_uv[1] - dy * half_len),
            (origin_uv[0] + dx * half_len, origin_uv[1] + dy * half_len),
        )


def show_selected_line(plane, origin_uv, direction_uv, half_len=1000.0, clear=True):
    root = _ensure_root(_LAYER_SELECTED)
    if root is None:
        return None
    if clear:
        _clear_layer(_LAYER_SELECTED)
    color = _point_color("selected")
    a_uv, b_uv = _visible_segment_for_line(origin_uv, direction_uv, half_len)
    root.addChild(_line_node([_plane_world(plane, a_uv), _plane_world(plane, b_uv)], color, width=3.0, alpha=20))
    return None


def show_selected_circle(plane, center_uv, radius, clear=True):
    root = _ensure_root(_LAYER_SELECTED)
    if root is None:
        return None
    if clear:
        _clear_layer(_LAYER_SELECTED)
    color = _point_color("selected")
    pts = _circle_points(plane, center_uv, radius)
    root.addChild(_line_node(pts, color, width=3.0, alpha=20))
    return None


# ---------------------------------------------------------------------------
# Preview / highlight / candidates
# ---------------------------------------------------------------------------

def show_preview_line(plane, p1_uv, p2_uv):
    root = _ensure_root(_LAYER_PREVIEW)
    if root is None:
        return None
    _clear_layer(_LAYER_PREVIEW)
    color, width, alpha = _preview_style("line")
    root.addChild(_line_node([_plane_world(plane, p1_uv), _plane_world(plane, p2_uv)], color, width=width, alpha=alpha))
    return None


def show_preview_circle(plane, center_uv, radius):
    root = _ensure_root(_LAYER_PREVIEW)
    if root is None:
        return None
    _clear_layer(_LAYER_PREVIEW)
    color, width, alpha = _preview_style("circle")
    root.addChild(_line_node(_circle_points(plane, center_uv, radius), color, width=width, alpha=alpha))
    return None


def show_preview_polygon(plane, vertices_uv):
    root = _ensure_root(_LAYER_PREVIEW)
    if root is None:
        return None
    _clear_layer(_LAYER_PREVIEW)
    if not vertices_uv or len(vertices_uv) < 2:
        return None
    pts = []
    for uv in vertices_uv:
        pts.append(_plane_world(plane, uv))
    pts.append(_plane_world(plane, vertices_uv[0]))
    color, width, alpha = _preview_style("line")
    root.addChild(_line_node(pts, color, width=width, alpha=alpha))
    return None


def show_highlight_line(plane, origin_uv, direction_uv, half_len=1000.0):
    root = _ensure_root(_LAYER_HIGHLIGHT)
    if root is None:
        return None
    _clear_layer(_LAYER_HIGHLIGHT)
    color, width, alpha = _highlight_style()
    a_uv, b_uv = _visible_segment_for_line(origin_uv, direction_uv, half_len)
    root.addChild(_line_node([_plane_world(plane, a_uv), _plane_world(plane, b_uv)], color, width=width, alpha=alpha))
    return None


def show_highlight_circle(plane, center_uv, radius):
    root = _ensure_root(_LAYER_HIGHLIGHT)
    if root is None:
        return None
    _clear_layer(_LAYER_HIGHLIGHT)
    color, width, alpha = _highlight_style()
    root.addChild(_line_node(_circle_points(plane, center_uv, radius), color, width=width, alpha=alpha))
    return None


def show_circle_candidates(plane, candidates):
    root = _ensure_root(_LAYER_CANDIDATES)
    if root is None:
        return None
    _clear_layer(_LAYER_CANDIDATES)
    color, width, alpha = _candidate_style()
    for cand in candidates or []:
        try:
            center = cand["center"]
            radius = cand["radius"]
        except Exception:
            continue
        root.addChild(_line_node(_circle_points(plane, center, radius), color, width=width, alpha=alpha))
    return None


# ---------------------------------------------------------------------------
# Arrows / frame compatibility
# ---------------------------------------------------------------------------

def show_uv_frame(plane, origin_uv=(0.0, 0.0), axis_len=140.0, head=35.0, from_refresh=False):
    # XY-only policy: no custom U/V frame overlay.
    clear_frame()
    return None


def show_arrow(plane, origin_uv, direction_uv, length=80.0, head=20.0):
    root = _ensure_root(_LAYER_ARROW)
    if root is None:
        return None
    _clear_layer(_LAYER_ARROW)
    try:
        from .math2d import normalize, scale, add, perp
        d = normalize(direction_uv)
        if d == (0.0, 0.0):
            return None
        n = normalize(perp(d))
        length_w = _pixels_to_world(plane, origin_uv, _as_float(_dict_get("gui.arrows.length", length), length))
        head_w = _pixels_to_world(plane, origin_uv, _as_float(_dict_get("gui.arrows.arrow_size", head), head))
        tail = origin_uv
        tip = add(tail, scale(d, length_w))
        left = add(tip, add(scale(d, -head_w), scale(n, head_w * 0.6)))
        right = add(tip, add(scale(d, -head_w), scale(n, -head_w * 0.6)))
        color, width, alpha = _arrow_style()
        for a, b in ((tail, tip), (tip, left), (tip, right)):
            root.addChild(_line_node([_plane_world(plane, a), _plane_world(plane, b)], color, width=width, alpha=alpha))
    except Exception:
        pass
    return None


def show_direction_field(plane, origin_uv, ref_direction_uv, normal_uv, count=10, spacing=30.0, length=30.0, head=5.0):
    root = _ensure_root(_LAYER_ARROW)
    if root is None:
        return None
    _clear_layer(_LAYER_ARROW)
    try:
        from .math2d import normalize, scale, add, sub
        ref_d = normalize(ref_direction_uv)
        n = normalize(normal_uv)
        if ref_d == (0.0, 0.0) or n == (0.0, 0.0):
            return None
        count = int(_dict_get("gui.arrows.count", count))
        step_w = _pixels_to_world(plane, origin_uv, _as_float(_dict_get("gui.arrows.step", spacing), spacing))
        len_w = _pixels_to_world(plane, origin_uv, _as_float(_dict_get("gui.arrows.length", length), length))
        head_w = _pixels_to_world(plane, origin_uv, _as_float(_dict_get("gui.arrows.arrow_size", head), head))
        start = sub(origin_uv, scale(ref_d, step_w * (count - 1) * 0.5))
        color, width, alpha = _arrow_style()
        for i in range(count):
            base = add(start, scale(ref_d, step_w * i))
            tip = add(base, scale(n, len_w))
            left = add(tip, add(scale(n, -head_w), scale(ref_d, head_w * 0.35)))
            right = add(tip, add(scale(n, -head_w), scale(ref_d, -head_w * 0.35)))
            for a, b in ((base, tip), (tip, left), (tip, right)):
                root.addChild(_line_node([_plane_world(plane, a), _plane_world(plane, b)], color, width=width, alpha=alpha))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Clear / refresh compatibility API
# ---------------------------------------------------------------------------

def clear_frame():
    _clear_layer(_LAYER_FRAME)


def clear_arrow():
    _clear_layer(_LAYER_ARROW)


def clear_candidates():
    _clear_layer(_LAYER_CANDIDATES)


def clear_snap():
    _clear_layer(_LAYER_POINTS)


def clear_manual():
    _clear_layer(_LAYER_POINTS)


def clear_selected():
    _clear_layer(_LAYER_SELECTED)


def clear_preview():
    _clear_layer(_LAYER_PREVIEW)


def clear_highlight():
    _clear_layer(_LAYER_HIGHLIGHT)


def clear_all():
    for layer in list(_ROOTS.keys()):
        _clear_layer(layer)


def reset_overlay_states(clear_frame_too=False):
    global _SNAP_STATE, _MANUAL_STATE, _SELECTED_STATE
    clear_snap()
    clear_manual()
    clear_selected()
    clear_preview()
    clear_highlight()
    clear_candidates()
    clear_arrow()
    if clear_frame_too:
        clear_frame()
    _SNAP_STATE = None
    _MANUAL_STATE = None
    _SELECTED_STATE = None


def refresh_camera_scaled_overlays():
    # Coin3D nodes are redrawn on demand by show_* calls. This function remains
    # for compatibility with existing controller calls.
    return None


def refresh_all_indicators():
    # Minimal compatibility refresh: redraw only point layers whose state is known.
    try:
        if _SNAP_STATE is not None:
            kind = _SNAP_STATE.get("kind", "snap")
            plane = _SNAP_STATE.get("plane")
            uv = _SNAP_STATE.get("uv")
            size = _SNAP_STATE.get("size")
            if plane is not None and uv is not None:
                _draw_layer_point(_LAYER_POINTS, plane, uv, _point_color(kind), size=size)
        if _MANUAL_STATE is not None:
            plane = _MANUAL_STATE.get("plane")
            uv = _MANUAL_STATE.get("uv")
            size = _MANUAL_STATE.get("size")
            if plane is not None and uv is not None:
                _draw_layer_point(_LAYER_POINTS, plane, uv, _point_color("manual", manual=True), size=size)
        if _SELECTED_STATE is not None:
            if _SELECTED_STATE.get("kind") == "anchors":
                show_selected_anchors(_SELECTED_STATE.get("plane"), _SELECTED_STATE.get("anchors", []))
            else:
                plane = _SELECTED_STATE.get("plane")
                uv = _SELECTED_STATE.get("uv")
                size = _SELECTED_STATE.get("size")
                manual = bool(_SELECTED_STATE.get("manual", False))
                if plane is not None and uv is not None:
                    _draw_layer_point(_LAYER_SELECTED, plane, uv, _point_color("selected", manual=manual), size=size)
    except Exception:
        pass
    return None
