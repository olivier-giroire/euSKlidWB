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

_ACTIVE_CONTEXT = None
_ACTIVE_HANDLER = None


def register_active_handler(handler):
    global _ACTIVE_HANDLER
    _ACTIVE_HANDLER = handler


def unregister_active_handler(handler=None):
    global _ACTIVE_HANDLER
    if handler is None or handler is _ACTIVE_HANDLER:
        _ACTIVE_HANDLER = None


def reset_interaction_state():
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
    return context


def finish_command(context=None):
    global _ACTIVE_CONTEXT
    _ACTIVE_CONTEXT = None
    reset_interaction_state()


    try:
        indicator.reset_overlay_states(clear_frame_too=False)
    except Exception:
        pass

def cancel_command(context=None):
    finish_command(context)


    try:
        indicator.reset_overlay_states(clear_frame_too=False)
    except Exception:
        pass

def get_active_context():
    return _ACTIVE_CONTEXT


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
