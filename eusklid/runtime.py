from . import indicator

"""Compatibility facade for the refactor core.

This module exposes a stable API for the new core/* modules while avoiding
imports from controller.py to prevent circular dependencies.
"""

from .feature import get_data, set_data, create_sketch
from .legacy_api import get_or_create_euclid_sketch, reset_interaction_state
from .core.undo import push_sketch_undo
from .geom import LineEntity2D, CircleEntity2D
from .math2d import normalize
import FreeCAD as App
import FreeCADGui as Gui

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

