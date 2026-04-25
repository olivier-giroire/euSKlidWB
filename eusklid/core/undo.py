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


def has_sketch_undo(sketch_obj):
    try:
        return len(_stack_for(sketch_obj)) > 0
    except Exception:
        return False


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
