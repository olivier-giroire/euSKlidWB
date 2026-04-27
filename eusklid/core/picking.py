
from ..qt_compat import QtCore
from . import logging as elog
import FreeCADGui as Gui
from .highlights import pick_reference_line
from .snaps import compute_contextual_snaps, compute_free_point
from .render import clear_render_layers, render_snap_point, render_highlight_line, render_highlight_circle
from .session import register_active_handler, unregister_active_handler

def world_to_uv(plane, world):
    return plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))


def _show_cursor_status(uv, snap=None):
    try:
        u = float(uv[0])
        v = float(uv[1])
        suffix = ""
        if isinstance(snap, dict):
            kind = snap.get("kind")
            if kind:
                suffix = "  [%s]" % kind
        Gui.getMainWindow().statusBar().showMessage("euSKlid U %.3f  V %.3f%s" % (u, v, suffix))
    except Exception:
        pass


def _clear_cursor_status():
    try:
        Gui.getMainWindow().statusBar().clearMessage()
    except Exception:
        pass



def _help_expected(message):
    try:
        elog.help(message)
    except Exception:
        pass


def _help_invalid_selection():
    try:
        elog.invalid_selection("You can't touch this !")
    except Exception:
        pass

def _force_free_point_requested(info):
    """Return True when the user requests a free point override.

    Ctrl is the free-point override modifier.
    """
    try:
        if bool(info.get("CtrlDown", False)):
            return True
    except Exception:
        pass

    try:
        mods = QtCore.QCoreApplication.keyboardModifiers()
        return bool(mods & QtCore.Qt.ControlModifier)
    except Exception:
        return False


def _forced_free_anchor(context, uv):
    p = compute_free_point(context, uv)
    return {
        "kind": "point",
        "point": p,
        "snap": {"kind": "free", "point": p, "source": None, "forced": True},
        "manual": True,
        "forced": True,
    }


def _point_anchor_from_snap(snap, manual=False):
    return {
        "kind": "point",
        "point": snap["point"],
        "snap": snap,
        "manual": bool(manual),
    }


def _primitive_candidates(context, uv, picker_kind):
    """Return allowed primitive anchors in explicit priority order."""
    out = []
    allowed = _allowed_anchor_kinds(context, picker_kind)

    if "line" in allowed:
        try:
            from ..controller import _pick_reference_line
            line = _pick_reference_line(context.sketch_obj, uv)
        except Exception:
            line = None
        if line is not None:
            anchor = {
                "kind": "line",
                "origin": line["origin"],
                "direction": line["direction"],
            }
            if _anchor_allowed(context, picker_kind, anchor):
                out.append(anchor)

    if "circle" in allowed:
        try:
            from ..controller import _pick_nearest_circle
            c = _pick_nearest_circle(context.sketch_obj, uv)
        except Exception:
            c = None
        if c is not None:
            anchor = {
                "kind": "circle",
                "center": c["center"],
                "radius": c["radius"],
            }
            if _anchor_allowed(context, picker_kind, anchor):
                out.append(anchor)

    return out


def _resolve_anchor_by_priority(context, uv, picker_kind, force_free=False):
    """Explicit picking priority.

    1. Ctrl-forced free point
    2. contextual tangent anchor
    3. snap point
    4. allowed primitive anchor
    5. free/manual point
    """
    if force_free:
        return _forced_free_anchor(context, uv)

    snap = compute_contextual_snaps(context, uv)

    if snap.get("kind") == "tangent" and "anchor" in snap:
        anchor = dict(snap["anchor"])
        anchor["snap"] = snap
        anchor["manual"] = False
        if _anchor_allowed(context, picker_kind, anchor):
            return anchor

    if snap.get("kind") != "free":
        return _point_anchor_from_snap(snap, manual=False)

    primitives = _primitive_candidates(context, uv, picker_kind)
    if primitives:
        return primitives[0]

    return _point_anchor_from_snap(snap, manual=True)

def _render_selected_from_context(context):
    try:
        from .. import indicator
        indicator.show_selected_anchors(context.plane, context.metadata.get('selected_anchors', []))
    except Exception:
        pass


