
from ..math2d import point_to_line_distance, normalize
from ..runtime import get_data
from ..geom import LineEntity2D

def pick_reference_line(scene_sketch_obj, uv, tol=10.0):
    best = None
    best_dist = None
    data = get_data(scene_sketch_obj)

    for ent in data.entities:
        if not isinstance(ent, LineEntity2D):
            continue
        d = point_to_line_distance(uv, ent.origin, ent.direction)
        if d <= tol and (best_dist is None or d < best_dist):
            best = {
                "kind": "line",
                "origin": tuple(ent.origin),
                "direction": normalize(tuple(ent.direction)),
            }
            best_dist = d

    for axis, origin, direction in [
        ("U", (0.0, 0.0), (1.0, 0.0)),
        ("V", (0.0, 0.0), (0.0, 1.0)),
    ]:
        d = point_to_line_distance(uv, origin, direction)
        if d <= tol and (best_dist is None or d < best_dist):
            best = {"kind": "axis", "axis": axis, "origin": origin, "direction": direction}
            best_dist = d

    return best

def compute_highlights(context, cursor_uv):
    if context.step.input_kind == "reference_line":
        ref = pick_reference_line(context.sketch_obj, cursor_uv)
        if ref is None:
            return []
        return [("line", ref["origin"], ref["direction"])]
    return []
