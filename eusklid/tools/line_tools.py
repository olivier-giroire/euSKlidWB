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
from ..core.picking import pick_reference_line_once, pick_line_anchor_once
from ..core.snaps import compute_contextual_snaps, compute_free_point
from ..core.render import render_preview_line, render_snap_point, clear_render_layers, render_highlight_circle
from ..runtime import (
    get_active_plane,
    get_or_create_euclid_sketch,
    commit_line,
    get_data,
    set_data,
)
from ..math2d import visible_segment_for_line, perp, normalize, project_point_on_line, dist2, lines_through_point_tangent_circle, parallel_lines_tangent_circle, parallel_ref_tangent_circle
from ..geom import LineEntity2D
from ..qt_compat import QtCore
import FreeCAD as App
import FreeCADGui as Gui
from ..solvers.line_solvers import build_point_angle_lines, build_lines_from_two_anchors


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

def _pick_point_once(context, direction, construction=True, mode="generic-line"):
    sketch_obj = context.sketch_obj
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

                commit_line(sketch_obj, uv, direction, construction=construction, mode=mode)
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
                        indicator.clear_snap()
                    except Exception:
                        pass
                else:
                    render_snap_point(plane, uv, snap["kind"])

                a, b = visible_segment_for_line(uv, direction, 1000.0)
                render_preview_line(plane, a, b)
            except Exception:
                pass

    return _PickPointOnce()


def start_series_parallel_ref(sketch_obj=None, ask_distance_series=None, construction=True):
    sketch_obj = sketch_obj or get_or_create_euclid_sketch()
    ctx = begin_command(CommandContext(
        name="series_parallel_ref",
        primitive="line",
        steps=[StepSpec("pick_reference", "reference_line")],
        sketch_obj=sketch_obj,
        plane=get_active_plane(sketch_obj),
    ))

    def _done(ref):
        direction = normalize(ref["direction"])
        if ref.get("kind") == "axis" and ref.get("axis") == "U":
            normal = (0.0, 1.0)
        elif ref.get("kind") == "axis" and ref.get("axis") == "V":
            normal = (1.0, 0.0)
        else:
            normal = normalize(perp(direction))

        try:
            from .. import indicator
            indicator.clear_arrow()
            indicator.show_direction_field(
                ctx.plane,
                ref["origin"],
                direction,
                normal,
                count=10,
                spacing=30.0,
                length=30.0,
                head=5.0,
            )
            Gui.updateGui()
        except Exception:
            pass

        values = ask_distance_series("Distances for Series ∥/Ref.\nExamples:\n30,33,40,43\nrepeat 13 (0,1) origin 0 step 2.5\nrepeat 13 (0,1) org 0 step 2.5, repeat 6 (0,2) o 40 s 8") if ask_distance_series else None
        if values is None:
            cancel_command(ctx)
            return

        data = get_data(sketch_obj)
        elog.info("Series //Ref: creating %d construction line(s)" % len(values))

        series_meta = getattr(values, "meta", {}) or {}
        series_items = getattr(values, "items", []) or []
        series_id = "series-%d" % (len(data.entities) + 1)

        for i, d in enumerate(values):
            origin = (
                ref["origin"][0] + normal[0] * d,
                ref["origin"][1] + normal[1] * d,
            )

            item = series_items[i] if i < len(series_items) else {"distance": d, "index": i}
            meta = {
                "mode": "parallel-ref-series",
                "series_id": series_id,
                "series_kind": series_meta.get("kind", "list"),
                "distance": float(d),
                "sequence_index": int(i),
            }

            if item.get("block_kind") == "repeat":
                meta.update({
                    "series_kind": "repeat",
                    "sequence_block_id": item.get("block_id", ""),
                    "sequence_origin": float(item.get("origin", 0.0)),
                    "sequence_repeat": int(item.get("repeat", 0)),
                    "sequence_step": float(item.get("step", 0.0)),
                    "sequence_pattern": list(item.get("pattern", [])),
                    "repeat_index": int(item.get("repeat_index", 0)),
                    "pattern_index": int(item.get("pattern_index", 0)),
                    "pattern_value": float(item.get("pattern_value", 0.0)),
                })

            data.entities.append(
                LineEntity2D(
                    origin=origin,
                    direction=direction,
                    construction=construction,
                    meta=meta,
                )
            )

        set_data(sketch_obj, data)
        App.ActiveDocument.recompute()
        finish_command(ctx)

    return pick_reference_line_once(Gui.ActiveDocument.ActiveView, ctx, _done)


