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


import FreeCAD as App

ROOT_NAME = "euSKlidRoot"
CONTEXT_NAME = "euSKlidContext"
FRAME_NAME = "euSKlidFrame"
INDICATORS_NAME = "euSKlidIndicators"
TRANSIENT_NAME = "euSKlidTransient"
CONSTRUCTION_NAME = "euSKlidConstruction"
PATH_NAME = "euSKlidPath"


def _set_label(obj, label):
    try:
        obj.Label = label
    except Exception:
        pass


def _get_or_create_group(doc, name, label, parent=None):
    obj = doc.getObject(name)
    if obj is None:
        obj = doc.addObject("App::DocumentObjectGroup", name)
    _set_label(obj, label)
    if parent is not None:
        try:
            if obj not in getattr(parent, 'Group', []):
                parent.addObject(obj)
        except Exception:
            pass
    return obj

def ensure_euclid_groups(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    root = _get_or_create_group(doc, ROOT_NAME, 'Sketch')
    context = _get_or_create_group(doc, CONTEXT_NAME, 'Context', root)
    _get_or_create_group(doc, FRAME_NAME, 'Frame', context)
    _get_or_create_group(doc, INDICATORS_NAME, 'Indicators', context)
    _get_or_create_group(doc, TRANSIENT_NAME, 'Transient', context)
    _get_or_create_group(doc, CONSTRUCTION_NAME, 'Construction', root)
    _get_or_create_group(doc, PATH_NAME, 'Path', root)
    return root


def get_transient_group(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    ensure_euclid_groups(doc)
    return doc.getObject(TRANSIENT_NAME)


def get_construction_group(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    ensure_euclid_groups(doc)
    return doc.getObject(CONSTRUCTION_NAME)


def get_path_group(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    ensure_euclid_groups(doc)
    return doc.getObject(PATH_NAME)


def ensure_path_instance_group(doc=None, path_id=None, label=None):
    """Return/create the per-closed-path group under the global Path group.

    The top-level Path group remains the container for all saved contours, while
    every closed path gets its own child group so it can be shown/hidden as a
    unit in the FreeCAD tree.
    """
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    ensure_euclid_groups(doc)
    parent = get_path_group(doc)
    safe_id = str(path_id or label or "Path")
    safe_id = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in safe_id)
    name = "euSKlidPath_%s" % safe_id
    return _get_or_create_group(doc, name, label or safe_id, parent)


def add_to_group(obj, group):
    if obj is None or group is None:
        return obj
    try:
        if obj not in getattr(group, 'Group', []):
            group.addObject(obj)
    except Exception:
        pass
    return obj
