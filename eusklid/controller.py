
import FreeCAD as App
import FreeCADGui as Gui
from .feature import ensure_proxy, get_data, set_data, create_sketch
from .plane import SketchPlane
from .geom import LineEntity2D, CircleEntity2D
from .math2d import point_to_line_distance, dist2
from . import indicator
from .qt_compat import QtWidgets
from .core.config import get_config
from .snap import SnapEngine2D
from .core.snaps import snap_threshold_uv
from .tools.line_tools import (
    start_series_parallel_ref as tools_start_series_parallel_ref,
    start_parallel_ref_point as tools_start_parallel_ref_point,
    start_point_angle as tools_start_point_angle,
    start_line_two_anchors,
    start_line_grid as tools_start_line_grid,
)
from .tools.circle_tools import (
    start_circle_center_radius as tools_start_circle_center_radius,
    start_circle_center_pass as tools_start_circle_center_pass,
    start_circle_three_points as tools_start_circle_three_points,
    start_circle_two_anchors_radius as tools_start_circle_two_anchors_radius,
)
from .core.groups import ensure_euclid_groups
from .tools.path_tools import (
    new_path_session,
    close_path_session,
    export_path_to_sketcher,
    stop_path_session,
    undo_path_session,
    has_active_path_session,
    mark_selected_path_tangent_overload,
    mark_selected_path_length_overload,
    mark_selected_path_colinearity_overload,
    mark_selected_path_angle_overload,
    mark_selected_path_distance_overload,
    start_path_overload_edit,
    finish_path_overload_edit,
)
from .core.session import undo_active_command, has_active_command, reset_interaction_state
from .core.undo import undo_last_sketch_edit
from .tools.selection_tools import start_selection_delete_handler, stop_selection_delete_handler, set_active_sketch

_SNAP = SnapEngine2D(tol=8.0)
_PATH_POINTS = []
_PATH_ACTIVE = False


def _snap_info(sketch_obj, uv):
    data = get_data(sketch_obj)
    return _SNAP.snap(uv, data)


def _snap_uv(sketch_obj, uv):
    return _snap_info(sketch_obj, uv)["point"]


def stop_active_session():
    try:
        reset_interaction_state()
    except Exception:
        pass
    try:
        stop_path_session()
    except Exception:
        pass
    try:
        indicator.reset_overlay_states(clear_frame_too=True)
    except Exception:
        try:
            indicator.clear_all()
        except Exception:
            pass


from . import legacy_api  # noqa: E402
legacy_api.set_legacy_stopper(stop_active_session)


def clear_all_indicators():
    indicator.clear_all()


def show_local_frame(sketch_obj=None):
    """Legacy entry point: XY-only euSKlid has no U/V frame overlay."""
    sketch_obj = sketch_obj or get_or_create_euclid_sketch()
    try:
        set_active_sketch(sketch_obj)
    except Exception:
        pass
    try:
        start_selection_delete_handler()
    except Exception:
        pass

def get_or_create_euclid_sketch():
    doc = App.ActiveDocument
    if doc is None:
        raise RuntimeError("No active document.")
    ensure_euclid_groups(doc)
    for obj in doc.Objects:
        if getattr(obj, "Proxy", None) and obj.Proxy.__class__.__name__ == "euSKlidFeature":
            return ensure_proxy(obj)
    return create_sketch(doc, plane=SketchPlane.XY())



def list_eusklid_sketches():
    doc = App.ActiveDocument
    if doc is None:
        return []

    out = []
    for obj in getattr(doc, "Objects", []):
        try:
            proxy = getattr(obj, "Proxy", None)
            if proxy is not None and proxy.__class__.__name__ == "euSKlidFeature":
                out.append(obj)
                continue
            if "SketchJson" in getattr(obj, "PropertiesList", []):
                out.append(ensure_proxy(obj))
        except Exception:
            pass
    return out


def open_eusklid_sketch():
    doc = App.ActiveDocument
    if doc is None:
        QtWidgets.QMessageBox.warning(None, "euSKlid", "No active document.")
        return None

    sketches = list_eusklid_sketches()
    if not sketches:
        QtWidgets.QMessageBox.information(None, "euSKlid", "No euSKlid sketch found in the active document.")
        return None

    if len(sketches) == 1:
        obj = ensure_proxy(sketches[0])
    else:
        labels = []
        for obj in sketches:
            try:
                labels.append("%s (%s)" % (getattr(obj, "Label", obj.Name), obj.Name))
            except Exception:
                labels.append(str(obj))

        label, ok = QtWidgets.QInputDialog.getItem(
            None,
            "euSKlid",
            "Open Sketch",
            labels,
            0,
            False,
        )
        if not ok:
            return None
        idx = labels.index(label)
        obj = ensure_proxy(sketches[idx])

    try:
        set_active_sketch(obj)
    except Exception:
        try:
            Gui.Selection.clearSelection()
        except Exception:
            pass

    try:
        from .tools.path_tools import restore_closed_paths_from_sketch
        restore_closed_paths_from_sketch(obj, redraw_missing=False)
    except Exception:
        pass

    try:
        if Gui.ActiveDocument is not None:
            Gui.ActiveDocument.ActiveView.redraw()
    except Exception:
        pass

    try:
        start_selection_delete_handler()
    except Exception:
        pass

    return obj

