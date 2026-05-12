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

from ..feature import get_data as feature_get_data, set_data as feature_set_data, ensure_proxy
from ..geom import LineEntity2D, CircleEntity2D
from ..math2d import point_to_line_distance, dist2
from ..core.snaps import snap_threshold_uv
from .. import indicator


_ACTIVE_SELECTOR = None
_CURRENT_SKETCH = None


def set_active_sketch(obj):
    global _CURRENT_SKETCH
    try:
        _CURRENT_SKETCH = ensure_proxy(obj) if obj is not None else None
    except Exception:
        _CURRENT_SKETCH = obj
    try:
        Gui.Selection.clearSelection()
    except Exception:
        pass
    return _CURRENT_SKETCH


def _is_eusklid_sketch(obj):
    try:
        proxy = getattr(obj, "Proxy", None)
        if proxy is not None and proxy.__class__.__name__ == "euSKlidFeature":
            return True
        return "SketchJson" in getattr(obj, "PropertiesList", [])
    except Exception:
        return False


def _active_sketch():
    global _CURRENT_SKETCH

    if _CURRENT_SKETCH is not None:
        try:
            if _is_eusklid_sketch(_CURRENT_SKETCH):
                return ensure_proxy(_CURRENT_SKETCH)
        except Exception:
            _CURRENT_SKETCH = None

    try:
        sel = Gui.Selection.getSelection()
        for obj in sel:
            if _is_eusklid_sketch(obj):
                return set_active_sketch(obj)
    except Exception:
        pass

    doc = App.ActiveDocument
    if doc is None:
        return None

    for obj in getattr(doc, "Objects", []):
        if _is_eusklid_sketch(obj):
            return set_active_sketch(obj)
    return None
def _line_distance(ent, uv):
    try:
        return point_to_line_distance(uv, ent.origin, ent.direction)
    except Exception:
        return 1e99


def _circle_distance(ent, uv):
    try:
        return abs(math.sqrt(dist2(uv, ent.center)) - float(ent.radius))
    except Exception:
        return 1e99


def _entity_distance(ent, uv):
    if isinstance(ent, LineEntity2D):
        return _line_distance(ent, uv)
    if isinstance(ent, CircleEntity2D):
        return _circle_distance(ent, uv)
    return 1e99


def _pick_entity_index(sketch_obj, uv):
    try:
        data = feature_get_data(sketch_obj)
        tol = snap_threshold_uv(sketch_obj, uv)
    except Exception:
        return None

    best_i = None
    best_d = None
    for i, ent in enumerate(data.entities):
        d = _entity_distance(ent, uv)
        if best_d is None or d < best_d:
            best_i = i
            best_d = d

    if best_i is not None and best_d is not None and best_d <= tol:
        return best_i
    return None


def _selected_anchor_for_entity(data, index):
    try:
        ent = data.entities[index]
        if isinstance(ent, LineEntity2D):
            return {
                "kind": "line",
                "origin": ent.origin,
                "direction": ent.direction,
            }
        if isinstance(ent, CircleEntity2D):
            return {
                "kind": "circle",
                "center": ent.center,
                "radius": ent.radius,
            }
    except Exception:
        pass
    return None


def _refresh_selection_overlay(sketch_obj, selected_indices):
    try:
        data = feature_get_data(sketch_obj)
        anchors = []
        for idx in sorted(selected_indices):
            a = _selected_anchor_for_entity(data, idx)
            if a is not None:
                anchors.append(a)
        indicator.show_selected_anchors(data.plane, anchors)
    except Exception:
        pass


class SelectionDeleteHandler:
    def __init__(self):
        self.sketch_obj = None
        self.selected_indices = set()
        self._closed = False
        self._view = None
        self._cb_mouse = None
        self._cb_key = None
        self.start()

    def start(self):
        try:
            self._view = Gui.ActiveDocument.ActiveView
            self._cb_mouse = self._view.addEventCallback("SoMouseButtonEvent", self.on_mouse)
            self._cb_key = self._view.addEventCallback("SoKeyboardEvent", self.on_key)
        except Exception:
            self._closed = True

    def finish(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._view is not None and self._cb_mouse is not None:
                self._view.removeEventCallback("SoMouseButtonEvent", self._cb_mouse)
        except Exception:
            pass
        try:
            if self._view is not None and self._cb_key is not None:
                self._view.removeEventCallback("SoKeyboardEvent", self._cb_key)
        except Exception:
            pass
        try:
            indicator.clear_selected()
        except Exception:
            pass

    def _shift_requested(self, info):
        try:
            if bool(info.get("ShiftDown", False)):
                return True
        except Exception:
            pass
        try:
            from ..qt_compat import QtCore
            mods = QtCore.QCoreApplication.keyboardModifiers()
            return bool(mods & QtCore.Qt.ShiftModifier)
        except Exception:
            return False

    def on_mouse(self, info):
        try:
            if self._closed:
                return
            if info.get("State") != "DOWN" or info.get("Button") != "BUTTON1":
                return
            if not self._shift_requested(info):
                return

            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass

            sketch = _active_sketch()
            if sketch is None:
                return

            pos = info.get("Position")
            if not pos:
                return

            data = feature_get_data(sketch)
            world = self._view.getPoint(pos[0], pos[1])
            uv = data.plane.world_to_uv((float(world[0]), float(world[1]), float(world[2])))

            idx = _pick_entity_index(sketch, uv)
            if idx is None:
                return

            if self.sketch_obj is not sketch:
                self.sketch_obj = sketch
                self.selected_indices = set()

            if idx in self.selected_indices:
                self.selected_indices.remove(idx)
            else:
                self.selected_indices.add(idx)

            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass
            _refresh_selection_overlay(sketch, self.selected_indices)
        except Exception:
            pass

    def _is_delete_key(self, info):
        try:
            key = str(info.get("Key", "")).upper()
            if key in ("DELETE", "DEL", "SUPR", "KEY_DELETE"):
                return True
        except Exception:
            pass
        return False

    def on_key(self, info):
        try:
            if self._closed:
                return
            if info.get("State") != "DOWN":
                return
            if not self._is_delete_key(info):
                return
            self.delete_selected()
        except Exception:
            pass

    def delete_selected(self):
        try:
            Gui.Selection.clearSelection()
        except Exception:
            pass
        if self.sketch_obj is None or not self.selected_indices:
            return
        try:
            try:
                from ..core.undo import push_sketch_undo
                push_sketch_undo(self.sketch_obj)
            except Exception:
                pass
            data = feature_get_data(self.sketch_obj)
            kept = [
                ent for i, ent in enumerate(data.entities)
                if i not in self.selected_indices
            ]
            data.entities = kept
            feature_set_data(self.sketch_obj, data)
            self.selected_indices = set()
            indicator.clear_selected()
            try:
                set_active_sketch(self.sketch_obj)
            except Exception:
                pass
            if App.ActiveDocument is not None:
                App.ActiveDocument.recompute()
        except Exception:
            pass


def start_selection_delete_handler():
    global _ACTIVE_SELECTOR
    if _ACTIVE_SELECTOR is None or getattr(_ACTIVE_SELECTOR, "_closed", False):
        _ACTIVE_SELECTOR = SelectionDeleteHandler()
    return _ACTIVE_SELECTOR


def stop_selection_delete_handler():
    global _ACTIVE_SELECTOR
    if _ACTIVE_SELECTOR is not None:
        try:
            _ACTIVE_SELECTOR.finish()
        except Exception:
            pass
    _ACTIVE_SELECTOR = None
_CURRENT_SKETCH = None
