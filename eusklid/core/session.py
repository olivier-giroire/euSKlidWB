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

from .. import indicator
from ..runtime import reset_interaction_state as runtime_reset_interaction_state
from ..qt_compat import QtCore

try:
    import FreeCADGui as Gui
except Exception:  # pragma: no cover - FreeCAD runtime only
    Gui = None

_ACTIVE_CONTEXT = None
_ACTIVE_HANDLER = None
_ESC_VIEW = None
_ESC_CALLBACK = None


def register_active_handler(handler):
    global _ACTIVE_HANDLER
    _ACTIVE_HANDLER = handler


def unregister_active_handler(handler=None):
    global _ACTIVE_HANDLER
    if handler is None or handler is _ACTIVE_HANDLER:
        _ACTIVE_HANDLER = None



def _function_reentrance_enabled():
    try:
        from .config import get_config
        return bool(get_config().get("feeling", {}).get("function_reentrance", True))
    except Exception:
        return True


def _is_escape_key(info):
    try:
        if str(info.get("State", "")).upper() != "DOWN":
            return False
    except Exception:
        return False
    try:
        key = str(info.get("Key", "")).upper()
        return key in ("ESCAPE", "ESC", "KEY_ESCAPE")
    except Exception:
        return False


def _remove_escape_handler():
    global _ESC_VIEW, _ESC_CALLBACK
    if _ESC_VIEW is not None and _ESC_CALLBACK is not None:
        try:
            _ESC_VIEW.removeEventCallback("SoKeyboardEvent", _ESC_CALLBACK)
        except Exception:
            pass
    _ESC_VIEW = None
    _ESC_CALLBACK = None


def _install_escape_handler(context):
    global _ESC_VIEW, _ESC_CALLBACK
    _remove_escape_handler()
    if not _function_reentrance_enabled():
        return
    if Gui is None:
        return
    try:
        view = Gui.ActiveDocument.ActiveView
    except Exception:
        return

    def _on_key(info):
        try:
            if not _is_escape_key(info):
                return
            try:
                context.metadata["_suppress_reentry"] = True
            except Exception:
                pass
            cancel_command(context)
        except Exception:
            pass

    try:
        _ESC_VIEW = view
        _ESC_CALLBACK = view.addEventCallback("SoKeyboardEvent", _on_key)
    except Exception:
        _ESC_VIEW = None
        _ESC_CALLBACK = None


def reset_interaction_state():
    _remove_escape_handler()
    try:
        indicator.reset_overlay_states(clear_frame_too=False)
    except Exception:
        pass

    global _ACTIVE_HANDLER
    if _ACTIVE_HANDLER is not None:
        try:
            _ACTIVE_HANDLER.finish()
        except Exception:
            pass
        _ACTIVE_HANDLER = None
    runtime_reset_interaction_state()


def begin_command(context):
    global _ACTIVE_CONTEXT
    if _ACTIVE_CONTEXT is not None:
        reset_interaction_state()
    context.metadata.setdefault("_undo_stack", [])
    _ACTIVE_CONTEXT = context
    _install_escape_handler(context)
    return context


def _schedule_reentry(context):
    if context is None:
        return
    try:
        if bool(context.metadata.get("_suppress_reentry", False)):
            return
        if not _function_reentrance_enabled():
            return
        reenter_fn = context.metadata.get("_reenter_fn")
        if reenter_fn is None:
            return
        QtCore.QTimer.singleShot(0, reenter_fn)
    except Exception:
        pass


def finish_command(context=None):
    global _ACTIVE_CONTEXT
    ctx = context or _ACTIVE_CONTEXT
    _ACTIVE_CONTEXT = None
    reset_interaction_state()

    try:
        indicator.reset_overlay_states(clear_frame_too=False)
    except Exception:
        pass

    _schedule_reentry(ctx)


def cancel_command(context=None):
    try:
        if context is not None:
            context.metadata["_suppress_reentry"] = True
    except Exception:
        pass
    finish_command(context)

    try:
        indicator.reset_overlay_states(clear_frame_too=False)
    except Exception:
        pass

def has_active_command():
    return _ACTIVE_CONTEXT is not None


def push_command_restore(context, restore_fn):
    try:
        stack = context.metadata.setdefault("_undo_stack", [])
        stack.append(restore_fn)
    except Exception:
        pass


def undo_active_command():
    global _ACTIVE_CONTEXT
    ctx = _ACTIVE_CONTEXT
    if ctx is None:
        return False
    stack = ctx.metadata.setdefault("_undo_stack", [])
    if not stack:
        return False
    restore_fn = stack.pop()
    try:
        if _ACTIVE_HANDLER is not None:
            try:
                _ACTIVE_HANDLER.finish()
            except Exception:
                pass
    except Exception:
        pass
    try:
        restore_fn()
        return True
    except Exception:
        return False