def create_sketch_on_plane(plane, name):
    doc = App.ActiveDocument
    if doc is None:
        doc = App.newDocument()
    ensure_euclid_groups(doc)
    obj = create_sketch(doc, name=name, plane=plane)
    try:
        orient_view_to_plane(plane)
    except Exception:
        pass
    try:
        set_active_sketch(obj)
    except Exception:
        pass
    try:
        start_selection_delete_handler()
    except Exception:
        pass
    return obj


def _line_descriptor(ent):
    return {"kind": "line", "origin": tuple(ent.origin), "direction": tuple(ent.direction)}


def _circle_descriptor(ent):
    return {"kind": "circle", "center": tuple(ent.center), "radius": float(ent.radius)}


def _pick_nearest_line(sketch_obj, uv, tol=10.0):
    best = None
    best_dist = None
    data = get_data(sketch_obj)
    for ent in data.entities:
        if not isinstance(ent, LineEntity2D):
            continue
        dist = point_to_line_distance(uv, ent.origin, ent.direction)
        if best_dist is None or dist < best_dist:
            best = ent
            best_dist = dist
    if best is not None and best_dist is not None and best_dist <= tol:
        return _line_descriptor(best)
    return None


def _snap_threshold(sketch_obj=None, uv=None):
    try:
        if sketch_obj is not None and uv is not None:
            return snap_threshold_uv(sketch_obj, uv)
    except Exception:
        pass
    try:
        return float(get_config().get("feeling", {}).get("snap_threshold", 20.0))
    except Exception:
        return 20.0

def _pick_nearest_circle(sketch_obj, uv, tol=None):
    if tol is None:
        tol = _snap_threshold(sketch_obj, uv)
    best = None
    best_dist = None
    data = get_data(sketch_obj)
    for ent in data.entities:
        if not isinstance(ent, CircleEntity2D):
            continue
        dist = abs(dist2(uv, ent.center) - ent.radius)
        if best_dist is None or dist < best_dist:
            best = ent
            best_dist = dist
    if best is not None and best_dist is not None and best_dist <= tol:
        return _circle_descriptor(best)
    return None


def orient_view_to_plane(plane):
    try:
        view = Gui.ActiveDocument.ActiveView
        if plane.name == "XY":
            view.viewTop()
        elif plane.name == "XZ":
            view.viewFront()
        elif plane.name == "YZ":
            view.viewRight()
        else:
            n = plane.normal
            view.viewPosition()
            view.setCameraOrientation(App.Rotation(App.Vector(0, 0, 1), n))
            view.fitAll()
    except Exception:
        try:
            Gui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass


def _axis_reference_candidates(sketch_obj):
    return [
        {"kind": "axis", "axis": "X", "origin": (0.0, 0.0), "direction": (1.0, 0.0)},
        {"kind": "axis", "axis": "Y", "origin": (0.0, 0.0), "direction": (0.0, 1.0)},
    ]


def _pick_reference_line(sketch_obj, uv, tol=None):
    if tol is None:
        tol = _snap_threshold(sketch_obj, uv)
    line = _pick_nearest_line(sketch_obj, uv, tol=tol)
    best = line
    best_dist = point_to_line_distance(uv, line["origin"], line["direction"]) if line is not None else None
    for axis in _axis_reference_candidates(sketch_obj):
        d = point_to_line_distance(uv, axis["origin"], axis["direction"])
        if best_dist is None or d < best_dist:
            if d <= tol:
                best = axis
                best_dist = d
    return best


def create_parallel_axis(axis, values, construction=True, sketch_obj=None):
    sketch_obj = sketch_obj or get_or_create_euclid_sketch()
    data = get_data(sketch_obj)
    axis = "X" if axis in ("U", "X") else "Y"
    if axis == "X":
        direction = (1.0, 0.0)
        for d in values:
            data.entities.append(LineEntity2D(origin=(0.0, d), direction=direction, construction=construction, meta={"mode": "parallel-x"}))
    else:
        direction = (0.0, 1.0)
        for d in values:
            data.entities.append(LineEntity2D(origin=(d, 0.0), direction=direction, construction=construction, meta={"mode": "parallel-y"}))
    set_data(sketch_obj, data)
    App.ActiveDocument.recompute()
    try:
        Gui.Selection.clearSelection()
    except Exception:
        pass
    show_local_frame(sketch_obj)
    return sketch_obj

def origin_mode_message(mode_name):
    QtWidgets.QMessageBox.information(None, "euSKlid", f"Origin mode '{mode_name}' is not implemented yet.")