def start_parallel_ref_point(sketch_obj=None, construction=True, perpendicular=False):
    sketch_obj = sketch_obj or get_or_create_euclid_sketch()
    ctx = begin_command(CommandContext(
        name="perpendicular_ref_anchor" if perpendicular else "parallel_ref_anchor",
        primitive="line",
        steps=[
            StepSpec("pick_reference", "reference_line"),
            StepSpec("pick_anchor", "point"),
        ],
        sketch_obj=sketch_obj,
        plane=get_active_plane(sketch_obj),
    ))
    ctx.metadata["selected_anchors"] = []

    def _start_ref():
        ctx.metadata["selected_anchors"] = []
        return pick_reference_line_once(Gui.ActiveDocument.ActiveView, ctx, _done_ref)

    def _start_point(ref):
        direction = normalize(perp(ref["direction"])) if perpendicular else normalize(ref["direction"])
        ctx.metadata["tangent_line_direction"] = direction
        a1 = {"kind": ref.get("kind", "line"), "origin": ref["origin"], "direction": ref["direction"]}
        ctx.metadata["selected_anchors"] = [a1]
        return _pick_point_once(
            ctx,
            direction,
            construction=construction,
            mode="perpendicular-ref-anchor" if perpendicular else "parallel-ref-anchor",
        )

    def _done_ref(ref):
        push_command_restore(ctx, _start_ref)
        return _start_point(ref)

    return _start_ref()

def _pick_best_line_candidate(candidates, uv):
    best = None
    best_dist = None
    for cand in candidates or []:
        proj = project_point_on_line(uv, cand["origin"], cand["direction"])
        d = dist2(uv, proj)
        if best_dist is None or d < best_dist:
            best = cand
            best_dist = d
    return best


def start_point_angle(sketch_obj=None, ask_angle=None, construction=True):
    sketch_obj = sketch_obj or get_or_create_euclid_sketch()
    ctx = begin_command(CommandContext(
        name="point_angle",
        primitive="line",
        steps=[
            StepSpec("pick_reference", "reference_line"),
            StepSpec("pick_point", "point"),
            StepSpec("pick_solution", "solution_line"),
        ],
        sketch_obj=sketch_obj,
        plane=get_active_plane(sketch_obj),
    ))

    def _done_ref(ref):
        plane = ctx.plane
        view = Gui.ActiveDocument.ActiveView

        class _PickPointOnce:
            def __init__(self):
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
                        QtCore.QTimer.singleShot(0, lambda: cancel_command(ctx))
                        return
                    if button != "BUTTON1":
                        return

                    pos = info.get("Position")
                    if not pos:
                        return

                    world = view.getPoint(pos[0], pos[1])
                    uv0 = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))
                    snap = compute_contextual_snaps(ctx, uv0)
                    uv = snap["point"]

                    self.finish()
                    QtCore.QTimer.singleShot(0, lambda p=uv: _done_point(ref, p))
                except Exception:
                    self.finish()
                    QtCore.QTimer.singleShot(0, lambda: cancel_command(ctx))

            def on_move(self, info):
                try:
                    if self._closed:
                        return

                    pos = info.get("Position")
                    if not pos:
                        return

                    world = view.getPoint(pos[0], pos[1])
                    uv0 = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))
                    snap = compute_contextual_snaps(ctx, uv0)
                    uv = snap["point"]

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
                        render_snap_point(plane, uv, snap["kind"])
                except Exception:
                    pass

        return _PickPointOnce()

    def _done_point(ref, point):
        try:
            angle = ask_angle() if ask_angle else None
        except Exception:
            cancel_command(ctx)
            return

        if angle is None:
            cancel_command(ctx)
            return

        plane = ctx.plane
        view = Gui.ActiveDocument.ActiveView
        cands = build_point_angle_lines(ref, point, angle)

        class _PickSolutionOnce:
            def __init__(self):
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
                        QtCore.QTimer.singleShot(0, lambda: cancel_command(ctx))
                        return
                    if button != "BUTTON1":
                        return

                    pos = info.get("Position")
                    if not pos:
                        return

                    world = view.getPoint(pos[0], pos[1])
                    uv0 = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))
                    best = _pick_best_line_candidate(cands, uv0) or cands[0]

                    commit_line(
                        sketch_obj,
                        best["origin"],
                        best["direction"],
                        construction=construction,
                        mode="point-angle",
                    )
                    self.finish()
                    QtCore.QTimer.singleShot(0, lambda: finish_command(ctx))
                except Exception:
                    self.finish()
                    QtCore.QTimer.singleShot(0, lambda: cancel_command(ctx))

            def on_move(self, info):
                try:
                    if self._closed:
                        return

                    pos = info.get("Position")
                    if not pos:
                        return

                    world = view.getPoint(pos[0], pos[1])
                    uv0 = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))

                    try:
                        from .. import indicator
                        indicator.clear_snap()
                        indicator.clear_highlight()
                    except Exception:
                        pass

                    best = _pick_best_line_candidate(cands, uv0) or cands[0]
                    a, b = visible_segment_for_line(best["origin"], best["direction"], 1000.0)
                    render_preview_line(plane, a, b)
                except Exception:
                    pass

        return _PickSolutionOnce()

    return pick_reference_line_once(Gui.ActiveDocument.ActiveView, ctx, _done_ref)


