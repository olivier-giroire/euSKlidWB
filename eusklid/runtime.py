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

"""Compatibility facade for the refactor core.

This module exposes a stable API for the new core/* modules while avoiding
imports from controller.py to prevent circular dependencies.
"""

from .feature import get_data, set_data, create_sketch  # noqa: F401
from .legacy_api import get_or_create_euclid_sketch, reset_interaction_state  # noqa: F401
from .core.undo import push_sketch_undo
from .geom import LineEntity2D, CircleEntity2D
from .math2d import normalize
import FreeCAD as App
import FreeCADGui as Gui

__all__ = [
    "get_data",
    "set_data",
    "create_sketch",
    "get_or_create_euclid_sketch",
    "reset_interaction_state",
]


def get_active_plane(sketch_obj):
    return get_data(sketch_obj).plane

def commit_line(sketch_obj, origin, direction, construction=True, mode="generic-line"):
    push_sketch_undo(sketch_obj)
    data = get_data(sketch_obj)
    data.entities.append(
        LineEntity2D(
            origin=origin,
            direction=normalize(direction),
            construction=construction,
            meta={"mode": mode},
        )
    )
    set_data(sketch_obj, data)
    App.ActiveDocument.recompute()
    try:
        Gui.Selection.clearSelection()
    except Exception:
        pass
    try:
        from .controller import show_local_frame
        show_local_frame(sketch_obj)
    except Exception:
        pass
    return sketch_obj

def commit_circle(sketch_obj, center, radius, construction=True, mode="generic-circle"):
    push_sketch_undo(sketch_obj)
    data = get_data(sketch_obj)
    data.entities.append(
        CircleEntity2D(
            center=center,
            radius=radius,
            construction=construction,
            meta={"mode": mode},
        )
    )
    set_data(sketch_obj, data)
    App.ActiveDocument.recompute()
    try:
        Gui.Selection.clearSelection()
    except Exception:
        pass
    try:
        from .controller import show_local_frame
        show_local_frame(sketch_obj)
    except Exception:
        pass
    return sketch_obj
