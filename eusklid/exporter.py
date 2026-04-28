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
import Part
from .feature import ensure_proxy, get_data
from .geom import LineEntity2D, CircleEntity2D
from .math2d import visible_segment_for_line

def export_to_native_sketch(sketch_obj,name="euSKlidExport"):
    doc=App.ActiveDocument
    sketch_obj=ensure_proxy(sketch_obj)
    data=get_data(sketch_obj)
    native=doc.addObject("Sketcher::SketchObject",name)
    native.MapMode="Deactivated"
    for ent in data.entities:
        if isinstance(ent,LineEntity2D):
            uv1,uv2=visible_segment_for_line(ent.origin,ent.direction,1000.0)
            p1=App.Vector(*data.plane.uv_to_world(uv1))
            p2=App.Vector(*data.plane.uv_to_world(uv2))
            native.addGeometry(Part.LineSegment(p1,p2), bool(ent.construction))
        elif isinstance(ent,CircleEntity2D):
            center=App.Vector(*data.plane.uv_to_world(ent.center))
            n=data.plane.normal
            native.addGeometry(Part.Circle(center,App.Vector(n.x,n.y,n.z),ent.radius), bool(ent.construction))
    doc.recompute()
    return native
