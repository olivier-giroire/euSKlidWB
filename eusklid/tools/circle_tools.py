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

from ..core.context import CommandContext, StepSpec
from ..core import logging as elog
from ..core.session import (
    begin_command,
    finish_command,
    cancel_command,
    register_active_handler,
    unregister_active_handler,
    push_command_restore,
)
from ..core.snaps import compute_contextual_snaps, compute_free_point
from ..core.render import (
    render_snap_point,
    render_preview_circle,
    render_preview_polygon,
    clear_render_layers,
)
from ..core.picking import pick_circle_anchor_once
from ..runtime import (
    get_active_plane,
    get_or_create_euclid_sketch,
    commit_circle,
)
from ..feature import get_data, set_data
from ..geom import LineEntity2D, CircleEntity2D
from ..solvers.circle_solvers import (
    build_circle_center_radius,
    build_circle_center_anchor,
    build_circles_from_three_anchors,
    build_circles_from_two_anchors_radius,
)
from ..math2d import dist2, normalize
from ..qt_compat import QtCore
import FreeCADGui as Gui
import FreeCAD as App


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

def _pick_point_and_callback(context, on_done, preview_fn=None):
    plane = context.plane
    view = Gui.ActiveDocument.ActiveView

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
                    QtCore.QTimer.singleShot(0, lambda: cancel_command(context))
                    return
                if button != "BUTTON1":
                    return
                pos = info.get("Position")
                if not pos:
                    return
                world = view.getPoint(pos[0], pos[1])
                uv0 = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))
                if _force_free_point_requested(info):
                    uv = compute_free_point(context, uv0)
                    snap = {"kind": "free", "point": uv, "source": None, "forced": True}
                else:
                    snap = compute_contextual_snaps(context, uv0)
                    uv = snap["point"]
                _show_cursor_status(uv, snap)
                try:
                    context.metadata['last_anchor'] = {'kind': 'point', 'point': uv, 'manual': snap.get('kind') == 'free'}
                except Exception:
                    pass
                self.finish()
                QtCore.QTimer.singleShot(0, lambda p=uv: on_done(p))
            except Exception:
                self.finish()
                QtCore.QTimer.singleShot(0, lambda: cancel_command(context))

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
                    uv = compute_free_point(context, uv0)
                    snap = {"kind": "free", "point": uv, "source": None, "forced": True}
                else:
                    snap = compute_contextual_snaps(context, uv0)
                    uv = snap["point"]
                _show_cursor_status(uv, snap)

                try:
                    from .. import indicator
                    indicator.clear_highlight()
                except Exception:
                    pass

                if snap["kind"] == "free":
                    try:
                        from .. import indicator
                        indicator.show_manual_point(plane, uv)
                    except Exception:
                        pass
                else:
                    render_snap_point(plane, uv, snap["kind"])

                if preview_fn is not None:
                    preview_fn(uv)
                try:
                    from .. import indicator
                    indicator.show_selected_anchors(context.plane, context.metadata.get('selected_anchors', []))
                except Exception:
                    pass
            except Exception:
                pass

    return _PickPointOnce()


def _pick_best_circle_candidate(candidates, uv):
    best = None
    best_score = None
    for cand in candidates or []:
        score = abs(dist2(uv, cand["center"]) - cand["radius"])
        if best_score is None or score < best_score:
            best = cand
            best_score = score
    return best


def _pick_circle_solution_once(context, candidates, construction=True, mode="generic-circle"):
    sketch_obj = context.sketch_obj
    plane = context.plane
    view = Gui.ActiveDocument.ActiveView

    def _pick_best(uv):
        best = None
        best_score = None
        for cand in candidates or []:
            score = abs(dist2(uv, cand["center"]) - cand["radius"])
            if best_score is None or score < best_score:
                best = cand
                best_score = score
        return best

    class _PickCircleSolutionOnce:
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
                    QtCore.QTimer.singleShot(0, lambda: cancel_command(context))
                    return
                if button != "BUTTON1":
                    return

                pos = info.get("Position")
                if not pos:
                    return

                world = view.getPoint(pos[0], pos[1])
                uv0 = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))

                best = _pick_best(uv0)
                if best is None:
                    return

                commit_circle(
                    sketch_obj,
                    best["center"],
                    best["radius"],
                    construction=construction,
                    mode=mode,
                )
                self.finish()
                QtCore.QTimer.singleShot(0, lambda: finish_command(context))
            except Exception:
                self.finish()
                QtCore.QTimer.singleShot(0, lambda: cancel_command(context))

        def on_move(self, info):
            try:
                if self._closed:
                    return

                pos = info.get("Position")
                if not pos:
                    return

                world = view.getPoint(pos[0], pos[1])
                uv0 = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))

                best = _pick_best(uv0)
                if best is None:
                    clear_render_layers()
                    return

                render_preview_circle(plane, best["center"], best["radius"])
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

    return _PickCircleSolutionOnce()

