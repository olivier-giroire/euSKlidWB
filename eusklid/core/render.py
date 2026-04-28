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

def render_highlight_line(plane, origin_uv, direction_uv):
    indicator.show_highlight_line(plane, origin_uv, direction_uv)

def render_highlight_circle(plane, center_uv, radius):
    indicator.show_highlight_circle(plane, center_uv, radius)

def render_snap_point(plane, uv, kind):
    indicator.show_snap_point(plane, uv, kind=kind)

def render_preview_line(plane, a_uv, b_uv):
    indicator.show_preview_line(plane, a_uv, b_uv)

def render_preview_circle(plane, center_uv, radius):
    indicator.show_preview_circle(plane, center_uv, radius)

def clear_render_layers():
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


def render_preview_polygon(plane, vertices_uv):
    indicator.show_preview_polygon(plane, vertices_uv)
