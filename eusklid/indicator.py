import math

import FreeCAD as App
import FreeCADGui as Gui
from pivy import coin

from .core.config import get_config

# ---------------------------------------------------------------------------
# Coin3D point overlays
# ---------------------------------------------------------------------------
# Temporary interactive points are rendered in the active 3D view scene graph,
# not as FreeCAD document objects. This keeps the document clean and avoids
# removeObject recursion / stale preview artefacts.

_POINT_ROOTS = {}
_DEFAULT_POINT_SIZE = 20.0
_DEFAULT_POINT_ALPHA = 30


def _cfg():
    try:
        return get_config()
    except Exception:
        return {}


def _cfg_points():
    try:
        return _cfg().get("gui", {}).get("points", {})
    except Exception:
        return {}


def _cfg_point_size(default=_DEFAULT_POINT_SIZE):
    try:
        return float(_cfg_points().get("size", default))
    except Exception:
        return float(default)


def _cfg_point_alpha(default=_DEFAULT_POINT_ALPHA):
    try:
        return int(_cfg_points().get("alpha", default))
    except Exception:
        return int(default)


def _point_color(kind="snap", manual=False):
    colors = {}
    try:
        colors = _cfg_points().get("colors", {}) or {}
    except Exception:
        colors = {}

    if kind == "selected":
        return tuple(colors.get("selected", (0.0, 0.5, 1.0)))
    if kind == "manual" or manual:
        return tuple(colors.get("fixed", (0.7, 0.2, 1.0)))
    if kind == "hover":
        return tuple(colors.get("hover", (1.0, 0.0, 1.0)))
    if kind == "marker":
        return tuple(colors.get("marker", (1.0, 0.5, 0.0)))
    return tuple(colors.get("snap", (0.2, 0.9, 0.2)))


def _point_transparency_to_alpha():
    # FreeCAD transparency is 0 opaque -> 100 invisible.
    # Coin alpha is 1 opaque -> 0 invisible.
    try:
        transparency = max(0, min(100, _cfg_point_alpha()))
        return max(0.0, min(1.0, 1.0 - (float(transparency) / 100.0)))
    except Exception:
        return 0.7


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


def _ensure_point_overlay(layer):
    root = _POINT_ROOTS.get(layer)
    if root is not None:
        return root

    sg = _active_scene_graph()
    if sg is None:
        return None

    root = coin.SoSeparator()
    sg.addChild(root)
    _POINT_ROOTS[layer] = root
    return root


def _clear_layer(layer):
    root = _POINT_ROOTS.get(layer)
    if root is not None:
        try:
            root.removeAllChildren()
        except Exception:
            pass


def _clear_all_layers():
    for layer in list(_POINT_ROOTS.keys()):
        _clear_layer(layer)


def _pixels_to_world(plane, uv, px):
    try:
        view = Gui.ActiveDocument.ActiveView
        cam = view.getCameraNode()

        try:
            _w, h = view.getSize()
            vh = max(1.0, float(h))
        except Exception:
            vh = 1000.0

        world = App.Vector(*plane.uv_to_world(uv))

        # Orthographic camera: height is world-space viewport height.
        try:
            cam_height = float(cam.height.getValue())
            return max(1e-6, cam_height * float(px) / vh)
        except Exception:
            pass

        # Perspective camera: use depth along camera direction.
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


def _draw_point(world, radius, color):
    sep = coin.SoSeparator()

    mat = coin.SoMaterial()
    try:
        mat.diffuseColor.setValue(float(color[0]), float(color[1]), float(color[2]))
        mat.transparency.setValue(1.0 - _point_transparency_to_alpha())
    except Exception:
        mat.diffuseColor.setValue(1.0, 0.0, 1.0)

    tr = coin.SoTranslation()
    tr.translation.setValue(float(world.x), float(world.y), float(world.z))

    sphere = coin.SoSphere()
    sphere.radius = float(radius)

    sep.addChild(mat)
    sep.addChild(tr)
    sep.addChild(sphere)
    return sep