def _pick_line_solution_once(context, candidates, construction=True, mode="line-2anchors"):
    sketch_obj = context.sketch_obj
    plane = context.plane
    view = Gui.ActiveDocument.ActiveView

    class _PickSolutionOnce:
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

        def _pick_best(self, uv):
            best = None
            best_dist = None
            for cand in candidates:
                proj = project_point_on_line(uv, cand["origin"], cand["direction"])
                d = dist2(uv, proj)
                if best_dist is None or d < best_dist:
                    best = cand
                    best_dist = d
            return best

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

                best = self._pick_best(uv0)
                if best is None:
                    return

                commit_line(sketch_obj, best["origin"], best["direction"], construction=construction, mode=mode)
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

                best = self._pick_best(uv0)
                if best is None:
                    return

                a, b = visible_segment_for_line(best["origin"], best["direction"], 1000.0)
                clear_render_layers()
                render_preview_line(plane, a, b)
            except Exception:
                pass

    return _PickSolutionOnce()


def start_line_two_anchors(sketch_obj=None, construction=True):
    sketch_obj = sketch_obj or get_or_create_euclid_sketch()
    ctx = begin_command(CommandContext(
        name="line_two_anchors",
        primitive="line",
        steps=[
            StepSpec("pick_anchor1", "line_anchor"),
            StepSpec("pick_anchor2", "line_anchor"),
        ],
        sketch_obj=sketch_obj,
        plane=get_active_plane(sketch_obj),
    ))
    ctx.metadata['selected_anchors'] = []

    def _start_anchor1():
        ctx.metadata['selected_anchors'] = []
        return pick_line_anchor_once(Gui.ActiveDocument.ActiveView, ctx, _after_anchor1)

    def _start_anchor2(a1):
        ctx.metadata['selected_anchors'] = [a1]
        return pick_line_anchor_once(Gui.ActiveDocument.ActiveView, ctx, _after_anchor2(a1))

    def _after_anchor1(a1):
        push_command_restore(ctx, _start_anchor1)
        return _start_anchor2(a1)

    def _after_anchor2(a1):
        def __done(a2):
            cands = build_lines_from_two_anchors(a1, a2)
            if not cands:
                cancel_command(ctx)
                return
            if len(cands) == 1:
                c = cands[0]
                commit_line(sketch_obj, c["origin"], c["direction"], construction=construction, mode=c["mode"])
                finish_command(ctx)
                return
            push_command_restore(ctx, lambda: _start_anchor2(a1))
            return _pick_line_solution_once(ctx, cands, construction=construction, mode="line-2anchors")
        return __done

    return _start_anchor1()