def start_circle_center_radius(sketch_obj=None, radius=None, construction=True):
    sketch_obj = sketch_obj or get_or_create_euclid_sketch()
    if radius is None:
        return sketch_obj

    ctx = begin_command(CommandContext(
        name="circle_center_radius",
        primitive="circle",
        steps=[StepSpec("pick_center", "point")],
        sketch_obj=sketch_obj,
        plane=get_active_plane(sketch_obj),
    ))
    ctx.metadata["_reenter_fn"] = lambda: start_circle_center_radius(
        sketch_obj=sketch_obj, radius=radius, construction=construction
    )

    def _start_center():
        def _preview(center):
            cand = build_circle_center_radius(center, radius)
            if cand is None:
                clear_render_layers()
                return
            render_preview_circle(ctx.plane, cand["center"], cand["radius"])

        def _done(center):
            cand = build_circle_center_radius(center, radius)
            if cand is None:
                cancel_command(ctx)
                return
            commit_circle(sketch_obj, cand["center"], cand["radius"], construction=construction, mode=cand["mode"])
            finish_command(ctx)

        push_command_restore(ctx, _start_center)
        return _pick_point_and_callback(ctx, _done, preview_fn=_preview)

    return _start_center()

def start_circle_center_pass(sketch_obj=None, construction=True):
    sketch_obj = sketch_obj or get_or_create_euclid_sketch()

    ctx = begin_command(CommandContext(
        name="circle_center_anchor",
        primitive="circle",
        steps=[
            StepSpec("pick_center", "point"),
            StepSpec("pick_anchor", "circle_anchor"),
        ],
        sketch_obj=sketch_obj,
        plane=get_active_plane(sketch_obj),
    ))
    ctx.metadata["selected_anchors"] = []
    ctx.metadata["_reenter_fn"] = lambda: start_circle_center_pass(
        sketch_obj=sketch_obj, construction=construction
    )

    def _start_center():
        ctx.metadata["selected_anchors"] = []
        return _pick_point_and_callback(ctx, _after_center)

    def _start_anchor(center):
        a = ctx.metadata.get("last_anchor") or {"kind": "point", "point": center, "manual": False}
        ctx.metadata["selected_anchors"] = [a]

        def _done(anchor):
            cands = [c for c in build_circle_center_anchor(center, anchor) if c is not None]
            if not cands:
                cancel_command(ctx)
                return
            if len(cands) == 1:
                c = cands[0]
                commit_circle(sketch_obj, c["center"], c["radius"], construction=construction, mode=c["mode"])
                finish_command(ctx)
                return
            push_command_restore(ctx, lambda: _start_anchor(center))
            return _pick_circle_solution_once(ctx, cands, construction=construction, mode="center-anchor")

        push_command_restore(ctx, _start_center)
        return pick_circle_anchor_once(Gui.ActiveDocument.ActiveView, ctx, _done)

    def _after_center(center):
        return _start_anchor(center)

    return _start_center()

