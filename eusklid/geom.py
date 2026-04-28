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

from dataclasses import dataclass, field

@dataclass
class LineEntity2D:
    kind:str="line"
    origin:tuple=(0.0,0.0)
    direction:tuple=(1.0,0.0)
    construction:bool=True
    meta:dict=field(default_factory=dict)

    def to_dict(self):
        return {"kind":"line","origin":list(self.origin),"direction":list(self.direction),"construction":bool(self.construction),"meta":dict(self.meta)}

    @classmethod
    def from_dict(cls,d):
        return cls(origin=tuple(d["origin"]), direction=tuple(d["direction"]), construction=bool(d.get("construction",True)), meta=dict(d.get("meta",{})))

@dataclass
class CircleEntity2D:
    kind:str="circle"
    center:tuple=(0.0,0.0)
    radius:float=1.0
    construction:bool=True
    meta:dict=field(default_factory=dict)

    def to_dict(self):
        return {"kind":"circle","center":list(self.center),"radius":float(self.radius),"construction":bool(self.construction),"meta":dict(self.meta)}

    @classmethod
    def from_dict(cls,d):
        return cls(center=tuple(d["center"]), radius=float(d["radius"]), construction=bool(d.get("construction",True)), meta=dict(d.get("meta",{})))