def _allowed_anchor_kinds(context, picker_kind):
    """Return the set of anchor kinds this picker may expose in this command.

    The goal is UX filtering only: do not highlight/select entities that the
    current construction cannot actually consume.
    """
    # A line built from anchors uses point anchors and circle anchors
    # (for tangent solutions). A line itself is not a useful anchor here.
    if picker_kind == "line_anchor":
        return {"point", "circle"}

    # Circle anchor constructions can use points, lines and circles.
    if picker_kind == "circle_anchor":
        return {"point", "line", "circle"}

    return {"point", "line", "circle"}


def _anchor_allowed(context, picker_kind, anchor):
    try:
        return anchor.get("kind") in _allowed_anchor_kinds(context, picker_kind)
    except Exception:
        return False


def pick_reference_line_once(view, context, on_done):
    plane = context.plane

    class _PickRefOnce:
        def __init__(self):
            _help_expected("Expected: reference line")
            self._closed = False
            self.cb_mouse = view.addEventCallback("SoMouseButtonEvent", self.on_mouse)
            self.cb_move = view.addEventCallback("SoLocation2Event", self.on_move)
            register_active_handler(self)

        def _do_finish(self):
            if self._closed:
                return
            self._closed = True
            try:
                view.removeEventCallback("SoMouseButtonEvent", self.cb_mouse)
            except Exception:
                pass
            try:
                view.removeEventCallback("SoLocation2Event", self.cb_move)
            except Exception:
                pass
            unregister_active_handler(self)
            clear_render_layers()

        def finish(self):
            QtCore.QTimer.singleShot(0, self._do_finish)

        def on_mouse(self, info):
            try:
                if info.get("State") != "DOWN":
                    return
                button = info.get("Button")
                if button == "BUTTON3":
                    self.finish()
                    return
                if button != "BUTTON1":
                    return

                pos = info.get("Position")
                if not pos:
                    return

                world = view.getPoint(pos[0], pos[1])
                uv0 = world_to_uv(plane, world)
                snap = compute_contextual_snaps(context, uv0)
                uv = snap["point"]

                ref = pick_reference_line(context.sketch_obj, uv)
                if ref is None:
                    _help_invalid_selection()
                    return
                try:
                    context.metadata['last_anchor'] = dict(ref)
                except Exception:
                    pass

                QtCore.QTimer.singleShot(0, lambda r=ref: on_done(r))
                self.finish()
            except Exception:
                self.finish()

        def on_move(self, info):
            try:
                if self._closed:
                    return
                pos = info.get("Position")
                if not pos:
                    return

                world = view.getPoint(pos[0], pos[1])
                uv0 = world_to_uv(plane, world)
                snap = compute_contextual_snaps(context, uv0)
                uv = snap["point"]

                ref = pick_reference_line(context.sketch_obj, uv)
                _render_selected_from_context(context)
                if ref is None:
                    clear_render_layers()
                    _render_selected_from_context(context)
                    return

                render_highlight_line(plane, ref["origin"], ref["direction"])
                _render_selected_from_context(context)
            except Exception:
                pass

    return _PickRefOnce()

