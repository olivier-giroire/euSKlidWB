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

"""Stable compatibility layer used by the refactored runtime."""

import FreeCAD as App

from .feature import ensure_proxy, create_sketch
from .plane import SketchPlane
from . import indicator

_LEGACY_STOPPER = None


def set_legacy_stopper(func):
    global _LEGACY_STOPPER
    _LEGACY_STOPPER = func


def get_or_create_euclid_sketch():
    doc = App.ActiveDocument
    if doc is None:
        raise RuntimeError("No active document.")
    for obj in doc.Objects:
        if getattr(obj, "Proxy", None) and obj.Proxy.__class__.__name__ == "euSKlidFeature":
            return ensure_proxy(obj)
    return create_sketch(doc, plane=SketchPlane.XY())


def reset_interaction_state():
    global _LEGACY_STOPPER

    if _LEGACY_STOPPER is not None:
        try:
            _LEGACY_STOPPER()
        except Exception:
            pass

    try:
        indicator.clear_arrow()
    except Exception:
        pass
    try:
        indicator.clear_highlight()
    except Exception:
        pass
    try:
        indicator.clear_preview()
    except Exception:
        pass
    try:
        indicator.clear_candidates()
    except Exception:
        pass
    try:
        indicator.clear_snap()
    except Exception:
        pass
    try:
        indicator.clear_selected()
    except Exception:
        pass