def placeholder_message(label):
    QtWidgets.QMessageBox.information(None, "euSKlid", f"'{label}' is not implemented yet.")


def _find_existing_euclid_sketch():
    doc = App.ActiveDocument
    if doc is None:
        return None
    for obj in doc.Objects:
        if getattr(obj, "Proxy", None) and obj.Proxy.__class__.__name__ == "euSKlidFeature":
            return ensure_proxy(obj)
    return None


def undo_contextual():
    if has_active_path_session():
        if undo_path_session():
            return
    if has_active_command():
        if undo_active_command():
            return
    sketch_obj = _find_existing_euclid_sketch()
    if sketch_obj is not None:
        undo_last_sketch_edit(sketch_obj)

def path_start():
    stop_active_session()
    new_path_session()


def path_close():
    close_path_session()


def path_export():
    export_path_to_sketcher()

def end_sketch():

    stop_active_session()
    try:
        stop_selection_delete_handler()
    except Exception:
        pass
    try:
        if hasattr(indicator, "reset_overlay_states"):
            indicator.reset_overlay_states(clear_frame_too=True)
        else:
            indicator.clear_all()
    except Exception:
        pass
    try:
        if Gui.ActiveDocument is not None:
            Gui.ActiveDocument.ActiveView.redraw()
    except Exception:
        pass
    QtWidgets.QMessageBox.information(None, "euSKlid", "End Sketch: active euSKlid tool stopped.")


def start_line_2pts_session(construction=True):
    stop_active_session()
    sketch_obj = get_or_create_euclid_sketch()
    return start_line_two_anchors(sketch_obj=sketch_obj, construction=construction)


def start_circle_center_pass_session(construction=True):
    stop_active_session()
    sketch_obj = get_or_create_euclid_sketch()
    return tools_start_circle_center_pass(sketch_obj=sketch_obj, construction=construction)


def start_circle_center_radius_session(radius, construction=True):
    stop_active_session()
    sketch_obj = get_or_create_euclid_sketch()
    return tools_start_circle_center_radius(sketch_obj=sketch_obj, radius=radius, construction=construction)


def start_circle_3pts_session(construction=True):
    stop_active_session()
    sketch_obj = get_or_create_euclid_sketch()
    return tools_start_circle_three_points(sketch_obj=sketch_obj, construction=construction)


def start_circle_2pts_radius_session(radius, choose_solution, construction=True):
    stop_active_session()
    sketch_obj = get_or_create_euclid_sketch()
    return tools_start_circle_two_anchors_radius(sketch_obj=sketch_obj, radius=radius, construction=construction)


def start_line_parallel_ref_series_session(ask_distance_series, construction=True):
    stop_active_session()
    sketch_obj = get_or_create_euclid_sketch()
    return tools_start_series_parallel_ref(sketch_obj=sketch_obj, ask_distance_series=ask_distance_series, construction=construction)


def start_line_parallel_ref_point_session(construction=True):
    stop_active_session()
    sketch_obj = get_or_create_euclid_sketch()
    return tools_start_parallel_ref_point(sketch_obj=sketch_obj, construction=construction, perpendicular=False)


def start_line_perpendicular_ref_point_session(construction=True):
    stop_active_session()
    sketch_obj = get_or_create_euclid_sketch()
    return tools_start_parallel_ref_point(sketch_obj=sketch_obj, construction=construction, perpendicular=True)


def start_point_angle_session(ask_angle_series, construction=True):
    stop_active_session()
    sketch_obj = get_or_create_euclid_sketch()
    return tools_start_point_angle(sketch_obj=sketch_obj, ask_angle_series=ask_angle_series, construction=construction)


def start_line_grid_session(grid_params=None, ask_grid_parameters=None, construction=True):
    stop_active_session()
    sketch_obj = get_or_create_euclid_sketch()
    return tools_start_line_grid(sketch_obj=sketch_obj, grid_params=grid_params, ask_grid_parameters=ask_grid_parameters, construction=construction)


# Constraint overload command wrappers.
def path_preserve_tangent_overload():
    return mark_selected_path_tangent_overload()

def path_preserve_tangent():
    return mark_selected_path_tangent_overload()

def path_preserve_length_overload():
    return mark_selected_path_length_overload()

def path_preserve_length():
    return mark_selected_path_length_overload()

def path_preserve_colinearity_overload():
    return mark_selected_path_colinearity_overload()

def path_preserve_colinearity():
    return mark_selected_path_colinearity_overload()

def path_preserve_angle_overload():
    return mark_selected_path_angle_overload()

def path_preserve_angle():
    return mark_selected_path_angle_overload()

def path_preserve_distance_overload():
    return mark_selected_path_distance_overload()

def path_preserve_distance():
    return mark_selected_path_distance_overload()

def path_start_overload_edit():
    return start_path_overload_edit()

def path_finish_overload_edit():
    return finish_path_overload_edit()

def path_edit_overloads():
    return start_path_overload_edit()