def _draw_layer_point(layer, plane, uv, color, size=None):
    root = _ensure_point_overlay(layer)
    if root is None:
        return None

    _clear_layer(layer)

    try:
        world = App.Vector(*plane.uv_to_world(uv))
    except Exception:
        return None

    try:
        px = float(size) if size is not None else _cfg_point_size()
    except Exception:
        px = _cfg_point_size()
    if px <= 0.0:
        px = _DEFAULT_POINT_SIZE

    radius = max(_pixels_to_world(plane, uv, px * 0.5), _pixels_to_world(plane, uv, 3.0))
    root.addChild(_draw_point(world, radius=radius, color=color))
    return None


# ---------------------------------------------------------------------------
# Public point API
# ---------------------------------------------------------------------------

def show_snap_point(plane, uv, kind="snap", size=None):
    # kind can be snap/hover/marker in a few call sites; keep it respected.
    return _draw_layer_point("snap", plane, uv, _point_color(kind), size=size)


def show_hover_point(plane, uv, size=None):
    return _draw_layer_point("hover", plane, uv, _point_color("hover"), size=size)


def show_marker_point(plane, uv, size=None):
    return _draw_layer_point("hover", plane, uv, _point_color("marker"), size=size)


def show_manual_point(plane, uv, size=None):
    return _draw_layer_point("manual", plane, uv, _point_color("manual", manual=True), size=size)


def show_selected_point(plane, uv, size=None, manual=False):
    color = _point_color("manual", manual=True) if manual else _point_color("selected")
    return _draw_layer_point("selected", plane, uv, color, size=size)


def show_selected_anchors(plane, anchors):
    root = _ensure_point_overlay("selected")
    if root is None:
        return None

    try:
        root.removeAllChildren()
    except Exception:
        pass

    for anchor in anchors or []:
        try:
            if anchor.get("kind") != "point":
                continue
            uv = anchor.get("point")
            if uv is None:
                continue
            size = anchor.get("size", None)
            manual = bool(anchor.get("manual", False))
            color = _point_color("manual", manual=True) if manual else _point_color("selected")

            world = App.Vector(*plane.uv_to_world(uv))
            try:
                px = float(size) if size is not None else _cfg_point_size()
            except Exception:
                px = _cfg_point_size()
            radius = max(_pixels_to_world(plane, uv, px * 0.5), _pixels_to_world(plane, uv, 3.0))
            root.addChild(_draw_point(world, radius=radius, color=color))
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Compatibility cleanup API
# ---------------------------------------------------------------------------
# These functions used to delete FreeCAD document objects. Points are now pure
# Coin3D overlays, so cleanup only clears scene graph layers.

def clear_all():
    _clear_all_layers()


def clear_snap():
    _clear_layer("snap")


def clear_manual():
    _clear_layer("manual")


def clear_selected():
    _clear_layer("selected")


def clear_preview():
    _clear_layer("hover")


def clear_hover():
    _clear_layer("hover")


def clear_highlight():
    pass


def clear_candidates():
    pass


def clear_arrow():
    pass


def clear_frame():
    pass


def reset_overlay_states(clear_frame_too=False):
    _clear_all_layers()


def refresh_camera_scaled_overlays():
    # Current point radius is recomputed every time a point is shown. This hook
    # is kept for callers that still expect it.
    pass


# ---------------------------------------------------------------------------
# Legacy non-point indicator API kept as no-op for compatibility.
# ---------------------------------------------------------------------------
# Path preview/export are handled elsewhere; this file is now only responsible
# for interactive point overlays.

def show_preview_line(*args, **kwargs):
    pass


def show_preview_circle(*args, **kwargs):
    pass


def show_highlight_line(*args, **kwargs):
    pass


def show_highlight_circle(*args, **kwargs):
    pass


def show_circle_candidates(*args, **kwargs):
    pass


def show_preview_polygon(*args, **kwargs):
    pass


def show_uv_frame(*args, **kwargs):
    return None


def show_arrow(*args, **kwargs):
    pass


def show_direction_field(*args, **kwargs):
    pass
