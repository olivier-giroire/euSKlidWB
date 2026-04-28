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

import json
from .plane import SketchPlane
from .geom import LineEntity2D, CircleEntity2D

class SketchData:
    def __init__(self, plane=None, entities=None):
        self.plane = plane or SketchPlane.XY()
        self.entities = entities or []

    def to_dict(self):
        return {"plane":self.plane.to_dict(),"entities":[e.to_dict() for e in self.entities]}

    @classmethod
    def from_dict(cls,d):
        ents=[]
        for item in d.get("entities",[]):
            if item.get("kind")=="line":
                ents.append(LineEntity2D.from_dict(item))
            elif item.get("kind")=="circle":
                ents.append(CircleEntity2D.from_dict(item))
        return cls(plane=SketchPlane.XY(), entities=ents)

def load_data(text):
    if not text:
        return SketchData()
    try:
        return SketchData.from_dict(json.loads(text))
    except Exception:
        return SketchData()

def dump_data(data):
    return json.dumps(data.to_dict(), indent=2)
