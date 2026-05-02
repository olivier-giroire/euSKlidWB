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

import copy

import FreeCAD as App

from ..runtime import get_data, set_data

_SKETCH_UNDO = {}


def _stack_for(sketch_obj):
    return _SKETCH_UNDO.setdefault(sketch_obj.Name, [])


def push_sketch_undo(sketch_obj):
    try:
        data = get_data(sketch_obj)
        snapshot = copy.deepcopy(data.entities)
        _stack_for(sketch_obj).append(snapshot)
    except Exception:
        pass


def undo_last_sketch_edit(sketch_obj):
    try:
        stack = _stack_for(sketch_obj)
        if not stack:
            return False
        entities = stack.pop()
        data = get_data(sketch_obj)
        data.entities = entities
        set_data(sketch_obj, data)
        if App.ActiveDocument is not None:
            App.ActiveDocument.recompute()
        return True
    except Exception:
        return False