def _pick_circle_only_once(context, on_done, preview_fn=None):
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
                QtCore.QTimer.singleShot(0, lambda c=dict(circle), uv=uv0: on_done(c, uv))
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
                    render_highlight_circle(plane, circle["center"], circle["radius"])
                    if preview_fn is not None:
                        preview_fn(circle, uv0)
                try:
                    from .. import indicator
                    indicator.show_selected_anchors(context.plane, context.metadata.get("selected_anchors", []))
                except Exception:
                    pass
            except Exception:
                pass

    return _PickCircleOnlyOnce()


def start_line_point_tangent_circle(sketch_obj=None, construction=True):
    sketch_obj = sketch_obj or get_or_create_euclid_sketch()
    ctx = begin_command(CommandContext(
        name="line_point_tangent_circle",
        primitive="line",
        steps=[
            StepSpec("pick_point", "point"),
            StepSpec("pick_circle", "circle"),
            StepSpec("pick_solution", "solution_line"),
        ],
        sketch_obj=sketch_obj,
        plane=get_active_plane(sketch_obj),
    ))
    ctx.metadata["selected_anchors"] = []

    def _after_point(point):
        a1 = ctx.metadata.get("last_anchor") or {"kind": "point", "point": point, "manual": False}
        ctx.metadata["selected_anchors"] = [a1]

        def _preview(circle, uv):
            cands = lines_through_point_tangent_circle(point, circle["center"], circle["radius"])
            if cands:
                best = _pick_best_line_candidate(cands, uv) or cands[0]
                a, b = visible_segment_for_line(best["origin"], best["direction"], 1000.0)
                render_preview_line(ctx.plane, a, b)

        def _done(circle, uv):
            a2 = {"kind": "circle", "center": circle["center"], "radius": circle["radius"]}
            ctx.metadata["selected_anchors"] = [a1, a2]
            cands = lines_through_point_tangent_circle(point, circle["center"], circle["radius"])
            if not cands:
                cancel_command(ctx)
                return
            if len(cands) == 1:
                c = cands[0]
                commit_line(sketch_obj, c["origin"], c["direction"], construction=construction, mode=c.get("mode", "point-tg-circle"))
                finish_command(ctx)
                return
            return _pick_line_solution_once(ctx, cands, construction=construction, mode="point-tg-circle")

        return _pick_circle_only_once(ctx, _done, preview_fn=_preview)

    return __pick_point_and_callback(ctx, _after_point)


def _start_line_axis_tangent_circle(sketch_obj=None, direction=(1.0, 0.0), mode_name="parallel-u-tg-circle", construction=True):
    sketch_obj = sketch_obj or get_or_create_euclid_sketch()
    ctx = begin_command(CommandContext(
        name=mode_name,
        primitive="line",
        steps=[
            StepSpec("pick_circle", "circle"),
            StepSpec("pick_solution", "solution_line"),
        ],
        sketch_obj=sketch_obj,
        plane=get_active_plane(sketch_obj),
    ))
    ctx.metadata["selected_anchors"] = []

    def _preview(circle, uv):
        cands = parallel_lines_tangent_circle(direction, circle["center"], circle["radius"])
        if cands:
            best = _pick_best_line_candidate(cands, uv) or cands[0]
            a, b = visible_segment_for_line(best["origin"], best["direction"], 1000.0)
            render_preview_line(ctx.plane, a, b)

    def _done(circle, uv):
        a1 = {"kind": "circle", "center": circle["center"], "radius": circle["radius"]}
        ctx.metadata["selected_anchors"] = [a1]
        cands = parallel_lines_tangent_circle(direction, circle["center"], circle["radius"])
        for c in cands:
            c["mode"] = mode_name
        if not cands:
            cancel_command(ctx)
            return
        if len(cands) == 1:
            c = cands[0]
            commit_line(sketch_obj, c["origin"], c["direction"], construction=construction, mode=c["mode"])
            finish_command(ctx)
            return
        return _pick_line_solution_once(ctx, cands, construction=construction, mode=mode_name)

    return _pick_circle_only_once(ctx, _done, preview_fn=_preview)


def start_line_parallel_u_tangent_circle(sketch_obj=None, construction=True):
    return _start_line_axis_tangent_circle(
        sketch_obj=sketch_obj,
        direction=(1.0, 0.0),
        mode_name="parallel-u-tg-circle",
        construction=construction,
    )


