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


"""Line-specific snap/highlight/preview policies.

These are placeholders for the next migration step.
"""

policy_line_2pts = {
    "snap_policy": "point_or_tangent",
    "highlight_policy": "contextual",
    "preview_policy": "line_from_points",
}

policy_line_parallel_ref_point = {
    "snap_policy": "point_or_tangent",
    "highlight_policy": "contextual",
    "preview_policy": "parallel_line_preview",
}

policy_line_perpendicular_ref_point = {
    "snap_policy": "point_or_tangent",
    "highlight_policy": "contextual",
    "preview_policy": "perpendicular_line_preview",
}