def pick_point_once(view, context, on_done):
    plane = context.plane

    class _PickPointOnce:
        def __init__(self):
            _help_expected("Expected: snap point → free point")
            self._closed = False
            self.cb_mouse = view.addEventCallback("SoMouseButtonEvent", self.on_mouse)
            self.cb_move = view.addEventCallback("SoLocation2Event", self.on_move)
            register_active_handler(self)

        def _do_finish(self):
            if self._closed:
                return
            self._closed = True
            try:
                view.removeEventCallback("SoMouseButtonEvent", self.cb_mouse)
            except Exception:
                pass
            try:
                view.removeEventCallback("SoLocation2Event", self.cb_move)
            except Exception:
                pass
            unregister_active_handler(self)
            clear_render_layers()

        def finish(self):
            QtCore.QTimer.singleShot(0, self._do_finish)

        def on_mouse(self, info):
            try:
                if info.get("State") != "DOWN":
                    return

                button = info.get("Button")
                if button == "BUTTON3":
                    self.finish()
                    return
                if button != "BUTTON1":
                    return

                pos = info.get("Position")
                if not pos:
                    return

                world = view.getPoint(pos[0], pos[1])
                uv0 = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))
                if _force_free_point_requested(info):
                    point = compute_free_point(context, uv0)
                    snap = {"kind": "free", "point": point, "source": None, "forced": True}
                else:
                    snap = compute_contextual_snaps(context, uv0)
                    point = snap["point"]
                _show_cursor_status(point, snap)
                try:
                    context.metadata['last_anchor'] = {'kind': 'point', 'point': point, 'manual': snap.get('kind') == 'free'}
                except Exception:
                    pass

                QtCore.QTimer.singleShot(0, lambda p=point: on_done(p))
                self.finish()

            except Exception:
                self.finish()

        def on_move(self, info):
            try:
                if self._closed:
                    return

                pos = info.get("Position")
                if not pos:
                    return

                world = view.getPoint(pos[0], pos[1])
                uv0 = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))
                if _force_free_point_requested(info):
                    point = compute_free_point(context, uv0)
                    snap = {"kind": "free", "point": point, "source": None, "forced": True}
                else:
                    snap = compute_contextual_snaps(context, uv0)
                    point = snap["point"]
                _show_cursor_status(point, snap)

                try:
                    from .. import indicator
                    indicator.clear_highlight()
                except Exception:
                    pass

                if snap["kind"] == "free":
                    try:
                        from .. import indicator
                        indicator.clear_snap()
                    except Exception:
                        pass
                else:
                    render_snap_point(plane, point, snap["kind"])
                _render_selected_from_context(context)

            except Exception:
                pass

    return _PickPointOnce()

def pick_line_anchor_once(view, context, on_done):
    plane = context.plane

    class _PickAnchorOnce:
        def __init__(self):
            _help_expected("Expected: snap point → tangent circle → circle → free point")
            self._closed = False
            self.cb_mouse = view.addEventCallback("SoMouseButtonEvent", self.on_mouse)
            self.cb_move = view.addEventCallback("SoLocation2Event", self.on_move)
            register_active_handler(self)

        def _do_finish(self):
            if self._closed:
                return
            self._closed = True
            try:
                view.removeEventCallback("SoMouseButtonEvent", self.cb_mouse)
            except Exception:
                pass
            try:
                view.removeEventCallback("SoLocation2Event", self.cb_move)
            except Exception:
                pass
            unregister_active_handler(self)
            clear_render_layers()

        def finish(self):
            QtCore.QTimer.singleShot(0, self._do_finish)

        def _pick_anchor(self, uv, force_free=False):
            return _resolve_anchor_by_priority(
                context,
                uv,
                "line_anchor",
                force_free=force_free,
            )

        def on_mouse(self, info):
            try:
                if info.get("State") != "DOWN":
                    return
                button = info.get("Button")
                if button == "BUTTON3":
                    self.finish()
                    return
                if button != "BUTTON1":
                    return

                pos = info.get("Position")
                if not pos:
                    return

                world = view.getPoint(pos[0], pos[1])
                uv0 = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))

                anchor = self._pick_anchor(uv0, force_free=_force_free_point_requested(info))
                try:
                    context.metadata["last_anchor"] = dict(anchor)
                except Exception:
                    pass

                self.finish()
                QtCore.QTimer.singleShot(0, lambda a=anchor: on_done(a))
            except Exception:
                self.finish()

        def on_move(self, info):
            try:
                if self._closed:
                    return

                pos = info.get("Position")
                if not pos:
                    return

                world = view.getPoint(pos[0], pos[1])
                uv0 = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))

                anchor = self._pick_anchor(uv0, force_free=_force_free_point_requested(info))
                try:
                    _show_cursor_status(anchor.get("point", uv0), anchor.get("snap"))
                except Exception:
                    _show_cursor_status(uv0)
                clear_render_layers()

                if anchor["kind"] == "line":
                    if anchor.get("snap", {}).get("kind") == "tangent":
                        render_highlight_line(plane, anchor["origin"], anchor["direction"])
                        render_snap_point(plane, anchor["snap"]["point"], "tangent")
                    else:
                        render_highlight_line(plane, anchor["origin"], anchor["direction"])
                elif anchor["kind"] == "circle":
                    if anchor.get("snap", {}).get("kind") == "tangent":
                        render_highlight_circle(plane, anchor["center"], anchor["radius"])
                        render_snap_point(plane, anchor["snap"]["point"], "tangent")
                    else:
                        render_highlight_circle(plane, anchor["center"], anchor["radius"])
                else:
                    snap = anchor["snap"]
                    if anchor.get("manual", False):
                        try:
                            from .. import indicator
                            indicator.show_manual_point(plane, anchor["point"])
                        except Exception:
                            pass
                    elif snap["kind"] != "free":
                        render_snap_point(plane, anchor["point"], snap["kind"])

                try:
                    from .. import indicator
                    indicator.show_selected_anchors(
                        context.plane,
                        context.metadata.get("selected_anchors", []),
                    )
                except Exception:
                    pass
            except Exception:
                pass

    return _PickAnchorOnce()