def start_line_parallel_v_tangent_circle(sketch_obj=None, construction=True):
    return _start_line_axis_tangent_circle(
        sketch_obj=sketch_obj,
        direction=(0.0, 1.0),
        mode_name="parallel-v-tg-circle",
        construction=construction,
    )


def start_line_parallel_ref_tangent_circle(sketch_obj=None, construction=True):
    sketch_obj = sketch_obj or get_or_create_euclid_sketch()
    ctx = begin_command(CommandContext(
        name="parallel-ref-tg-circle",
        primitive="line",
        steps=[
            StepSpec("pick_reference", "reference_line"),
            StepSpec("pick_circle", "circle"),
            StepSpec("pick_solution", "solution_line"),
        ],
        sketch_obj=sketch_obj,
        plane=get_active_plane(sketch_obj),
    ))
    ctx.metadata["selected_anchors"] = []

    def _after_ref(ref):
        a1 = {"kind": ref.get("kind", "line"), "origin": ref["origin"], "direction": ref["direction"]}
        ctx.metadata["selected_anchors"] = [a1]

        def _preview(circle, uv):
            cands = parallel_ref_tangent_circle(ref["origin"], ref["direction"], circle["center"], circle["radius"])
            if cands:
                best = _pick_best_line_candidate(cands, uv) or cands[0]
                a, b = visible_segment_for_line(best["origin"], best["direction"], 1000.0)
                render_preview_line(ctx.plane, a, b)

        def _done(circle, uv):
            a2 = {"kind": "circle", "center": circle["center"], "radius": circle["radius"]}
            ctx.metadata["selected_anchors"] = [a1, a2]
            cands = parallel_ref_tangent_circle(ref["origin"], ref["direction"], circle["center"], circle["radius"])
            for c in cands:
                c["mode"] = "parallel-ref-tg-circle"
            if not cands:
                cancel_command(ctx)
                return
            if len(cands) == 1:
                c = cands[0]
                commit_line(sketch_obj, c["origin"], c["direction"], construction=construction, mode=c["mode"])
                finish_command(ctx)
                return
            return _pick_line_solution_once(ctx, cands, construction=construction, mode="parallel-ref-tg-circle")

        return _pick_circle_only_once(ctx, _done, preview_fn=_preview)

    return pick_reference_line_once(Gui.ActiveDocument.ActiveView, ctx, _after_ref)


# helper reused locally
def __pick_point_and_callback(context, on_done, preview_fn=None):
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
                    context.metadata["last_anchor"] = {"kind": "point", "point": uv, "manual": snap.get("kind") == "free"}
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
                    indicator.show_selected_anchors(context.plane, context.metadata.get("selected_anchors", []))
                except Exception:
                    pass
            except Exception:
                pass

    return _PickPointOnce()



def _estimate_grid_family_count(view, plane, center_uv, direction, step):
    try:
        size = view.getSize()
        w = int(size[0])
        h = int(size[1])
        corners = [(0, 0), (w, 0), (0, h), (w, h)]
        uvs = []
        for sx, sy in corners:
            world = view.getPoint(int(sx), int(sy))
            uv = plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))
            uvs.append(uv)
        n = normalize(perp(direction))
        vals = [uv[0] * n[0] + uv[1] * n[1] for uv in uvs]
        span = max(vals) - min(vals)
        half_count = max(1, int(math.ceil((span * 0.5) / max(float(step), 1e-9))))
        count = 2 * half_count + 1
        return max(3, count)
    except Exception:
        return 11


def _grid_line_intersection(o1, d1, o2, d2):
    x1, y1 = o1
    dx1, dy1 = d1
    x2, y2 = o2
    dx2, dy2 = d2
    det = dx1 * dy2 - dy1 * dx2
    if abs(det) < 1e-12:
        return None
    t = ((x2 - x1) * dy2 - (y2 - y1) * dx2) / det
    return (x1 + t * dx1, y1 + t * dy1)