def start_circle_three_anchors(sketch_obj=None, construction=True):
    sketch_obj = sketch_obj or get_or_create_euclid_sketch()

    ctx = begin_command(CommandContext(
        name="circle_three_anchors",
        primitive="circle",
        steps=[
            StepSpec("pick_a1", "circle_anchor"),
            StepSpec("pick_a2", "circle_anchor"),
            StepSpec("pick_a3", "circle_anchor"),
        ],
        sketch_obj=sketch_obj,
        plane=get_active_plane(sketch_obj),
    ))
    ctx.metadata['selected_anchors'] = []
    ctx.metadata["_reenter_fn"] = lambda: start_circle_three_anchors(
        sketch_obj=sketch_obj, construction=construction
    )

    def _start_a1():
        ctx.metadata['selected_anchors'] = []
        return pick_circle_anchor_once(Gui.ActiveDocument.ActiveView, ctx, _after_a1)

    def _start_a2(a1):
        ctx.metadata['selected_anchors'] = [a1]
        return pick_circle_anchor_once(Gui.ActiveDocument.ActiveView, ctx, _after_a2(a1))

    def _start_a3(a1, a2):
        ctx.metadata['selected_anchors'] = [a1, a2]
        return pick_circle_anchor_once(Gui.ActiveDocument.ActiveView, ctx, _after_a3(a1, a2))

    def _after_a1(a1):
        push_command_restore(ctx, _start_a1)
        return _start_a2(a1)

    def _after_a2(a1):
        def __done(a2):
            push_command_restore(ctx, lambda: _start_a2(a1))
            return _start_a3(a1, a2)
        return __done

    def _after_a3(a1, a2):
        def __done(a3):
            cands = build_circles_from_three_anchors(a1, a2, a3)
            if not cands:
                App.Console.PrintError("euSKlid: impossible 3 anchors construction\n")
                cancel_command(ctx)
                return
            if len(cands) == 1:
                c = cands[0]
                commit_circle(sketch_obj, c["center"], c["radius"], construction=construction, mode=c["mode"])
                finish_command(ctx)
                return
            push_command_restore(ctx, lambda: _start_a3(a1, a2))
            return _pick_circle_solution_once(ctx, cands, construction=construction, mode="3anchors")
        return __done

    return _start_a1()

def start_circle_two_points_radius(sketch_obj=None, radius=None, construction=True):
    # compat wrapper: 2Pt + Radius is now implemented as 2 Anchors + Radius
    return start_circle_two_anchors_radius(
        sketch_obj=sketch_obj,
        radius=radius,
        construction=construction,
    )

def start_circle_two_anchors_radius(sketch_obj=None, radius=None, construction=True):
    sketch_obj = sketch_obj or get_or_create_euclid_sketch()
    if radius is None:
        return sketch_obj

    ctx = begin_command(CommandContext(
        name="circle_two_anchors_radius",
        primitive="circle",
        steps=[
            StepSpec("pick_a1", "circle_anchor"),
            StepSpec("pick_a2", "circle_anchor"),
            StepSpec("pick_solution", "solution_circle"),
        ],
        sketch_obj=sketch_obj,
        plane=get_active_plane(sketch_obj),
    ))
    ctx.metadata["selected_anchors"] = []
    ctx.metadata["_reenter_fn"] = lambda: start_circle_two_anchors_radius(
        sketch_obj=sketch_obj, radius=radius, construction=construction
    )

    def _start_a1():
        ctx.metadata["selected_anchors"] = []
        return pick_circle_anchor_once(Gui.ActiveDocument.ActiveView, ctx, _after_a1)

    def _start_a2(a1):
        ctx.metadata["selected_anchors"] = [a1]
        return pick_circle_anchor_once(Gui.ActiveDocument.ActiveView, ctx, _after_a2(a1))

    def _after_a1(a1):
        push_command_restore(ctx, _start_a1)
        return _start_a2(a1)

    def _after_a2(a1):
        def __done(a2):
            ctx.metadata["selected_anchors"] = [a1, a2]
            cands = build_circles_from_two_anchors_radius(a1, a2, radius)
            if not cands:
                App.Console.PrintError("euSKlid: Impossible construction for 2 anchors + radius\n")
                cancel_command(ctx)
                return
            if len(cands) == 1:
                c = cands[0]
                commit_circle(sketch_obj, c["center"], c["radius"], construction=construction, mode=c["mode"])
                finish_command(ctx)
                return
            push_command_restore(ctx, lambda: _start_a2(a1))
            return _pick_circle_solution_once(ctx, cands, construction=construction, mode="2anchors-radius")
        return __done

    return _start_a1()

def start_circle_three_points(sketch_obj=None, construction=True):
    return start_circle_three_anchors(sketch_obj=sketch_obj, construction=construction)