def pick_circle_anchor_once(view, context, on_done):
    plane = context.plane

    class _PickCircleAnchorOnce:
        def __init__(self):
            _help_expected("Expected: snap point → tangent anchor → line → circle → free point")
            self._closed = False
            self.cb_mouse = view.addEventCallback("SoMouseButtonEvent", self.on_mouse)
            self.cb_move = view.addEventCallback("SoLocation2Event", self.on_move)
            register_active_handler(self)

        def _do_finish(self):
            if self._closed:
                return
            self._closed = True
            try:
                view.removeEventCallback("SoMouseButtonEvent", self.cb_mouse)
            except Exception:
                pass
            try:
                view.removeEventCallback("SoLocation2Event", self.cb_move)
            except Exception:
                pass
            unregister_active_handler(self)
            clear_render_layers()

        def finish(self):
            QtCore.QTimer.singleShot(0, self._do_finish)

        def _pick_anchor(self, uv, force_free=False):
            return _resolve_anchor_by_priority(
                context,
                uv,
                "circle_anchor",
                force_free=force_free,
            )

        def on_mouse(self, info):
            try:
                if info.get("State") != "DOWN":
                    return
                button = info.get("Button")
                if button == "BUTTON3":
                    self.finish()
                    return
                if button != "BUTTON1":
                    return

                pos = info.get("Position")
                if not pos:
                    return

                world = view.getPoint(pos[0], pos[1])
                uv0 = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))

                anchor = self._pick_anchor(uv0, force_free=_force_free_point_requested(info))
                try:
                    context.metadata["last_anchor"] = dict(anchor)
                except Exception:
                    pass

                self.finish()
                QtCore.QTimer.singleShot(0, lambda a=anchor: on_done(a))
            except Exception:
                self.finish()

        def on_move(self, info):
            try:
                if self._closed:
                    return

                pos = info.get("Position")
                if not pos:
                    return

                world = view.getPoint(pos[0], pos[1])
                uv0 = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))

                anchor = self._pick_anchor(uv0, force_free=_force_free_point_requested(info))
                try:
                    _show_cursor_status(anchor.get("point", uv0), anchor.get("snap"))
                except Exception:
                    _show_cursor_status(uv0)
                clear_render_layers()

                if anchor["kind"] == "line":
                    if anchor.get("snap", {}).get("kind") == "tangent":
                        render_highlight_line(plane, anchor["origin"], anchor["direction"])
                        render_snap_point(plane, anchor["snap"]["point"], "tangent")
                    else:
                        render_highlight_line(plane, anchor["origin"], anchor["direction"])
                elif anchor["kind"] == "circle":
                    if anchor.get("snap", {}).get("kind") == "tangent":
                        render_highlight_circle(plane, anchor["center"], anchor["radius"])
                        render_snap_point(plane, anchor["snap"]["point"], "tangent")
                    else:
                        render_highlight_circle(plane, anchor["center"], anchor["radius"])
                else:
                    snap = anchor["snap"]
                    if anchor.get("manual", False):
                        try:
                            from .. import indicator
                            indicator.show_manual_point(plane, anchor["point"])
                        except Exception:
                            pass
                    elif snap["kind"] != "free":
                        render_snap_point(plane, anchor["point"], snap["kind"])

                try:
                    from .. import indicator
                    indicator.show_selected_anchors(
                        context.plane,
                        context.metadata.get("selected_anchors", []),
                    )
                except Exception:
                    pass
            except Exception:
                pass

    return _PickCircleAnchorOnce()

