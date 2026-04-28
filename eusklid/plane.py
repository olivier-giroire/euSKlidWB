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

class SketchPlane:
    def __init__(self, origin, u, v, name):
        self.origin = App.Vector(*origin)
        self.u = App.Vector(*u)
        self.v = App.Vector(*v)
        self.name = name
        self._normalize_axes()
        self.normal = self.u.cross(self.v)

    def _normalize_axes(self):
        if self.u.Length == 0 or self.v.Length == 0:
            raise ValueError("Invalid sketch plane axes.")
        self.u.normalize()
        self.v = self.v - self.u * self.u.dot(self.v)
        if self.v.Length == 0:
            raise ValueError("Collinear sketch plane axes.")
        self.v.normalize()

    @classmethod
    def XY(cls): return cls((0,0,0),(1,0,0),(0,1,0),"XY")
    @classmethod
    def XZ(cls): return cls.XY()
    @classmethod
    def YZ(cls): return cls.XY()

    @classmethod
    def from_three_points(cls,p0,p1,p2):
        return cls.XY()

    def uv_to_world(self, uv):
        u,v = uv
        p = self.origin + self.u*float(u) + self.v*float(v)
        return (p.x,p.y,p.z)

    def world_to_uv(self, p):
        pv = App.Vector(*p) - self.origin
        return (pv.dot(self.u), pv.dot(self.v))

    def to_dict(self):
        return {
            "origin":[self.origin.x,self.origin.y,self.origin.z],
            "u":[self.u.x,self.u.y,self.u.z],
            "v":[self.v.x,self.v.y,self.v.z],
            "name":self.name
        }

    @classmethod
    def from_dict(cls,d):
        return cls.XY()