def _pick_circle_only_once(context, on_done):
    plane = context.plane
    view = Gui.ActiveDocument.ActiveView

    class _PickCircleOnlyOnce:
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

        def _pick_circle(self, uv):
            try:
                from ..controller import _pick_nearest_circle
                return _pick_nearest_circle(context.sketch_obj, uv)
            except Exception:
                return None

        def on_mouse(self, info):
            try:
                if info.get("State") != "DOWN":
                    return
                button = info.get("Button")
                if button == "BUTTON3":
                    self.finish()
                    QtCore.QTimer.singleShot(0, lambda: cancel_command(context))
                    return
                if button != "BUTTON1":
                    return
                pos = info.get("Position")
                if not pos:
                    return
                world = view.getPoint(pos[0], pos[1])
                uv0 = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))
                circle = self._pick_circle(uv0)
                if circle is None:
                    return
                self.finish()
                QtCore.QTimer.singleShot(0, lambda c=dict(circle): on_done(c))
            except Exception:
                self.finish()
                QtCore.QTimer.singleShot(0, lambda: cancel_command(context))

        def on_move(self, info):
            try:
                if self._closed:
                    return
                pos = info.get("Position")
                if not pos:
                    return
                world = view.getPoint(pos[0], pos[1])
                uv0 = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))
                circle = self._pick_circle(uv0)
                clear_render_layers()
                if circle is not None:
                    try:
                        from ..core.render import render_highlight_circle
                        render_highlight_circle(plane, circle["center"], circle["radius"])
                    except Exception:
                        pass
                try:
                    from .. import indicator
                    indicator.show_selected_anchors(context.plane, context.metadata.get("selected_anchors", []))
                except Exception:
                    pass
            except Exception:
                pass
    return _PickCircleOnlyOnce()


def _pick_point_or_reference_once(context, mode, on_done, preview_fn=None):
    plane = context.plane
    view = Gui.ActiveDocument.ActiveView

    class _PickRefOnce:
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

        def _pick(self, uv):
            if mode in ("vertice", "edge_middle"):
                snap = compute_contextual_snaps(context, uv)
                return {"kind": "point", "point": snap["point"], "snap": snap, "manual": snap.get("kind") == "free"}
            try:
                from ..controller import _pick_reference_line
                ref = _pick_reference_line(context.sketch_obj, uv)
            except Exception:
                ref = None
            if ref is not None:
                return {"kind": "line", "origin": ref["origin"], "direction": ref["direction"]}
            # fallback to point direction if no line
            snap = compute_contextual_snaps(context, uv)
            return {"kind": "point", "point": snap["point"], "snap": snap, "manual": snap.get("kind") == "free"}

        def on_mouse(self, info):
            try:
                if info.get("State") != "DOWN":
                    return
                button = info.get("Button")
                if button == "BUTTON3":
                    self.finish()
                    QtCore.QTimer.singleShot(0, lambda: cancel_command(context))
                    return
                if button != "BUTTON1":
                    return
                pos = info.get("Position")
                if not pos:
                    return
                world = view.getPoint(pos[0], pos[1])
                uv0 = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))
                ref = self._pick(uv0)
                self.finish()
                QtCore.QTimer.singleShot(0, lambda r=ref: on_done(r))
            except Exception:
                self.finish()
                QtCore.QTimer.singleShot(0, lambda: cancel_command(context))

        def on_move(self, info):
            try:
                if self._closed:
                    return
                pos = info.get("Position")
                if not pos:
                    return
                world = view.getPoint(pos[0], pos[1])
                uv0 = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))
                ref = self._pick(uv0)
                clear_render_layers()
                if ref["kind"] == "line":
                    try:
                        from ..core.render import render_highlight_line
                        render_highlight_line(plane, ref["origin"], ref["direction"])
                    except Exception:
                        pass
                else:
                    snap = ref["snap"]
                    if ref.get("manual", False):
                        try:
                            from .. import indicator
                            indicator.show_manual_point(plane, ref["point"], size=2.0)
                        except Exception:
                            pass
                    elif snap["kind"] != "free":
                        render_snap_point(plane, ref["point"], snap["kind"])
                if preview_fn is not None:
                    preview_fn(ref)
                try:
                    from .. import indicator
                    indicator.show_selected_anchors(context.plane, context.metadata.get("selected_anchors", []))
                except Exception:
                    pass
            except Exception:
                pass
    return _PickRefOnce()


def _polygon_vertices(center, circumradius, nb_edges, theta0):
    verts = []
    step = 2.0 * math.pi / float(nb_edges)
    for i in range(nb_edges):
        a = theta0 + i * step
        verts.append((center[0] + circumradius * math.cos(a), center[1] + circumradius * math.sin(a)))
    return verts