def _grid_line_segment_from_intersections(origin, direction, other_lines, margin):
    """Return segment endpoints around the last intersections.

    If no non-parallel intersections are available, return None and keep the
    line in its legacy infinite/visible-segment display mode.
    """
    d = normalize(direction)
    if d == (0.0, 0.0):
        return None

    params = []
    for other_origin, other_direction in other_lines:
        p = _grid_line_intersection(origin, d, other_origin, other_direction)
        if p is None:
            continue
        t = (p[0] - origin[0]) * d[0] + (p[1] - origin[1]) * d[1]
        params.append(t)

    if not params:
        return None

    margin = abs(float(margin))
    t0 = min(params) - margin
    t1 = max(params) + margin
    return (
        (origin[0] + d[0] * t0, origin[1] + d[1] * t0),
        (origin[0] + d[0] * t1, origin[1] + d[1] * t1),
    )

def start_line_grid(sketch_obj=None, grid_params=None, construction=True):
    sketch_obj = sketch_obj or get_or_create_euclid_sketch()
    if not grid_params:
        return sketch_obj

    ctx = begin_command(CommandContext(
        name="line_grid",
        primitive="line",
        steps=[StepSpec("pick_center", "point")],
        sketch_obj=sketch_obj,
        plane=get_active_plane(sketch_obj),
    ))
    ctx.metadata["selected_anchors"] = []

    def _start_center():
        def _preview(center):
            try:
                from .. import indicator
                indicator.show_selected_anchors(ctx.plane, [{"kind": "point", "point": center, "manual": False, "size": 2.0}])
            except Exception:
                pass

        def _done(center):
            data = get_data(sketch_obj)
            view = Gui.ActiveDocument.ActiveView
            from ..core.undo import push_sketch_undo
            push_sketch_undo(sketch_obj)

            families = []
            for spec in grid_params.get("series", []):
                try:
                    step = float(spec["step"])
                    angle_deg = float(spec["angle"])
                    requested_count = int(spec.get("count", 0))
                except Exception:
                    continue

                if step <= 0.0:
                    continue

                a = math.radians(angle_deg)
                direction = normalize((math.cos(a), math.sin(a)))
                if direction == (0.0, 0.0):
                    continue

                if requested_count <= 0:
                    requested_count = _estimate_grid_family_count(view, ctx.plane, center, direction, step)

                requested_count = max(1, int(requested_count))
                half = requested_count // 2
                if requested_count % 2:
                    offsets = list(range(-half, half + 1))
                else:
                    offsets = list(range(-half, half))

                n = normalize(perp(direction))
                lines = []
                for k in offsets:
                    origin = (center[0] + n[0] * step * k, center[1] + n[1] * step * k)
                    lines.append({
                        "origin": origin,
                        "direction": direction,
                        "step": step,
                        "spec": spec,
                        "offset": k,
                    })

                families.append({
                    "spec": spec,
                    "step": step,
                    "direction": direction,
                    "lines": lines,
                })

            all_lines = []
            total_grid_lines = sum(len(family["lines"]) for family in families)
            elog.info("Grid: creating %d construction line(s) in %d series" % (total_grid_lines, len(families)))

            for family in families:
                for line in family["lines"]:
                    all_lines.append(line)

            total_grid_lines = sum(len(family["lines"]) for family in families)
            elog.info("Grid: creating %d construction line(s) in %d series" % (total_grid_lines, len(families)))

            for family in families:
                for line in family["lines"]:
                    other_lines = [
                        (other["origin"], other["direction"])
                        for other in all_lines
                        if other is not line
                    ]
                    seg = _grid_line_segment_from_intersections(
                        line["origin"],
                        line["direction"],
                        other_lines,
                        margin=line["step"],
                    )

                    meta = {
                        "mode": "grid",
                        "series": line["spec"].get("name", "?"),
                        "center": center,
                        "grid_count": len(family["lines"]),
                        "grid_step": line["step"],
                    }
                    if seg is not None:
                        meta["segment_a"] = seg[0]
                        meta["segment_b"] = seg[1]

                    data.entities.append(
                        LineEntity2D(
                            origin=line["origin"],
                            direction=line["direction"],
                            construction=construction,
                            meta=meta,
                        )
                    )

            set_data(sketch_obj, data)
            App.ActiveDocument.recompute()
            finish_command(ctx)

        push_command_restore(ctx, _start_center)
        return __pick_point_and_callback(ctx, _done, preview_fn=_preview)

    return _start_center()
