
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