def _polygon_vertices_from_reference(center, radius, nb_edges, fit_mode, orientation_mode, ref):
    n = int(nb_edges)
    if n < 3:
        return []
    R = float(radius)
    if fit_mode == "in":
        circum = R
    else:
        circum = R / math.cos(math.pi / n)

    step = 2.0 * math.pi / n

    if orientation_mode == "vertice":
        if ref["kind"] != "point":
            return []
        dx = ref["point"][0] - center[0]
        dy = ref["point"][1] - center[1]
        theta0 = math.atan2(dy, dx)
    elif orientation_mode == "edge_middle":
        if ref["kind"] != "point":
            return []
        dx = ref["point"][0] - center[0]
        dy = ref["point"][1] - center[1]
        theta_mid = math.atan2(dy, dx)
        theta0 = theta_mid - step * 0.5
    else:  # parallel_edge
        if ref["kind"] == "line":
            d = ref["direction"]
            line_angle = math.atan2(d[1], d[0])
        else:
            dx = ref["point"][0] - center[0]
            dy = ref["point"][1] - center[1]
            line_angle = math.atan2(dy, dx)
        theta0 = line_angle - math.pi * 0.5 - step * 0.5

    return _polygon_vertices(center, circum, n, theta0)


def start_circle_to_polygon(sketch_obj=None, params=None, construction=True):
    sketch_obj = sketch_obj or get_or_create_euclid_sketch()
    if params is None:
        return sketch_obj

    ctx = begin_command(CommandContext(
        name="circle_to_polygon",
        primitive="polygon",
        steps=[
            StepSpec("pick_circle", "circle"),
            StepSpec("pick_orientation", "point_or_line"),
        ],
        sketch_obj=sketch_obj,
        plane=get_active_plane(sketch_obj),
    ))
    ctx.metadata["selected_anchors"] = []

    def _start_circle():
        ctx.metadata["selected_anchors"] = []
        return _pick_circle_only_once(ctx, _after_circle)

    def _start_orientation(circle):
        ctx.metadata["selected_anchors"] = [{"kind": "circle", "center": circle["center"], "radius": circle["radius"]}]

        def _preview(ref):
            verts = _polygon_vertices_from_reference(
                circle["center"], circle["radius"], params["nb_edges"], params["inout"], params["orientation"], ref,
            )
            if verts:
                render_preview_polygon(ctx.plane, verts)
            try:
                from .. import indicator
                indicator.show_selected_anchors(ctx.plane, ctx.metadata.get("selected_anchors", []))
            except Exception:
                pass

        def _done(ref):
            verts = _polygon_vertices_from_reference(
                circle["center"], circle["radius"], params["nb_edges"], params["inout"], params["orientation"], ref,
            )
            if not verts:
                cancel_command(ctx)
                return

            from ..core.undo import push_sketch_undo
            push_sketch_undo(sketch_obj)
            data = get_data(sketch_obj)

            if params["action"] == "convert":
                new_entities = []
                removed = False
                for ent in data.entities:
                    if (not removed and isinstance(ent, CircleEntity2D)
                        and dist2(ent.center, circle["center"]) < 1e-7
                        and abs(float(ent.radius) - float(circle["radius"])) < 1e-7):
                        removed = True
                        continue
                    new_entities.append(ent)
                data.entities = new_entities

            for i in range(len(verts)):
                p1 = verts[i]
                p2 = verts[(i + 1) % len(verts)]
                d = (p2[0] - p1[0], p2[1] - p1[1])
                ld = normalize(d)
                if ld == (0.0, 0.0):
                    continue
                data.entities.append(
                    LineEntity2D(
                        origin=p1,
                        direction=ld,
                        construction=construction,
                        meta={"mode": "polygon-edge", "p1": p1, "p2": p2},
                    )
                )

            set_data(sketch_obj, data)
            App.ActiveDocument.recompute()
            try:
                from ..controller import show_local_frame
                show_local_frame(sketch_obj)
            except Exception:
                pass
            finish_command(ctx)

        push_command_restore(ctx, _start_circle)
        return _pick_point_or_reference_once(ctx, params["orientation"], _done, preview_fn=_preview)

    def _after_circle(circle):
        return _start_orientation(circle)

    return _start_circle()

