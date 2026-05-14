# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sketcher constraint emission for euSKlid path exports.

v5.2.1 policy: deliberately under-constrain rather than over-constrain, while
reducing repeated direction constraints by grouping segments that share the
same construction/support line. Support collinearity is expressed with one
Sketcher Tangent constraint instead of Parallel + PointOnObject. Arc smoothness
is added only when consecutive path elements have matching tangent directions.
Dimension / equality / pattern constraints are intentionally left out until
they can be emitted from explicit construction intent without creating
redundant constraints.
"""

import math

from .detect import (
    arc_sweep_length,
    are_collinear_segments,
    are_tangent_vectors,
    group_collinear_segments,
    group_same_circle_arcs,
    is_horizontal,
    is_vertical,
    same_circle_support,
    segment_dir,
    segment_length,
    tangent_vec_end,
    tangent_vec_start,
)
from .topology import (
    connected_junctions,
    endpoint_coincidence_pairs,
    arbitrary_center_symmetry_candidates,
    arbitrary_axis_symmetry_candidates,
    mirrored_endpoint_pairs_center_origin,
    mirrored_endpoint_pairs_x_axis,
    mirrored_endpoint_pairs_y_axis,
)
from ..core.config import get_config
from .user_intent import (
    normalize_overloads,
    validate_user_intents,
    forced_piece_pair_intents,
    forced_piece_pair_intents_expanded,
    forced_dimension_intents,
    has_intent_for_piece_pair,
    has_directional_user_intent,
)

try:
    from ..core import logging as elog
except Exception:  # pragma: no cover - FreeCAD runtime fallback
    elog = None


def _log(message):
    try:
        if elog is not None:
            elog.info(message)
    except Exception:
        pass


def _constraint_count(sk):
    try:
        return len(sk.Constraints)
    except Exception:
        return 0


def _remember_constraints_from(sk, before_count, out):
    try:
        after = len(sk.Constraints)
    except Exception:
        return
    for ci in range(int(before_count), int(after)):
        out.append(ci)


def _add_constraint_safe(sk, Sketcher, stats, exported_constraint_indices, *args):
    before_count = _constraint_count(sk)
    try:
        sk.addConstraint(Sketcher.Constraint(*args))
        _remember_constraints_from(sk, before_count, exported_constraint_indices)
        stats["added"] += 1
        return True
    except Exception as exc:
        stats["failed"] += 1
        _log("Export constraint skipped: %s %s" % (args, exc))
        return False


def _choose_collinear_reference(group):
    """Pick the support representative: longest segment, then first in path."""
    return max(
        group,
        key=lambda meta: (segment_length(meta), -int(meta.get("path_order", meta.get("index", 0)))),
    )




def _choose_circle_reference(group):
    """Pick the circle representative: longest arc sweep, then first in path."""
    return max(
        group,
        key=lambda meta: (arc_sweep_length(meta), -int(meta.get("path_order", meta.get("index", 0)))),
    )



def _endpoint_mirrored_y(meta, tol):
    """Return True when a segment's own endpoints are mirrored about Y.

    In that case a Horizontal constraint on the same segment is redundant: the
    Symmetric endpoint constraint already forces both endpoints to have the same
    Y coordinate.
    """
    try:
        a = meta.get("start")
        b = meta.get("end")
        if a is None or b is None:
            return False
        ax, ay = float(a[0]), float(a[1])
        bx, by = float(b[0]), float(b[1])
        return abs(ax + bx) <= tol and abs(ay - by) <= tol and ax * bx < 0
    except Exception:
        return False


def _endpoint_mirrored_x(meta, tol):
    """Return True when a segment's own endpoints are mirrored about X.

    In that case a Vertical constraint on the same segment is redundant: the
    Symmetric endpoint constraint already forces both endpoints to have the same
    X coordinate.
    """
    try:
        a = meta.get("start")
        b = meta.get("end")
        if a is None or b is None:
            return False
        ax, ay = float(a[0]), float(a[1])
        bx, by = float(b[0]), float(b[1])
        return abs(ax - bx) <= tol and abs(ay + by) <= tol and ay * by < 0
    except Exception:
        return False


def _group_has_symmetry_implied_horizontal(group, tol):
    return any(_endpoint_mirrored_y(meta, tol) for meta in group)


def _group_has_symmetry_implied_vertical(group, tol):
    return any(_endpoint_mirrored_x(meta, tol) for meta in group)


def _add_same_circle_to_reference(add_constraint_safe, child, ref):
    """Attach an arc fragment to the support circle of ``ref``.

    No numeric dimensions are emitted here.  The relation is expressed as:

    - Coincident arc centers;
    - Equal radius.

    In FreeCAD Sketcher point id 3 is the center of an arc/circle geometry.
    """
    ok_center = add_constraint_safe("Coincident", child["index"], 3, ref["index"], 3)
    ok_equal = add_constraint_safe("Equal", child["index"], ref["index"])
    return bool(ok_center or ok_equal)

def _add_collinearity_to_reference(add_constraint_safe, child, ref):
    """Constrain ``child`` to the infinite support of ``ref``.

    In FreeCAD Sketcher, line/line tangency is the most compact way to express
    collinearity for fragments sharing the same supporting construction line.
    This replaces the previous v3 pair:

        Parallel(child, ref) + PointOnObject(child endpoint, ref)

    with a single constraint:

        Tangent(child, ref)

    which is exactly the structural intent here and halves the constraint count
    for each non-reference fragment.
    """
    return add_constraint_safe("Tangent", child["index"], ref["index"])


def _add_parallel_to_reference(add_constraint_safe, child, ref):
    """Constrain two non-collinear segment directions to stay parallel."""
    return add_constraint_safe("Parallel", child["index"], ref["index"])


def _tangent_vec_at_endpoint(meta, point_id):
    """Return the local tangent vector at a Sketcher endpoint id."""
    try:
        pid = int(point_id)
    except Exception:
        pid = 0
    if pid == 1:
        return tangent_vec_start(meta)
    if pid == 2:
        return tangent_vec_end(meta)
    return (0.0, 0.0)



def _symmetry_point_key(meta, point):
    return (int(meta.get("index", 0)), int(point))


def _symmetry_pair_key(meta_a, point_a, meta_b, point_b):
    a = _symmetry_point_key(meta_a, point_a)
    b = _symmetry_point_key(meta_b, point_b)
    return tuple(sorted((a, b)))


def _axial_symmetry_y_enabled():
    try:
        cfg = get_config()
        return bool(cfg.get("export", {}).get("axial_symmetry_y", True))
    except Exception:
        return True


def _axial_symmetry_x_enabled():
    try:
        cfg = get_config()
        return bool(cfg.get("export", {}).get("axial_symmetry_x", True))
    except Exception:
        return True


def _central_symmetry_enabled():
    try:
        cfg = get_config()
        return bool(cfg.get("export", {}).get("central_symmetry", False))
    except Exception:
        return False


def _arbitrary_symmetry_centers_enabled():
    try:
        cfg = get_config()
        return bool(cfg.get("export", {}).get("arbitrary_symmetry_centers", False))
    except Exception:
        return False


def _arbitrary_symmetry_axes_enabled():
    try:
        cfg = get_config()
        return bool(cfg.get("export", {}).get("arbitrary_symmetry_axes", False))
    except Exception:
        return False


def _arbitrary_symmetry_min_score():
    try:
        cfg = get_config()
        return max(3, int(cfg.get("export", {}).get("symmetry_min_score", 4)))
    except Exception:
        return 4



def _desaturation_enabled():
    try:
        cfg = get_config()
        return bool(cfg.get("export", {}).get("reduce_redundant_constraints", False))
    except Exception:
        return False


def _constraint_kind(constraint):
    """Best-effort, FreeCAD-version tolerant constraint kind extraction."""
    for attr in ("Name", "Type", "TypeName"):
        try:
            val = getattr(constraint, attr, None)
            if val:
                return str(val)
        except Exception:
            pass
    try:
        text = repr(constraint)
    except Exception:
        text = str(constraint)
    known = (
        "Horizontal", "Vertical", "Tangent", "Equal", "Parallel",
        "Perpendicular", "Symmetric", "Coincident", "PointOnObject",
        "Lock", "DistanceX", "DistanceY", "Distance", "Radius", "Angle",
    )
    for name in known:
        if name in text:
            return name
    return text


def _constraint_try_priority(constraint):
    """Safe desaturation order.

    Lower values are tested first.  The v1.3.1 pass is intentionally
    conservative: it tries weak/reconstructible relation constraints and does
    not delete topology, locks, or dimensions.
    """
    kind = _constraint_kind(constraint)
    if "Horizontal" in kind or "Vertical" in kind:
        return 10
    if "Symmetric" in kind:
        # Symmetry is a useful global compression, but it must yield before
        # primitive construction intent such as tangency and parallelism.
        return 20
    if "Parallel" in kind or "Perpendicular" in kind:
        return 30
    if "Equal" in kind:
        return 40
    if "Tangent" in kind:
        return 50
    # Never desaturate anchors/topology/dimensions in safe mode.
    if any(name in kind for name in ("Coincident", "PointOnObject", "Lock", "Distance", "Radius", "Angle")):
        return None
    return None




def _constraint_aggressive_priority(constraint):
    """Aggressive local desaturation order for weak relation constraints.

    This pass is used after the DOF-safe pass.  It is intentionally limited to
    local relation constraints that FreeCAD often marks as partially redundant
    when global symmetries or equalities already imply them. Topology, locks,
    dimensions and symmetries remain protected here.
    """
    kind = _constraint_kind(constraint)
    if "Horizontal" in kind or "Vertical" in kind:
        return 10
    if "Parallel" in kind or "Perpendicular" in kind:
        return 20
    if "Tangent" in kind:
        return 30
    if "Equal" in kind:
        return 40
    return None


def _coincident_constraint_refs(constraint):
    """Return ((geo_a, point_a), (geo_b, point_b)) for a Coincident constraint."""
    try:
        if "Coincident" not in _constraint_kind(constraint):
            return None
        first = int(getattr(constraint, "First"))
        first_pos = int(getattr(constraint, "FirstPos"))
        second = int(getattr(constraint, "Second"))
        second_pos = int(getattr(constraint, "SecondPos"))
        if first < 0 or second < 0 or first_pos <= 0 or second_pos <= 0:
            return None
        return ((first, first_pos), (second, second_pos))
    except Exception:
        return None


def _solve_result_is_nonfatal(result):
    """Return True if a solve result is usable for an aggressive trial.

    FreeCAD may return negative integer codes (for example -2) while also
    reporting a partially redundant sketch in ReportView.  That is not a
    geometric failure for this pass; exceptions are treated as hard failure.
    """
    return not isinstance(result, Exception)


def _delete_constraint_safe(sk, index):
    for meth in ("delConstraint", "deleteConstraint", "removeConstraint"):
        try:
            fn = getattr(sk, meth, None)
            if callable(fn):
                fn(int(index))
                return True
        except Exception:
            pass
    return False


def _geometry_copy_safe(geom):
    try:
        return geom.copy()
    except Exception:
        return geom


def _geometry_snapshot(sk):
    try:
        return [_geometry_copy_safe(g) for g in list(sk.Geometry)]
    except Exception:
        return None


def _restore_geometry_snapshot(sk, snapshot):
    try:
        if snapshot is None:
            return False
        sk.Geometry = [_geometry_copy_safe(g) for g in list(snapshot)]
        return True
    except Exception:
        return False


def _vector_tuple(value):
    try:
        return (float(value.x), float(value.y), float(value.z))
    except Exception:
        pass
    try:
        return (float(value[0]), float(value[1]), float(value[2] if len(value) > 2 else 0.0))
    except Exception:
        return None


def _sketch_point_position(sk, geo_id, point_id):
    try:
        point = sk.getPoint(int(geo_id), int(point_id))
        pos = _vector_tuple(point)
        if pos is not None:
            return pos
    except Exception:
        pass

    try:
        geom = list(sk.Geometry)[int(geo_id)]
    except Exception:
        return None

    attr = None
    try:
        pid = int(point_id)
    except Exception:
        return None
    if pid == 1:
        attr = "StartPoint"
    elif pid == 2:
        attr = "EndPoint"
    elif pid == 3:
        attr = "Center"

    if attr is not None:
        try:
            pos = _vector_tuple(getattr(geom, attr))
            if pos is not None:
                return pos
        except Exception:
            pass

    try:
        pos = _vector_tuple(getattr(geom, "Location"))
        if pos is not None:
            return pos
    except Exception:
        pass
    return None


def _sketch_points_coincident(sk, ref_a, ref_b, tol=1e-6):
    try:
        pa = _sketch_point_position(sk, ref_a[0], ref_a[1])
        pb = _sketch_point_position(sk, ref_b[0], ref_b[1])
        if pa is None or pb is None:
            return False
        return (
            abs(float(pa[0]) - float(pb[0])) <= float(tol)
            and abs(float(pa[1]) - float(pb[1])) <= float(tol)
            and abs(float(pa[2]) - float(pb[2])) <= float(tol)
        )
    except Exception:
        return False


def _geometry_numeric_signature(geom):
    vals = []
    for attr in ("StartPoint", "EndPoint", "Center", "Location"):
        try:
            pt = _vector_tuple(getattr(geom, attr))
            if pt is not None:
                vals.extend(pt)
        except Exception:
            pass
    for attr in ("Radius", "MajorRadius", "MinorRadius", "FirstParameter", "LastParameter"):
        try:
            val = getattr(geom, attr)
            if val is not None:
                vals.append(float(val))
        except Exception:
            pass
    return tuple(vals)


def _geometry_snapshot_drift(before, after, tol=1e-6):
    try:
        if before is None or after is None:
            return 0.0
        before = list(before)
        after = list(after)
        n = min(len(before), len(after))
        drift = 0.0
        for i in range(n):
            sig_a = _geometry_numeric_signature(before[i])
            sig_b = _geometry_numeric_signature(after[i])
            m = min(len(sig_a), len(sig_b))
            for j in range(m):
                drift = max(drift, abs(float(sig_a[j]) - float(sig_b[j])))
            if len(sig_a) != len(sig_b):
                drift = max(drift, float("inf"))
        if len(before) != len(after):
            drift = max(drift, float("inf"))
        if drift <= float(tol):
            return 0.0
        return float(drift)
    except Exception:
        return 0.0


def _solve_sketch_for_desaturation(sk):
    try:
        return sk.solve()
    except Exception as exc:
        return exc


def _parse_dof_from_text(text):
    try:
        import re
        patterns = (
            r"degrees?\s+of\s+freedom\D+(-?\d+)",
            r"(-?\d+)\s+degrees?\s+of\s+freedom",
            r"DoF\D+(-?\d+)",
            r"dof\D+(-?\d+)",
        )
        for pat in patterns:
            m = re.search(pat, str(text), re.IGNORECASE)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return None




def _solver_diagnostic_text(sk, solve_result=None):
    """Collect solver messages in a FreeCAD-version tolerant way."""
    parts = []
    try:
        if solve_result is not None:
            parts.append(str(solve_result))
    except Exception:
        pass
    for name in (
        "SolverMessages", "SolverMessage", "SolveMessage", "SolveMessages",
        "SolveStatus", "SolverStatus", "Status",
    ):
        try:
            val = getattr(sk, name, None)
            if val is not None:
                parts.append(str(val))
        except Exception:
            pass
    return "\n".join(parts)


def _parse_redundant_constraint_indices(text):
    """Return current Sketcher constraint indices reported as redundant.

    FreeCAD messages usually look like:

        Sketch with redundant constraints
        Remove the following redundant constraint:
        25

    or may contain several indices.  We intentionally only parse numbers near
    the word "redundant" / "surnum" to avoid mistaking DOF counts for
    constraint ids.
    """
    try:
        import re
        src = str(text or "")
        if not re.search(r"redundant|surnum", src, re.IGNORECASE):
            return []
        out = []
        # Prefer the section following the relevant sentence.
        sections = re.split(r"(?:redundant|surnum)[^\n\r:]*:?", src, flags=re.IGNORECASE)
        candidates = sections[1:] if len(sections) > 1 else [src]
        for section in candidates:
            # Stop at common next-report sections to keep the parse local.
            section = re.split(r"(?:degrees?\s+of\s+freedom|DoF|under.?constrained|conflicting)", section, flags=re.IGNORECASE)[0]
            for m in re.finditer(r"(?<![-.\w])(\d+)(?![.\w])", section):
                idx = int(m.group(1))
                if idx not in out:
                    out.append(idx)
        return out
    except Exception:
        return []


def _parse_malformed_constraint_indices(text):
    """Return Sketcher constraint indices reported as malformed."""
    try:
        import re
        src = str(text or "")
        if not re.search(r"malformed|incorrecte|malform", src, re.IGNORECASE):
            return []
        out = []

        for m in re.finditer(r"constraint\s+(?:number\s+)?(\d+)\s+is\s+malformed", src, re.IGNORECASE):
            idx = int(m.group(1))
            if idx not in out:
                out.append(idx)

        sections = re.split(r"malformed[^:\n\r]*:?", src, flags=re.IGNORECASE)
        for section in sections[1:]:
            section = re.split(r"(?:degrees?\s+of\s+freedom|DoF|redundant|conflicting)", section, flags=re.IGNORECASE)[0]
            for m in re.finditer(r"(?<![-.\w])(\d+)(?![.\w])", section):
                idx = int(m.group(1))
                if idx not in out:
                    out.append(idx)
        return out
    except Exception:
        return []


def _malformed_constraint_indices(sk, solve_result=None):
    out = []
    try:
        out.extend(_parse_malformed_constraint_indices(_solver_diagnostic_text(sk, solve_result)))
    except Exception:
        pass

    for name in (
        "getMalformedConstraints", "getMalformedConstraintIndices",
        "malformedConstraints", "MalformedConstraints",
    ):
        try:
            val = getattr(sk, name, None)
            if callable(val):
                val = val()
            if val is None:
                continue
            if isinstance(val, (list, tuple, set)):
                for item in val:
                    try:
                        idx = int(item)
                        if idx not in out:
                            out.append(idx)
                    except Exception:
                        pass
            else:
                for idx in _parse_malformed_constraint_indices(val):
                    if idx not in out:
                        out.append(idx)
        except Exception:
            pass
    return out


def _get_solver_dof(sk, solve_result=None):
    """Return a best-effort DOF value or None if unavailable.

    FreeCAD versions differ here.  Some expose a method/property after solve;
    others return the DOF directly from solve().  We support all known shapes
    and fail closed when no DOF can be recovered.
    """
    for name in ("getDoF", "getDof", "getDegreesOfFreedom", "getSolverDoF"):
        try:
            fn = getattr(sk, name, None)
            if callable(fn):
                val = fn()
                if isinstance(val, (int, float)):
                    return int(val)
                parsed = _parse_dof_from_text(val)
                if parsed is not None:
                    return parsed
        except Exception:
            pass

    for name in ("DegreesOfFreedom", "DoF", "Dof", "SolverDegreesOfFreedom", "SolverDoF"):
        try:
            val = getattr(sk, name, None)
            if isinstance(val, (int, float)):
                return int(val)
            parsed = _parse_dof_from_text(val)
            if parsed is not None:
                return parsed
        except Exception:
            pass

    if isinstance(solve_result, dict):
        for key in ("dof", "DoF", "degrees_of_freedom", "DegreesOfFreedom"):
            if key in solve_result:
                try:
                    return int(solve_result[key])
                except Exception:
                    pass
    elif isinstance(solve_result, (tuple, list)):
        for val in solve_result:
            if isinstance(val, (int, float)):
                # Prefer explicit non-negative values from tuple/list results.
                if int(val) >= 0:
                    return int(val)
            parsed = _parse_dof_from_text(val)
            if parsed is not None:
                return parsed
    elif isinstance(solve_result, (int, float)):
        # SketchObject.solve() commonly returns the degrees of freedom in
        # Sketcher Python workflows.  Negative values are treated as failure.
        if int(solve_result) >= 0:
            return int(solve_result)
    else:
        parsed = _parse_dof_from_text(solve_result)
        if parsed is not None:
            return parsed

    for name in ("SolverMessages", "SolverMessage", "SolveStatus", "SolverStatus", "Status"):
        try:
            parsed = _parse_dof_from_text(getattr(sk, name, None))
            if parsed is not None:
                return parsed
        except Exception:
            pass
    return None


def _meta_point_refs_for_rigid_anchor(sk, geom_meta):
    refs = []
    for meta in geom_meta or []:
        try:
            idx = int(meta.get("index"))
        except Exception:
            continue
        for point_id in (1, 2, 3):
            pos = _sketch_point_position(sk, idx, point_id)
            if pos is None:
                continue
            duplicate = False
            for _ref, old_pos in refs:
                if (
                    abs(float(pos[0]) - float(old_pos[0])) <= 1e-7
                    and abs(float(pos[1]) - float(old_pos[1])) <= 1e-7
                    and abs(float(pos[2]) - float(old_pos[2])) <= 1e-7
                ):
                    duplicate = True
                    break
            if not duplicate:
                refs.append(((idx, int(point_id)), pos))
    return refs


def _try_add_temp_constraint(sk, Sketcher, args, added):
    try:
        before = _constraint_count(sk)
        sk.addConstraint(Sketcher.Constraint(*args))
        after = _constraint_count(sk)
        for ci in range(int(before), int(after)):
            added.append(int(ci))
        return after > before
    except Exception:
        return False


def _remove_temp_constraints(sk, before_count):
    try:
        for ci in range(_constraint_count(sk) - 1, int(before_count) - 1, -1):
            _delete_constraint_safe(sk, ci)
    except Exception:
        pass


def _diagnose_shape_constraint_state(sk, Sketcher, geom_meta):
    """Classify remaining DOF as shape-internal or placement-only.

    The export intentionally avoids absolute placement constraints.  To tell
    whether remaining DOF are only global translation/rotation, temporarily
    anchor two existing points at their current coordinates, solve, then remove
    those temporary constraints and restore geometry.
    """
    out = {
        "dof": None,
        "anchored_dof": None,
        "position_only": False,
        "status": "unknown",
    }
    before_count = _constraint_count(sk)
    before_geometry = _geometry_snapshot(sk)
    added = []

    try:
        base_result = _solve_sketch_for_desaturation(sk)
        if isinstance(base_result, Exception):
            out["status"] = "solve-failed"
            return out
        base_dof = _get_solver_dof(sk, base_result)
        out["dof"] = base_dof
        if base_dof is None:
            out["status"] = "no-dof"
            return out
        if int(base_dof) <= 0:
            out["anchored_dof"] = int(base_dof)
            out["status"] = "fully-constrained"
            return out

        refs = _meta_point_refs_for_rigid_anchor(sk, geom_meta)
        if len(refs) < 2:
            out["status"] = "not-enough-points"
            return out

        ref0, pos0 = refs[0]
        ref1 = pos1 = None
        for candidate_ref, candidate_pos in refs[1:]:
            dx = float(candidate_pos[0]) - float(pos0[0])
            dy = float(candidate_pos[1]) - float(pos0[1])
            if (dx * dx + dy * dy) > 1e-10:
                ref1, pos1 = candidate_ref, candidate_pos
                break
        if ref1 is None:
            out["status"] = "degenerate-points"
            return out

        _try_add_temp_constraint(sk, Sketcher, ("DistanceX", ref0[0], ref0[1], float(pos0[0])), added)
        _try_add_temp_constraint(sk, Sketcher, ("DistanceY", ref0[0], ref0[1], float(pos0[1])), added)

        dx = abs(float(pos1[0]) - float(pos0[0]))
        dy = abs(float(pos1[1]) - float(pos0[1]))
        if dx >= dy:
            _try_add_temp_constraint(sk, Sketcher, ("DistanceY", ref1[0], ref1[1], float(pos1[1])), added)
        else:
            _try_add_temp_constraint(sk, Sketcher, ("DistanceX", ref1[0], ref1[1], float(pos1[0])), added)

        if len(added) < 3:
            out["status"] = "anchor-failed"
            return out

        anchored_result = _solve_sketch_for_desaturation(sk)
        if isinstance(anchored_result, Exception):
            out["status"] = "anchor-solve-failed"
            return out
        anchored_dof = _get_solver_dof(sk, anchored_result)
        out["anchored_dof"] = anchored_dof
        if anchored_dof is None:
            out["status"] = "anchor-no-dof"
            return out

        if int(base_dof) <= 3 and int(anchored_dof) == 0:
            out["position_only"] = True
            out["status"] = "shape-constrained-placement-free"
        elif int(anchored_dof) == 0:
            out["status"] = "anchored-constrained-with-extra-dof"
        else:
            out["status"] = "shape-underconstrained"
        return out
    finally:
        _remove_temp_constraints(sk, before_count)
        _restore_geometry_snapshot(sk, before_geometry)
        try:
            _solve_sketch_for_desaturation(sk)
        except Exception:
            pass


def _find_constraint_index(sk, obj, obj_repr):
    try:
        constraints = list(sk.Constraints)
    except Exception:
        return None
    for idx, cur in enumerate(constraints):
        try:
            if cur is obj:
                return idx
        except Exception:
            pass
    # Fallback for FreeCAD wrappers that recreate Python objects.
    for idx, cur in enumerate(constraints):
        try:
            if repr(cur) == obj_repr:
                return idx
        except Exception:
            pass
    return None




def _constraint_debug_line(index, constraint):
    """Return a compact diagnostic line for one Sketcher constraint."""
    try:
        kind = _constraint_kind(constraint)
    except Exception:
        kind = "<?>"
    try:
        rep = repr(constraint)
    except Exception:
        try:
            rep = str(constraint)
        except Exception:
            rep = "<?>"
    return "%03d kind=%s repr=%s" % (int(index), kind, rep)


def _log_constraint_table(sk, title="constraint table"):
    """Log the current Sketcher constraint table for desaturation diagnostics."""
    try:
        constraints = list(sk.Constraints)
    except Exception as exc:
        _log("Desaturation diagnostic: cannot read constraints for %s: %s" % (title, exc))
        return
    _log("Desaturation diagnostic: %s count=%d" % (title, len(constraints)))
    for idx, constraint in enumerate(constraints):
        _log("Desaturation diagnostic: " + _constraint_debug_line(idx, constraint))


def _desaturate_export_constraints(sk, stats, exported_constraint_indices, protected_constraint_indices=None):
    """Remove redundant exported constraints using FreeCAD's solver as oracle.

    v1.3.6 safe policy:
    - disabled unless the Export setting is checked;
    - FreeCAD solver diagnostics are consumed when they are available;
    - the DOF-preserving pass is multi-pass: after each removal cycle, all
      eligible constraints are re-evaluated in the new solved state;
    - topology, point anchors, and dimensions remain protected.
    """
    stats["desaturation_enabled"] = 1 if _desaturation_enabled() else 0
    stats["desaturation_tried"] = 0
    stats["desaturation_removed"] = 0
    stats["desaturation_kept"] = 0
    stats["desaturation_skipped"] = 0
    stats["desaturation_no_dof"] = 0
    stats["desaturation_solver_reported"] = 0
    stats["desaturation_solver_removed"] = 0
    stats["desaturation_aggressive_tried"] = 0
    stats["desaturation_aggressive_removed"] = 0
    stats["desaturation_induced_coincident_tried"] = 0
    stats["desaturation_induced_coincident_removed"] = 0
    stats["desaturation_induced_coincident_kept"] = 0

    if not _desaturation_enabled():
        return []

    removed = []
    if exported_constraint_indices is None:
        exported_constraint_indices = []
    exported_constraint_index_set = set(int(i) for i in exported_constraint_indices)
    protected_constraint_indices = set(int(i) for i in (protected_constraint_indices or set()))

    def _shift_tracked_indices_after_delete(deleted_index, remove_deleted=True):
        """Keep export/protection index sets aligned with Sketcher reindexing."""
        try:
            deleted_index = int(deleted_index)
            updated_exported = set()
            for ci in exported_constraint_index_set:
                ci = int(ci)
                if ci == deleted_index:
                    if not remove_deleted:
                        updated_exported.add(ci)
                    continue
                updated_exported.add(ci - 1 if ci > deleted_index else ci)
            exported_constraint_index_set.clear()
            exported_constraint_index_set.update(updated_exported)

            updated_protected = set()
            for pi in protected_constraint_indices:
                pi = int(pi)
                if pi == deleted_index:
                    if not remove_deleted:
                        updated_protected.add(pi)
                    continue
                updated_protected.add(pi - 1 if pi > deleted_index else pi)
            protected_constraint_indices.clear()
            protected_constraint_indices.update(updated_protected)
        except Exception:
            pass

    def _record_restored_constraint(was_exported, was_protected=False):
        try:
            new_index = _constraint_count(sk) - 1
            if new_index < 0:
                return
            if was_exported:
                exported_constraint_index_set.add(int(new_index))
            if was_protected:
                protected_constraint_indices.add(int(new_index))
        except Exception:
            pass

    def _sync_exported_index_list():
        try:
            exported_constraint_indices[:] = sorted(exported_constraint_index_set)
        except Exception:
            pass

    base_result = _solve_sketch_for_desaturation(sk)
    if isinstance(base_result, Exception):
        _log("Desaturation skipped: initial solve failed: %s" % base_result)
        stats["desaturation_no_dof"] = 1
        _sync_exported_index_list()
        return removed

    try:
        _log("Desaturation diagnostic: solve_result_repr=%s type=%s" % (repr(base_result), type(base_result).__name__))
        diag_text = _solver_diagnostic_text(sk, base_result)
        _log("Desaturation diagnostic: solver_text=%s" % repr(diag_text))
        _log("Desaturation diagnostic: parsed_redundant_indices=%s" % _parse_redundant_constraint_indices(diag_text))
    except Exception as exc:
        _log("Desaturation diagnostic: cannot collect initial solver text: %s" % exc)

    _log_constraint_table(sk, "before solver-guided desaturation")

    # First honour explicit solver reports when FreeCAD exposes them to Python.
    # Some versions only print them to ReportView and sk.solve() returns -2; in
    # that case this loop simply does nothing and the DOF-safe pass below is the
    # effective desaturator.
    solver_report_rounds = 0
    while solver_report_rounds < 20:
        solver_report_rounds += 1
        diag_text = _solver_diagnostic_text(sk, base_result)
        reported = _parse_redundant_constraint_indices(diag_text)
        _log("Desaturation diagnostic: solver_round=%d reported=%s" % (solver_report_rounds, reported))
        if not reported:
            break

        removed_this_round = False
        stats["desaturation_solver_reported"] += len(reported)
        for current_index in reported:
            try:
                constraints_now = list(sk.Constraints)
            except Exception:
                constraints_now = []
            if current_index < 0 or current_index >= len(constraints_now):
                stats["desaturation_skipped"] += 1
                continue
            if int(current_index) not in exported_constraint_index_set:
                stats["desaturation_skipped"] += 1
                _log("Desaturation kept non-euSKlid constraint: index=%d" % current_index)
                continue
            if int(current_index) in protected_constraint_indices:
                stats["desaturation_skipped"] += 1
                _log("Desaturation kept overload-protected constraint: index=%d" % current_index)
                continue
            obj = constraints_now[current_index]
            prio = _constraint_try_priority(obj)
            kind = _constraint_kind(obj)
            if prio is None:
                stats["desaturation_skipped"] += 1
                _log("Desaturation kept solver-reported protected constraint: index=%d kind=%s" % (current_index, kind))
                continue
            if _delete_constraint_safe(sk, current_index):
                stats["desaturation_removed"] += 1
                stats["desaturation_solver_removed"] += 1
                _shift_tracked_indices_after_delete(current_index, remove_deleted=True)
                removed.append({"index": int(current_index), "kind": str(kind), "source": "solver-reported"})
                _log("Desaturation removed solver-reported redundant constraint: index=%d kind=%s" % (current_index, kind))
                base_result = _solve_sketch_for_desaturation(sk)
                if isinstance(base_result, Exception):
                    _log("Desaturation stopped after solver-reported removal; solve failed: %s" % base_result)
                    _sync_exported_index_list()
                    return removed
                removed_this_round = True
                break
            stats["desaturation_kept"] += 1
        if not removed_this_round:
            break

    base_dof = _get_solver_dof(sk, base_result)
    if base_dof is None:
        _log("Desaturation skipped DOF-preserving pass: cannot read solver DOF")
        stats["desaturation_no_dof"] = 1
        _sync_exported_index_list()
        return removed

    # v1.3.6: multi-pass DOF-safe removal.  We rebuild the candidate list after
    # each full pass because removing one constraint may make another one newly
    # redundant, and indexes shift after every deletion.
    max_passes = 12
    passes = 0
    while passes < max_passes:
        passes += 1
        try:
            constraints = list(sk.Constraints)
        except Exception:
            stats["desaturation_no_dof"] = 1
            break

        candidates = []
        for current_index, obj in enumerate(constraints):
            if int(current_index) not in exported_constraint_index_set:
                continue
            prio = _constraint_try_priority(obj)
            if prio is None:
                continue
            try:
                obj_repr = repr(obj)
            except Exception:
                obj_repr = str(obj)
            # Higher indexes first within a priority bucket reduce the amount of
            # reindexing that can affect not-yet-tested constraints in this pass.
            candidates.append((prio, -int(current_index), int(current_index), obj, obj_repr, _constraint_kind(obj)))

        candidates.sort()
        removed_in_pass = 0
        tried_in_pass = 0

        for _prio, _neg_index, original_index, obj, obj_repr, kind in candidates:
            current_index = _find_constraint_index(sk, obj, obj_repr)
            if current_index is None:
                stats["desaturation_skipped"] += 1
                continue
            if int(current_index) in protected_constraint_indices:
                stats["desaturation_skipped"] += 1
                continue

            stats["desaturation_tried"] += 1
            tried_in_pass += 1
            was_exported = int(current_index) in exported_constraint_index_set
            was_protected = int(current_index) in protected_constraint_indices
            if not _delete_constraint_safe(sk, current_index):
                stats["desaturation_kept"] += 1
                continue
            _shift_tracked_indices_after_delete(current_index, remove_deleted=True)

            result = _solve_sketch_for_desaturation(sk)
            dof = None if isinstance(result, Exception) else _get_solver_dof(sk, result)
            if dof is not None and dof == base_dof:
                stats["desaturation_removed"] += 1
                removed_in_pass += 1
                removed.append({"index": int(original_index), "kind": str(kind), "pass": int(passes)})
                _log("Desaturation removed constraint: pass=%d original_index=%d kind=%s dof=%d" % (passes, original_index, kind, base_dof))
                continue

            try:
                sk.addConstraint(obj)
                _record_restored_constraint(was_exported, was_protected)
                _solve_sketch_for_desaturation(sk)
            except Exception as exc:
                _log("Desaturation restore failed for original_index=%d kind=%s: %s" % (original_index, kind, exc))
            stats["desaturation_kept"] += 1

        _log("Desaturation pass %d: tried=%d removed=%d" % (passes, tried_in_pass, removed_in_pass))
        if removed_in_pass == 0:
            break

    # v1.3.7: aggressive local relation pass.  The DOF-safe pass above is
    # conservative and can miss FreeCAD's "partially redundant" local relations
    # when sk.solve() only returns a negative status code and does not expose
    # the reported index to Python.  This pass tries only weak local relation
    # constraints and accepts deletion when the solver remains non-fatal.  If a
    # valid DOF is available, it must still match the original DOF.
    aggressive_passes = 0
    max_aggressive_passes = 6
    while aggressive_passes < max_aggressive_passes:
        aggressive_passes += 1
        try:
            constraints = list(sk.Constraints)
        except Exception:
            break
        candidates = []
        for current_index, obj in enumerate(constraints):
            if int(current_index) not in exported_constraint_index_set:
                continue
            prio = _constraint_aggressive_priority(obj)
            if prio is None:
                continue
            try:
                obj_repr = repr(obj)
            except Exception:
                obj_repr = str(obj)
            candidates.append((prio, -int(current_index), int(current_index), obj, obj_repr, _constraint_kind(obj)))
        candidates.sort()
        removed_in_aggressive_pass = 0
        for _prio, _neg_index, original_index, obj, obj_repr, kind in candidates:
            current_index = _find_constraint_index(sk, obj, obj_repr)
            if current_index is None:
                continue
            if int(current_index) in protected_constraint_indices:
                continue
            stats["desaturation_aggressive_tried"] += 1
            was_exported = int(current_index) in exported_constraint_index_set
            was_protected = int(current_index) in protected_constraint_indices
            if not _delete_constraint_safe(sk, current_index):
                continue
            _shift_tracked_indices_after_delete(current_index, remove_deleted=True)
            result = _solve_sketch_for_desaturation(sk)
            dof = None if isinstance(result, Exception) else _get_solver_dof(sk, result)
            accept = False
            if _solve_result_is_nonfatal(result):
                if dof is None:
                    # Negative FreeCAD status codes often mean "redundant" but
                    # do not expose DOF.  Keep the deletion for weak local
                    # constraints and let subsequent passes converge.
                    accept = True
                elif dof == base_dof:
                    accept = True
            if accept:
                stats["desaturation_removed"] += 1
                stats["desaturation_aggressive_removed"] += 1
                removed_in_aggressive_pass += 1
                removed.append({"index": int(original_index), "kind": str(kind), "pass": int(passes), "source": "aggressive-local"})
                _log("Desaturation aggressive removed constraint: pass=%d original_index=%d kind=%s dof=%s" % (aggressive_passes, original_index, kind, str(dof)))
                continue
            try:
                sk.addConstraint(obj)
                _record_restored_constraint(was_exported, was_protected)
                _solve_sketch_for_desaturation(sk)
            except Exception as exc:
                _log("Desaturation aggressive restore failed for original_index=%d kind=%s: %s" % (original_index, kind, exc))
        _log("Desaturation aggressive pass %d: removed=%d" % (aggressive_passes, removed_in_aggressive_pass))
        if removed_in_aggressive_pass == 0:
            break

    # Final conservative topology pass.  A Coincident may be removed only when
    # it is proven induced by stronger remaining constraints: DOF must stay
    # stable, the solve must not move geometry, and the two referenced points
    # must still coincide.
    induced_passes = 0
    max_induced_passes = 4
    while induced_passes < max_induced_passes:
        induced_passes += 1
        try:
            constraints = list(sk.Constraints)
        except Exception:
            stats["desaturation_no_dof"] = 1
            break

        candidates = []
        for current_index, obj in enumerate(constraints):
            if int(current_index) not in exported_constraint_index_set:
                continue
            if int(current_index) in protected_constraint_indices:
                continue
            refs = _coincident_constraint_refs(obj)
            if refs is None:
                continue
            try:
                obj_repr = repr(obj)
            except Exception:
                obj_repr = str(obj)
            candidates.append((-int(current_index), int(current_index), obj, obj_repr, refs))

        candidates.sort()
        removed_in_induced_pass = 0
        for _neg_index, original_index, obj, obj_repr, refs in candidates:
            current_index = _find_constraint_index(sk, obj, obj_repr)
            if current_index is None:
                stats["desaturation_skipped"] += 1
                continue
            if int(current_index) in protected_constraint_indices:
                stats["desaturation_skipped"] += 1
                continue

            before_geometry = _geometry_snapshot(sk)
            stats["desaturation_induced_coincident_tried"] += 1
            was_exported = int(current_index) in exported_constraint_index_set
            was_protected = int(current_index) in protected_constraint_indices
            if not _delete_constraint_safe(sk, current_index):
                stats["desaturation_induced_coincident_kept"] += 1
                continue
            _shift_tracked_indices_after_delete(current_index, remove_deleted=True)

            result = _solve_sketch_for_desaturation(sk)
            dof = None if isinstance(result, Exception) else _get_solver_dof(sk, result)
            drift = _geometry_snapshot_drift(before_geometry, _geometry_snapshot(sk))
            still_coincident = _sketch_points_coincident(sk, refs[0], refs[1], tol=1e-6)
            if not isinstance(result, Exception) and dof == base_dof and drift == 0.0 and still_coincident:
                stats["desaturation_removed"] += 1
                stats["desaturation_induced_coincident_removed"] += 1
                removed_in_induced_pass += 1
                removed.append({
                    "index": int(original_index),
                    "kind": "Coincident",
                    "pass": int(induced_passes),
                    "source": "induced-topology",
                })
                _log("Desaturation removed induced Coincident: pass=%d original_index=%d" % (induced_passes, original_index))
                continue

            try:
                _restore_geometry_snapshot(sk, before_geometry)
                sk.addConstraint(obj)
                _record_restored_constraint(was_exported, was_protected)
                _solve_sketch_for_desaturation(sk)
            except Exception as exc:
                _log("Desaturation induced Coincident restore failed for original_index=%d: %s" % (original_index, exc))
            stats["desaturation_induced_coincident_kept"] += 1

        _log("Desaturation induced Coincident pass %d: removed=%d" % (induced_passes, removed_in_induced_pass))
        if removed_in_induced_pass == 0:
            break

    _log(
        "Desaturation v1.3.8 capped-arbitrary-center-pairs: aggressive_tried=%d aggressive_removed=%d induced_coincident_tried=%d induced_coincident_removed=%d induced_coincident_kept=%d"
        % (
            stats["desaturation_aggressive_tried"],
            stats["desaturation_aggressive_removed"],
            stats["desaturation_induced_coincident_tried"],
            stats["desaturation_induced_coincident_removed"],
            stats["desaturation_induced_coincident_kept"],
        )
    )

    _log(
        "Desaturation v1.3.7 solver-guided-multipass: enabled=%d dof=%s reported=%d solver_removed=%d tried=%d removed=%d kept=%d skipped=%d passes=%d"
        % (
            stats["desaturation_enabled"],
            str(base_dof),
            stats["desaturation_solver_reported"],
            stats["desaturation_solver_removed"],
            stats["desaturation_tried"],
            stats["desaturation_removed"],
            stats["desaturation_kept"],
            stats["desaturation_skipped"],
            passes,
        )
    )
    _sync_exported_index_list()
    return removed



def _try_add_constraint(sk, Sketcher, args):
    """Try to add a Sketcher constraint without touching export statistics.

    Used by locking helpers where several FreeCAD versions expose different
    overloads.  The caller decides whether a failed fallback is fatal.
    """
    try:
        sk.addConstraint(Sketcher.Constraint(*args))
        return True
    except Exception as exc:
        _log("Export lock fallback failed: %s %s" % (args, exc))
        return False


def _remember_last_constraint(sk, exported_constraint_indices):
    try:
        exported_constraint_indices.add(max(0, _constraint_count(sk) - 1))
    except Exception:
        pass


def _lock_point_geometry(sk, Sketcher, stats, exported_constraint_indices, geo_id, x, y):
    """Anchor a construction point using the best overload available.

    FreeCAD versions differ here: some accept Block/Lock on point geometry,
    while others require coordinate constraints.  Locking failure is non-fatal
    for export, but a successful anchor is tracked as protected by the
    desaturation pass.
    """
    candidates = (
        ("Block", int(geo_id)),
        ("Lock", int(geo_id)),
        ("DistanceX", int(geo_id), 1, float(x)),
        ("DistanceY", int(geo_id), 1, float(y)),
    )
    locked = False
    # Prefer a single Block/Lock if supported.
    for args in candidates[:2]:
        before = _constraint_count(sk)
        if _try_add_constraint(sk, Sketcher, args):
            _remember_constraints_from(sk, before, exported_constraint_indices)
            stats["added"] += 1
            return True
    # Fallback: coordinate constraints.  Both must succeed to really lock.
    ok = True
    for args in candidates[2:]:
        before = _constraint_count(sk)
        if _try_add_constraint(sk, Sketcher, args):
            _remember_constraints_from(sk, before, exported_constraint_indices)
            stats["added"] += 1
            locked = True
        else:
            ok = False
    return bool(locked and ok)


def _lock_line_geometry(sk, Sketcher, stats, exported_constraint_indices, geo_id):
    """Anchor a construction line/axis when the runtime supports it."""
    for args in (("Block", int(geo_id)), ("Lock", int(geo_id))):
        before = _constraint_count(sk)
        if _try_add_constraint(sk, Sketcher, args):
            _remember_constraints_from(sk, before, exported_constraint_indices)
            stats["added"] += 1
            return True
    return False

def _get_or_create_locked_origin_point(sk, Sketcher, stats, exported_constraint_indices):
    """Return a construction point at sketch origin for point symmetry.

    FreeCAD's Symmetric point/point/point overload needs an explicit center
    point.  The helper creates one construction point at (0, 0) and attempts to
    lock it there.  If the runtime rejects the construction or lock constraint,
    central symmetry is safely skipped by the caller.
    """
    try:
        cached = getattr(sk, "_eusklid_origin_point_index", None)
        if cached is not None:
            return int(cached)
    except Exception:
        pass

    try:
        import FreeCAD as App
        import Part
        idx = sk.addGeometry(Part.Point(App.Vector(0, 0, 0)), True)
        try:
            setattr(sk, "_eusklid_origin_point_index", int(idx))
        except Exception:
            pass
        # Lock keeps the construction point at the sketch origin.  The
        # FreeCAD Sketcher constructor accepts the compact ``Lock, geoId``
        # overload for point geometry; coordinates are already carried by the
        # construction point itself.
        _lock_point_geometry(sk, Sketcher, stats, exported_constraint_indices, int(idx), 0.0, 0.0)
        return int(idx)
    except Exception as exc:
        _log("Export central symmetry skipped: cannot create origin point: %s" % exc)
        return None


def _get_or_create_locked_arbitrary_center_point(sk, Sketcher, stats, exported_constraint_indices, cx, cy):
    """Create a locked construction point at an arbitrary symmetry center.

    The point is used as the third point of Sketcher ``Symmetric`` constraints.
    It is intentionally locked so the detected center remains an explicit
    construction reference instead of a free extra degree of freedom.
    """
    try:
        import FreeCAD as App
        import Part
        idx = sk.addGeometry(Part.Point(App.Vector(float(cx), float(cy), 0)), True)
        # Keep arbitrary symmetry centers explicit and stable.  The point is
        # created at the detected coordinates, then locked with the compact
        # FreeCAD overload.
        _lock_point_geometry(sk, Sketcher, stats, exported_constraint_indices, int(idx), float(cx), float(cy))
        return int(idx)
    except Exception as exc:
        _log("Export arbitrary symmetry center skipped: cannot create center point: %s" % exc)
        return None


def _sketch_bbox_span(geom_meta):
    xs = []
    ys = []
    for meta in geom_meta:
        for key in ("start", "end", "center"):
            pos = meta.get(key)
            if pos is None:
                continue
            try:
                xs.append(float(pos[0]))
                ys.append(float(pos[1]))
            except Exception:
                pass
    if not xs or not ys:
        return 10.0
    return max(max(xs) - min(xs), max(ys) - min(ys), 10.0)



def _sketch_bbox_extents(geom_meta):
    xs = []
    ys = []
    for meta in geom_meta:
        for key in ("start", "end", "center"):
            pos = meta.get(key)
            if pos is None:
                continue
            try:
                xs.append(float(pos[0]))
                ys.append(float(pos[1]))
            except Exception:
                pass
    if not xs or not ys:
        return (0.0, 0.0, 10.0, 10.0)
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    return (min_x, min_y, max(max_x - min_x, 1e-9), max(max_y - min_y, 1e-9))


def _point_position(meta, point_id):
    """Return the 2D position of a Sketcher point id from geometry metadata."""
    try:
        pid = int(point_id)
    except Exception:
        return None
    key = "start" if pid == 1 else "end" if pid == 2 else "center" if pid == 3 else None
    if key is None:
        return None
    pos = meta.get(key)
    if pos is None:
        return None
    try:
        return (float(pos[0]), float(pos[1]))
    except Exception:
        return None



def _point_role_weight(meta, point_id):
    """Return a stable local-priority score for a symmetry point.

    This is used only to order already-accepted arbitrary-center pairs before
    applying the emission cap.  It must stay conservative: it should prefer
    structural points (circle/arc centers, arc endpoints) without inventing new
    geometry semantics.
    """
    try:
        pid = int(point_id)
    except Exception:
        pid = 0
    try:
        kind = str(meta.get("kind", meta.get("type", ""))).lower()
    except Exception:
        kind = ""

    # Circle/arc centers are the strongest indicators for a meaningful
    # central symmetry.  In Sketcher point id 3 is the center for arcs/circles.
    if pid == 3:
        if kind in ("arc", "circle"):
            return 4.0
        return 3.0

    # Arc endpoints tend to be more structural than bare line endpoints because
    # they often represent raccord / support transitions.
    if kind in ("arc", "circle"):
        return 3.0

    if kind == "line":
        return 1.5

    return 1.0

def _arbitrary_axis_global_relevance(candidate, useful_pairs, geom_meta, min_score):
    """Reject arbitrary axes that are only local numerical coincidences.

    Arbitrary axes are powerful and visually invasive because they create a
    construction line.  A candidate should therefore explain a global structure,
    not just a few nearby endpoints.  This conservative filter keeps axes when
    their useful points are spatially dispersed along the axis or when they
    carry enough strong semantic pairs (arc/center relevance).
    """
    axis = candidate.get("axis", {}) or {}
    ux, uy = axis.get("direction", (1.0, 0.0))
    try:
        ux, uy = float(ux), float(uy)
        norm = (ux * ux + uy * uy) ** 0.5
        if norm <= 1e-12:
            return False, "degenerate", 0.0, 0.0, 0
        ux, uy = ux / norm, uy / norm
    except Exception:
        return False, "bad_axis", 0.0, 0.0, 0

    projections = []
    unique_points = set()
    strong_pairs = 0
    useful_weight = 0.0
    for meta_a, point_a, meta_b, point_b, relevance in useful_pairs:
        useful_weight += float(relevance)
        if float(relevance) >= 2.0:
            strong_pairs += 1
        for meta, point in ((meta_a, point_a), (meta_b, point_b)):
            key = _symmetry_point_key(meta, point)
            if key in unique_points:
                continue
            pos = _point_position(meta, point)
            if pos is None:
                continue
            unique_points.add(key)
            projections.append(pos[0] * ux + pos[1] * uy)

    if len(useful_pairs) < max(3, int(min_score)):
        return False, "below_score", 0.0, useful_weight, strong_pairs
    if len(projections) < 4:
        return False, "too_few_points", 0.0, useful_weight, strong_pairs

    span_along = max(projections) - min(projections)
    _min_x, _min_y, sx, sy = _sketch_bbox_extents(geom_meta)
    # Scale by the projection of the sketch bounding box on the axis direction.
    bbox_along = max(abs(ux) * sx + abs(uy) * sy, 1e-9)
    dispersion = float(span_along) / float(bbox_along)

    # A genuine arbitrary axis should cover a visible fraction of the sketch, or
    # explain several strong structural pairs (circle centers / arc junctions).
    if dispersion >= 0.28:
        return True, "dispersion", dispersion, useful_weight, strong_pairs
    if strong_pairs >= 2 and useful_weight >= max(float(min_score) * 1.7, 6.0):
        return True, "strong_pairs", dispersion, useful_weight, strong_pairs
    if len(useful_pairs) >= max(int(min_score) + 2, 6) and useful_weight >= float(min_score) * 2.0 and dispersion >= 0.18:
        return True, "dense", dispersion, useful_weight, strong_pairs
    return False, "local_axis", dispersion, useful_weight, strong_pairs



def _undirected_angle(dx, dy):
    """Return line direction angle in [0, pi)."""
    try:
        import math
        a = math.atan2(float(dy), float(dx))
        while a < 0.0:
            a += math.pi
        while a >= math.pi:
            a -= math.pi
        return a
    except Exception:
        return 0.0


def _angle_distance_pi(a, b):
    """Smallest distance between undirected angles in radians."""
    try:
        import math
        d = abs(float(a) - float(b)) % math.pi
        return min(d, math.pi - d)
    except Exception:
        return 0.0


def _axis_angle(axis):
    try:
        import math
        return 0.0 if axis == "horizontal" else math.pi / 2.0
    except Exception:
        return 0.0


def _compute_global_direction_profile(segments, angle_tol_rad=None):
    """Compute a coarse global direction profile for segment constraints.

    H/V constraints are local.  They become meaningful only when their
    direction participates in a global direction family.  This profile clusters
    segment support directions and uses total segment length as weight.
    """
    try:
        import math
        if angle_tol_rad is None:
            angle_tol_rad = math.radians(2.0)
    except Exception:
        angle_tol_rad = 0.035

    clusters = []
    h_weight = v_weight = 0.0
    h_count = v_count = 0

    for meta in segments:
        try:
            dx, dy = segment_dir(meta)
            length = max(float(segment_length(meta)), 1e-9)
            angle = _undirected_angle(dx, dy)
        except Exception:
            continue

        placed = False
        for cl in clusters:
            if _angle_distance_pi(angle, cl["angle"]) <= angle_tol_rad:
                old_weight = cl["weight"]
                new_weight = old_weight + length
                # Weighted circular mean is overkill for 2-degree buckets; this
                # stable approximation is sufficient for relevance scoring.
                cl["angle"] = (cl["angle"] * old_weight + angle * length) / new_weight
                cl["weight"] = new_weight
                cl["count"] += 1
                placed = True
                break
        if not placed:
            clusters.append({"angle": angle, "weight": length, "count": 1})

        if is_horizontal(dx, dy):
            h_weight += length
            h_count += 1
        if is_vertical(dx, dy):
            v_weight += length
            v_count += 1

    max_weight = max([cl["weight"] for cl in clusters] or [0.0])
    max_count = max([cl["count"] for cl in clusters] or [0])
    total_weight = sum(cl["weight"] for cl in clusters)
    return {
        "clusters": clusters,
        "max_weight": max_weight,
        "max_count": max_count,
        "total_weight": total_weight,
        "horizontal_weight": h_weight,
        "vertical_weight": v_weight,
        "horizontal_count": h_count,
        "vertical_count": v_count,
    }


def _parallel_direction_groups(segments, angle_tol_rad=None):
    """Group significant segment directions, regardless of support line."""
    try:
        if angle_tol_rad is None:
            angle_tol_rad = math.radians(2.0)
    except Exception:
        angle_tol_rad = 0.035

    groups = []
    for meta in segments:
        try:
            dx, dy = segment_dir(meta)
            length = float(segment_length(meta))
            if length <= 1e-9:
                continue
            angle = _undirected_angle(dx, dy)
        except Exception:
            continue

        placed = False
        for group in groups:
            if _angle_distance_pi(angle, group["angle"]) <= float(angle_tol_rad):
                old_weight = group["weight"]
                new_weight = old_weight + length
                group["angle"] = (group["angle"] * old_weight + angle * length) / new_weight
                group["weight"] = new_weight
                group["items"].append(meta)
                placed = True
                break
        if not placed:
            groups.append({"angle": angle, "weight": length, "items": [meta]})

    return [group["items"] for group in groups if len(group["items"]) >= 2]


def _source_mode(meta):
    try:
        return str((meta.get("source_meta") or {}).get("mode") or "")
    except Exception:
        return ""


def _strong_parallel_candidate(meta, max_length):
    try:
        mode = _source_mode(meta)
        if mode in {
            "parallel-ref-series",
            "point-angle-series",
            "line-2anchors-tangent",
            "parallel-tg-circle",
        }:
            return True
        length = float(segment_length(meta))
        return length >= max(1e-9, 0.35 * float(max_length))
    except Exception:
        return False


def _axis_direction_globally_relevant(profile, axis):
    """Return whether an H/V marker carries global intent.

    A horizontal/vertical hint is kept when that direction is part of a strong
    global direction family.  Isolated H/V fragments inside an oblique or
    rotated design are treated as local accidents and skipped.
    """
    try:
        weight = float(profile.get(axis + "_weight", 0.0))
        count = int(profile.get(axis + "_count", 0))
        max_weight = float(profile.get("max_weight", 0.0))
        max_count = int(profile.get("max_count", 0))
        total_weight = float(profile.get("total_weight", 0.0))
    except Exception:
        return True

    if count <= 0 or weight <= 0.0:
        return False
    if max_weight <= 0.0:
        return True

    # Strong family: comparable to the dominant direction.
    if weight >= 0.45 * max_weight:
        return True

    # Repeated family: many members, even if short.
    if count >= 3 and count >= max(2, int(0.65 * max_count)):
        return True

    # Large share of total geometry, useful on small orthogonal sketches.
    if total_weight > 0.0 and weight >= 0.25 * total_weight:
        return True

    return False


def _global_direction_score(profile, axis):
    try:
        weight = float(profile.get(axis + "_weight", 0.0))
        max_weight = float(profile.get("max_weight", 0.0))
        if max_weight <= 0.0:
            return 0.0
        return weight / max_weight
    except Exception:
        return 0.0

def _get_or_create_locked_arbitrary_axis_line(sk, Sketcher, stats, exported_constraint_indices, axis, geom_meta):
    """Create a locked construction line for an arbitrary symmetry axis."""
    try:
        import FreeCAD as App
        import Part
        px, py = axis.get("point", (0.0, 0.0))
        ux, uy = axis.get("direction", (1.0, 0.0))
        norm = (float(ux) ** 2 + float(uy) ** 2) ** 0.5
        if norm <= 1e-12:
            return None
        ux, uy = float(ux) / norm, float(uy) / norm
        half = max(_sketch_bbox_span(geom_meta) * 0.75, 5.0)
        p1 = App.Vector(float(px) - ux * half, float(py) - uy * half, 0)
        p2 = App.Vector(float(px) + ux * half, float(py) + uy * half, 0)
        idx = sk.addGeometry(Part.LineSegment(p1, p2), True)
        # Lock the construction axis so the detected mirror line stays an
        # explicit reference.  Compact Lock is accepted by recent Sketcher
        # builds for construction geometry; failure remains non-fatal.
        _lock_line_geometry(sk, Sketcher, stats, exported_constraint_indices, int(idx))
        return int(idx)
    except Exception as exc:
        _log("Export arbitrary symmetry axis skipped: cannot create axis line: %s" % exc)
        return None


def _add_central_symmetry_safe(sk, Sketcher, stats, exported_constraint_indices, meta_a, point_a, meta_b, point_b, origin_index):
    """Add point symmetry about the explicit locked origin construction point."""
    if origin_index is None:
        return False
    return _add_constraint_safe(
        sk,
        Sketcher,
        stats,
        exported_constraint_indices,
        "Symmetric",
        meta_a["index"],
        point_a,
        meta_b["index"],
        point_b,
        origin_index,
        1,
    )



def _distance2(a, b):
    try:
        return (float(a[0]) - float(b[0])) ** 2 + (float(a[1]) - float(b[1])) ** 2
    except Exception:
        return 1e100


def _meta_point_id_from_ref(meta, ref, tol=1e-5):
    """Map a user point ref to Sketcher point id 1/2/3 on a geometry meta."""
    if meta is None or ref is None:
        return None

    try:
        t = float((ref or {}).get("t", 0.5))
        if t <= 0.001:
            return 1
        if t >= 0.999:
            return 2
    except Exception:
        pass

    uv = (ref or {}).get("uv")
    if uv is None:
        return None

    candidates = []
    for pid in (1, 2, 3):
        pos = _point_position(meta, pid)
        if pos is not None:
            candidates.append((_distance2(pos, uv), pid))

    if not candidates:
        return None

    candidates.sort()
    best_d, best_pid = candidates[0]
    if best_d <= max(float(tol) * float(tol), 1e-10):
        return int(best_pid)

    # In practice UI refs come from the same Path geometry, so the nearest
    # endpoint is a better fallback than losing the forced user dimension.
    return int(best_pid)


def _segment_length_from_meta(meta):
    try:
        a = meta.get("start")
        b = meta.get("end")
        return math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))
    except Exception:
        try:
            return segment_length(meta)
        except Exception:
            return None


def _ref_position_from_meta(meta, ref):
    if meta is None or ref is None:
        return None
    try:
        uv = ref.get("uv")
        if uv is not None:
            return (float(uv[0]), float(uv[1]))
    except Exception:
        pass
    try:
        pid = _meta_point_id_from_ref(meta, ref)
        if pid is not None:
            return _point_position(meta, pid)
    except Exception:
        pass
    return None


def _dimension_value_from_refs(a_meta, a_ref, b_meta, b_ref):
    pa = _ref_position_from_meta(a_meta, a_ref)
    pb = _ref_position_from_meta(b_meta, b_ref)
    if pa is None or pb is None:
        return None
    try:
        return math.hypot(float(pb[0]) - float(pa[0]), float(pb[1]) - float(pa[1]))
    except Exception:
        return None


def _segment_support_distance_from_point(meta, point):
    try:
        a = meta.get("start")
        b = meta.get("end")
        px, py = float(point[0]), float(point[1])
        ax, ay = float(a[0]), float(a[1])
        bx, by = float(b[0]), float(b[1])
        vx, vy = bx - ax, by - ay
        den = math.hypot(vx, vy)
        if den <= 1e-12:
            return math.hypot(px - ax, py - ay)
        return abs((px - ax) * vy - (py - ay) * vx) / den
    except Exception:
        return None


def _segment_ref_position(meta, ref):
    try:
        uv = (ref or {}).get("uv")
        if uv is not None:
            return (float(uv[0]), float(uv[1]))
    except Exception:
        pass
    try:
        t = float((ref or {}).get("t", 0.5))
        a = meta.get("start")
        b = meta.get("end")
        return (
            float(a[0]) + (float(b[0]) - float(a[0])) * t,
            float(a[1]) + (float(b[1]) - float(a[1])) * t,
        )
    except Exception:
        return None


def _segment_unit_direction(meta):
    try:
        a = meta.get("start")
        b = meta.get("end")
        dx = float(b[0]) - float(a[0])
        dy = float(b[1]) - float(a[1])
        ln = math.hypot(dx, dy)
        if ln <= 1e-12:
            return None
        return (dx / ln, dy / ln)
    except Exception:
        return None


def _user_distance_value(a_meta, a_ref, a_kind, b_meta, b_ref, b_kind):
    """Return the numeric value matching the stored distance semantics."""
    if a_kind == "point" and b_kind == "point":
        return _dimension_value_from_refs(a_meta, a_ref, b_meta, b_ref)

    if a_kind == "segment" and b_kind == "point":
        point = _ref_position_from_meta(b_meta, b_ref)
        return _segment_support_distance_from_point(a_meta, point)

    if a_kind == "point" and b_kind == "segment":
        point = _ref_position_from_meta(a_meta, a_ref)
        return _segment_support_distance_from_point(b_meta, point)

    if a_kind == "segment" and b_kind == "segment":
        point = _segment_ref_position(a_meta, a_ref)
        if point is not None:
            return _segment_support_distance_from_point(b_meta, point)
        point = _segment_ref_position(b_meta, b_ref)
        return _segment_support_distance_from_point(a_meta, point)

    return _dimension_value_from_refs(a_meta, a_ref, b_meta, b_ref)


def _create_user_distance_ref_point(add_protected_constraint_safe, meta, ref, kind):
    """Create a construction point for a stored distance reference.

    Sketcher accepts several distance signatures that later solve as malformed.
    A construction point gives the user intent a stable point-point target.
    Segment references are attached to the selected segment with PointOnObject;
    endpoint references are coincident with the real endpoint when possible.
    """
    sk = getattr(add_protected_constraint_safe, "sketch", None)
    if sk is None or meta is None:
        return None

    pos = _ref_position_from_meta(meta, ref)
    if pos is None and str(kind) == "segment":
        pos = _segment_ref_position(meta, ref)
    if pos is None:
        return None

    try:
        import FreeCAD as App
        import Part
        idx = sk.addGeometry(Part.Point(App.Vector(float(pos[0]), float(pos[1]), 0)), True)
        idx = int(idx)
    except Exception as exc:
        _log("Export user distance reference point failed: %s" % exc)
        return None

    try:
        if str(kind) == "point":
            pid = _meta_point_id_from_ref(meta, ref)
            if pid is not None:
                add_protected_constraint_safe("Coincident", idx, 1, meta["index"], int(pid))
        elif str(kind) == "segment":
            add_protected_constraint_safe("PointOnObject", idx, 1, meta["index"])
    except Exception:
        pass

    return idx


def _try_protected_dimension_candidates(add_protected_constraint_safe, candidates):
    def _reject_added_constraint(sk, added_index, before_geometry, reason, args):
        try:
            if added_index is not None:
                _delete_constraint_safe(sk, added_index)
        except Exception:
            pass
        try:
            _restore_geometry_snapshot(sk, before_geometry)
        except Exception:
            pass
        try:
            indices = getattr(add_protected_constraint_safe, "exported_constraint_indices", None)
            if indices is not None and added_index is not None:
                indices[:] = [i for i in indices if int(i) != int(added_index)]
        except Exception:
            pass
        try:
            protected = getattr(add_protected_constraint_safe, "protected_constraint_indices", None)
            if protected is not None and added_index is not None:
                protected.discard(int(added_index))
        except Exception:
            pass
        try:
            stats = getattr(add_protected_constraint_safe, "stats", None)
            if stats is not None:
                stats["added"] = max(0, int(stats.get("added", 0)) - 1)
                stats["failed"] = int(stats.get("failed", 0)) + 1
                if reason == "geometry drift":
                    stats["user_forced_geometry_drift"] = int(stats.get("user_forced_geometry_drift", 0)) + 1
        except Exception:
            pass
        try:
            _log("Export user dimension candidate rejected (%s): %s" % (reason, args))
        except Exception:
            pass

    for args in candidates:
        try:
            sk = getattr(add_protected_constraint_safe, "sketch", None)
            before_geometry = _geometry_snapshot(sk) if sk is not None else None
            try:
                before_count = _constraint_count(sk)
            except Exception:
                before_count = None
            if add_protected_constraint_safe(*args):
                if sk is not None:
                    added_index = None
                    try:
                        after_count = _constraint_count(sk)
                        if before_count is not None and after_count > int(before_count):
                            added_index = int(after_count) - 1
                    except Exception:
                        added_index = None
                    solve_result = _solve_sketch_for_desaturation(sk)
                    malformed = _malformed_constraint_indices(sk, solve_result)
                    if added_index is not None and int(added_index) in set(int(i) for i in malformed):
                        _reject_added_constraint(sk, added_index, before_geometry, "malformed constraint", args)
                        continue

                    drift = _geometry_snapshot_drift(before_geometry, _geometry_snapshot(sk))
                    if drift > 0.0:
                        _reject_added_constraint(sk, added_index, before_geometry, "geometry drift", args)
                        continue
                try:
                    _log("Export user dimension emitted: %s" % (args,))
                except Exception:
                    pass
                return True
        except Exception as exc:
            try:
                _log("Export user dimension candidate failed: %s %s" % (args, exc))
            except Exception:
                pass
    return False


def _add_user_length_dimension(add_protected_constraint_safe, stats, piece_map, intent):
    """Emit a protected user length dimension where possible."""
    pieces = intent.get("pieces", []) or []

    # Prefer the explicit overload pieces.  If an older length overload stored
    # only range refs, use the first referenced piece.
    if not pieces:
        try:
            rng = intent.get("range", {}) or {}
            p = (rng.get("start") or {}).get("piece")
            if p is not None:
                pieces = [int(p)]
        except Exception:
            pieces = []

    if not pieces:
        stats["user_forced_skipped"] += 1
        stats["skipped_dimensions"] += 1
        return False

    # Preserve Length is intentionally a segment-length lock.  When a range
    # accidentally carries more than one piece, keep the first piece: the UI
    # path_tools side already normalizes the intended target segment.
    meta = piece_map.get(int(pieces[0]))
    if meta is None:
        stats["user_forced_skipped"] += 1
        stats["skipped_dimensions"] += 1
        return False

    value = _segment_length_from_meta(meta)
    if value is None:
        stats["user_forced_skipped"] += 1
        stats["skipped_dimensions"] += 1
        return False

    # FreeCAD versions differ on dimensional constructor signatures.  Try the
    # known compact line-length form first, then explicit endpoint forms.
    candidates = [
        ("Distance", meta["index"], float(value)),
        ("Distance", meta["index"], 1, meta["index"], 2, float(value)),
        ("Distance", meta["index"], 2, meta["index"], 1, float(value)),
    ]

    if _try_protected_dimension_candidates(add_protected_constraint_safe, candidates):
        stats["user_forced_length"] += 1
        return True

    stats["user_forced_skipped"] += 1
    stats["skipped_dimensions"] += 1
    return False


def _add_user_distance_dimension(add_protected_constraint_safe, stats, piece_map, intent):
    """Emit a protected user distance dimension from stored distance refs."""
    rng = intent.get("range", {}) or {}
    a_ref = rng.get("start") or {}
    b_ref = rng.get("end") or {}

    try:
        a_meta = piece_map.get(int(a_ref.get("piece")))
        b_meta = piece_map.get(int(b_ref.get("piece")))
    except Exception:
        a_meta = None
        b_meta = None

    if a_meta is None or b_meta is None:
        stats["user_forced_skipped"] += 1
        stats["skipped_dimensions"] += 1
        return False

    a_kind = str(a_ref.get("kind") or "segment")
    b_kind = str(b_ref.get("kind") or "segment")

    try:
        stored_value = rng.get("value")
        value = None if stored_value is None else abs(float(stored_value))
    except Exception:
        value = None
    if value is None:
        value = _user_distance_value(a_meta, a_ref, a_kind, b_meta, b_ref, b_kind)
    if value is None:
        stats["user_forced_skipped"] += 1
        stats["skipped_dimensions"] += 1
        return False

    candidates = []

    a_pid = _meta_point_id_from_ref(a_meta, a_ref)
    b_pid = _meta_point_id_from_ref(b_meta, b_ref)

    # Segment/segment means "normal distance between two parallel supports".
    # FreeCAD's GUI represents this without auxiliary geometry; the stable
    # Python form is point-on-first-line to second-line.  The direct line/line
    # Distance constructor creates malformed constraints in FreeCAD 1.1.
    if a_kind == "segment" and b_kind == "segment":
        a_dir = _segment_unit_direction(a_meta)
        b_dir = _segment_unit_direction(b_meta)
        parallel = False
        try:
            if a_dir is not None and b_dir is not None:
                cross = abs(float(a_dir[0]) * float(b_dir[1]) - float(a_dir[1]) * float(b_dir[0]))
                parallel = cross <= 1e-3
        except Exception:
            parallel = False
        if parallel:
            candidates.extend([
                ("Distance", a_meta["index"], 1, b_meta["index"], float(value)),
                ("Distance", a_meta["index"], 2, b_meta["index"], float(value)),
                ("Distance", b_meta["index"], 1, a_meta["index"], float(value)),
                ("Distance", b_meta["index"], 2, a_meta["index"], float(value)),
            ])

    # Point-based fallback. It avoids Sketcher line/point Distance overloads
    # that can be accepted by the constructor but later reported as malformed.
    if not (a_kind == "segment" and b_kind == "segment"):
        ref_a_idx = _create_user_distance_ref_point(add_protected_constraint_safe, a_meta, a_ref, a_kind)
        ref_b_idx = _create_user_distance_ref_point(add_protected_constraint_safe, b_meta, b_ref, b_kind)
        if ref_a_idx is not None and ref_b_idx is not None:
            candidates.extend([
                ("Distance", int(ref_a_idx), 1, int(ref_b_idx), 1, float(value)),
                ("Distance", int(ref_b_idx), 1, int(ref_a_idx), 1, float(value)),
            ])

    # Direct endpoint-to-endpoint fallback only.  Avoid the ambiguous line-based
    # overloads that produced malformed constraints in FreeCAD.
    if a_kind == "point" and b_kind == "point" and a_pid is not None and b_pid is not None:
        candidates.extend([
            ("Distance", a_meta["index"], int(a_pid), b_meta["index"], int(b_pid), float(value)),
            ("Distance", b_meta["index"], int(b_pid), a_meta["index"], int(a_pid), float(value)),
        ])

    if _try_protected_dimension_candidates(add_protected_constraint_safe, candidates):
        stats["user_forced_distance"] += 1
        return True

    try:
        _log(
            "Export user distance failed: kinds=%s/%s pieces=%s/%s value=%s candidates=%d"
            % (a_kind, b_kind, a_ref.get("piece"), b_ref.get("piece"), value, len(candidates))
        )
    except Exception:
        pass

    stats["user_forced_skipped"] += 1
    stats["skipped_dimensions"] += 1
    return False




def _angle_value_between_meta(a, b):
    try:
        a0 = _point_position(a, 1)
        a1 = _point_position(a, 2)
        b0 = _point_position(b, 1)
        b1 = _point_position(b, 2)

        if a0 is not None and a1 is not None and b0 is not None and b1 is not None:
            for pa, oa in ((a0, a1), (a1, a0)):
                for pb, ob in ((b0, b1), (b1, b0)):
                    if _distance2(pa, pb) <= 1e-12:
                        av = (float(oa[0]) - float(pa[0]), float(oa[1]) - float(pa[1]))
                        bv = (float(ob[0]) - float(pb[0]), float(ob[1]) - float(pb[1]))
                        la = math.hypot(av[0], av[1])
                        lb = math.hypot(bv[0], bv[1])
                        if la > 1e-9 and lb > 1e-9:
                            dot = max(-1.0, min(1.0, (av[0] * bv[0] + av[1] * bv[1]) / (la * lb)))
                            cross = max(-1.0, min(1.0, (av[0] * bv[1] - av[1] * bv[0]) / (la * lb)))
                            return _normalize_unsigned_angle_value(math.atan2(cross, dot))

        ax, ay = segment_dir(a)
        bx, by = segment_dir(b)
        dot = float(ax) * float(bx) + float(ay) * float(by)
        cross = float(ax) * float(by) - float(ay) * float(bx)
        return _normalize_unsigned_angle_value(math.atan2(cross, dot))
    except Exception:
        return None


def _normalize_unsigned_angle_value(value):
    try:
        value = float(value)
        if abs(value) > math.pi * 2.0:
            value = math.radians(value)
        value = abs(value) % (math.pi * 2.0)
        if value > math.pi:
            value = math.pi * 2.0 - value
        if value <= 1e-9:
            return None
        return float(value)
    except Exception:
        return None


def _stored_angle_value(intent):
    try:
        rng = intent.get("range") or {}
        value = rng.get("abs_value")
        if value is None:
            value = rng.get("value")
        if value is None:
            value = (intent.get("raw") or {}).get("value")
        if value is None:
            return None
        if float(value) > 0.0 and "abs_value" not in rng:
            # Legacy angle overloads stored only the unsigned magnitude.  Let
            # the geometry fallback recover a value from the selected pieces.
            return None
        return _normalize_unsigned_angle_value(value)
    except Exception:
        return None


def _add_user_angle_dimension(add_protected_constraint_safe, stats, piece_map, intent):
    """Emit a protected user angle constraint between two straight segments."""
    pair = intent.get("piece_pair")
    if pair is None:
        stats["user_forced_skipped"] += 1
        stats["skipped_dimensions"] += 1
        return False

    ordered_pieces = intent.get("pieces") or []
    if len(ordered_pieces) >= 2:
        try:
            pair = (int(ordered_pieces[0]), int(ordered_pieces[1]))
        except Exception:
            pass

    a = piece_map.get(int(pair[0]))
    b = piece_map.get(int(pair[1]))
    if a is None or b is None:
        stats["user_forced_skipped"] += 1
        stats["skipped_dimensions"] += 1
        return False

    value = _stored_angle_value(intent)
    if value is None:
        value = _angle_value_between_meta(a, b)
    if value is None:
        stats["user_forced_skipped"] += 1
        stats["skipped_dimensions"] += 1
        return False
    value = _normalize_unsigned_angle_value(value)
    if value is None:
        stats["user_forced_skipped"] += 1
        stats["skipped_dimensions"] += 1
        return False

    candidates = [
        ("Angle", a["index"], b["index"], float(value)),
        ("Angle", b["index"], a["index"], float(value)),
    ]

    # Endpoint-explicit fallbacks.  Some Sketcher versions require endpoints
    # for line/line angle constraints, especially for non-adjacent segments.
    for pa in (1, 2):
        for pb in (1, 2):
            candidates.append(("Angle", a["index"], pa, b["index"], pb, float(value)))
            candidates.append(("Angle", b["index"], pb, a["index"], pa, float(value)))

    if _try_protected_dimension_candidates(add_protected_constraint_safe, candidates):
        stats["user_forced_angle"] += 1
        return True

    stats["user_forced_skipped"] += 1
    stats["skipped_dimensions"] += 1
    try:
        _log("Export user angle failed for pair=%s value=%s candidates=%d" % (pair, value, len(candidates)))
    except Exception:
        pass
    return False


def _emit_user_intents_phase2(add_protected_constraint_safe, stats, geom_meta, user_intents):
    """Emit protected user intents in strict Phase 2 order.

    Order:
    1. tangences
    2. colinearities
    3. angles (diagnosed/reserved for future numeric angle emission)
    4. lengths
    5. distances
    """
    piece_map = {}
    for meta in geom_meta:
        try:
            piece_map[int(meta.get("piece_order"))] = meta
        except Exception:
            pass

    emitted_user_pairs = set()

    def emit_piece_pair_intents(kind):
        for intent, pair in forced_piece_pair_intents_expanded(user_intents, kinds={kind}):
            try:
                if pair in emitted_user_pairs:
                    continue
                a = piece_map.get(int(pair[0]))
                b = piece_map.get(int(pair[1]))
                if a is None or b is None:
                    stats["user_forced_skipped"] += 1
                    stats["skipped_relations"] += 1
                    continue

                emitted = False
                candidates = [
                    ("Tangent", a["index"], b["index"]),
                    ("Tangent", b["index"], a["index"]),
                ]

                for pa in (1, 2):
                    for pb in (1, 2):
                        candidates.append(("Tangent", a["index"], pa, b["index"], pb))

                for args in candidates:
                    if add_protected_constraint_safe(*args):
                        emitted = True
                        break

                if emitted:
                    emitted_user_pairs.add(pair)
                    if kind == "colinearity":
                        stats["user_forced_colinearity"] += 1
                    else:
                        stats["user_forced_tangent"] += 1
                else:
                    stats["user_forced_skipped"] += 1
                    stats["skipped_relations"] += 1
                    try:
                        _log("Export phase2 user %s failed for pair=%s candidates=%d" % (kind, pair, len(candidates)))
                    except Exception:
                        pass
            except Exception as exc:
                stats["user_forced_skipped"] += 1
                stats["skipped_relations"] += 1
                try:
                    _log("Export phase2 user %s skipped: %s" % (kind, exc))
                except Exception:
                    pass

    # 2.1 Tangences
    emit_piece_pair_intents("tangent")

    # 2.2 Colinearities
    emit_piece_pair_intents("colinearity")

    # 2.3 Angles
    for intent in user_intents:
        try:
            if intent.get("kind") == "angle":
                _add_user_angle_dimension(add_protected_constraint_safe, stats, piece_map, intent)
        except Exception as exc:
            stats["user_forced_skipped"] += 1
            stats["skipped_dimensions"] += 1
            try:
                _log("Export phase2 user angle skipped: %s" % exc)
            except Exception:
                pass

    # 2.4 Lengths
    for intent in forced_dimension_intents(user_intents):
        try:
            if intent.get("kind") == "length":
                _add_user_length_dimension(add_protected_constraint_safe, stats, piece_map, intent)
        except Exception as exc:
            stats["user_forced_skipped"] += 1
            stats["skipped_dimensions"] += 1
            try:
                _log("Export phase2 user length skipped: %s" % exc)
            except Exception:
                pass

    # 2.5 Distances
    for intent in forced_dimension_intents(user_intents):
        try:
            if intent.get("kind") == "distance":
                _add_user_distance_dimension(add_protected_constraint_safe, stats, piece_map, intent)
        except Exception as exc:
            stats["user_forced_skipped"] += 1
            stats["skipped_dimensions"] += 1
            try:
                _log("Export phase2 user distance skipped: %s" % exc)
            except Exception:
                pass

    return piece_map


def add_path_constraints(sk, Sketcher, geom_meta, tol_join, overloads=None):
    """Add minimal v5 path constraints to ``sk``.

    Export policy:
    1. all endpoint Coincident constraints, not only successive traversal junctions;
    2. group segments sharing the same infinite support;
       - one direction constraint on the representative if H/V;
       - other fragments constrained collinear to the representative;
    3. H/V only on non-grouped standalone segments;
    4. arc fragments sharing the same circle support;
       - center Coincident + Equal radius against one representative;
    5. obvious tangent continuity between neighbouring line/arc or arc/arc pairs.

    No numeric dimensions or pattern-spacing constraints are emitted in this
    pass.  Equal radius is relational and only used for arcs already detected
    as fragments of the same circle support.
    """

    stats = {
        "added": 0,
        "failed": 0,
        "skipped_dimensions": 0,
        "skipped_relations": 0,
        "collinear_groups": 0,
        "collinear_members": 0,
        "circle_groups": 0,
        "circle_members": 0,
        "symmetry_y": 0,
        "symmetry_x": 0,
        "symmetry_center": 0,
        "symmetry_y_disabled": 0,
        "symmetry_x_disabled": 0,
        "central_symmetry_disabled": 0,
        "symmetry_skipped_by_cluster": 0,
        "symmetry_skipped_by_primitive": 0,
        "hv_skipped_by_symmetry": 0,
        "hv_skipped_by_global_direction": 0,
        "primitive_tangencies": 0,
        "parallel_groups": 0,
        "parallel_links": 0,
        "global_horizontal_score": 0.0,
        "global_vertical_score": 0.0,
        "arbitrary_center_candidates": 0,
        "arbitrary_center_pairs": 0,
        "arbitrary_centers_disabled": 0,
        "arbitrary_center_selected": 0,
        "arbitrary_center_selected_pairs": 0,
        "arbitrary_center_skipped_by_competition": 0,
        "arbitrary_center_greedy_rounds": 0,
        "arbitrary_center_weighted_score": 0.0,
        "arbitrary_axis_candidates": 0,
        "arbitrary_axis_pairs": 0,
        "arbitrary_axis_selected": 0,
        "arbitrary_axis_selected_pairs": 0,
        "arbitrary_axis_skipped_by_competition": 0,
        "arbitrary_axis_greedy_rounds": 0,
        "arbitrary_axis_weighted_score": 0.0,
        "arbitrary_axis_skipped_by_global_structure": 0,
        "desaturation_enabled": 0,
        "desaturation_tried": 0,
        "desaturation_removed": 0,
        "desaturation_kept": 0,
        "desaturation_skipped": 0,
        "desaturation_no_dof": 0,
        "desaturation_solver_reported": 0,
        "desaturation_solver_removed": 0,
        "arbitrary_axes_disabled": 0,
        "shape_dof": -1,
        "shape_anchor_dof": -1,
        "shape_position_only": 0,
        "user_intents": 0,
        "user_intent_conflicts": 0,
        "user_intent_warnings": 0,
        "user_forced_tangent": 0,
        "user_forced_colinearity": 0,
        "user_forced_length": 0,
        "user_forced_distance": 0,
        "user_forced_angle": 0,
        "user_forced_skipped": 0,
        "user_forced_geometry_drift": 0,
        "auto_skipped_by_user_intent": 0,
    }
    exported_constraint_indices = []
    protected_constraint_indices = set()

    def add_constraint_safe(*args):
        return _add_constraint_safe(sk, Sketcher, stats, exported_constraint_indices, *args)

    def add_protected_constraint_safe(*args):
        before_count = _constraint_count(sk)
        ok = _add_constraint_safe(sk, Sketcher, stats, exported_constraint_indices, *args)
        if ok:
            try:
                after_count = _constraint_count(sk)
                for ci in range(int(before_count), int(after_count)):
                    protected_constraint_indices.add(int(ci))
            except Exception:
                pass
        return ok

    try:
        add_protected_constraint_safe.sketch = sk
        add_protected_constraint_safe.stats = stats
        add_protected_constraint_safe.exported_constraint_indices = exported_constraint_indices
        add_protected_constraint_safe.protected_constraint_indices = protected_constraint_indices
    except Exception:
        pass

    # Preserve path traversal index for deterministic tie-breaking.
    for order, meta in enumerate(geom_meta):
        try:
            meta.setdefault("path_order", order)
        except Exception:
            pass

    # 0) User intent normalization / validation.
    #
    # User overloads are not decorative: they are promoted to protected export
    # intentions.  They still have to be internally coherent; contradictory
    # user requests abort constraint emission before calculated constraints are
    # added.
    user_intents = normalize_overloads(overloads or [])
    stats["user_intents"] = len(user_intents)
    user_intent_report = validate_user_intents(user_intents)
    stats["user_intent_conflicts"] = len(user_intent_report.get("conflicts", []) or [])
    stats["user_intent_warnings"] = len(user_intent_report.get("warnings", []) or [])

    if not user_intent_report.get("ok", True):
        for reason in user_intent_report.get("conflicts", []) or []:
            _log("Export aborted: conflicting user intent: %s" % reason)
        stats["failed"] += stats["user_intent_conflicts"]
        return stats


    # 1) Topology: endpoint coincidences.  This is the mandatory family and
    # must never be reduced away by support-line or support-circle logic.
    # Use all geometric endpoint pairs, not only successive traversal
    # neighbours: outer circular supports can be exported as non-consecutive
    # fragments while still sharing real topological endpoints.
    endpoint_pairs = list(endpoint_coincidence_pairs(geom_meta, tol_join))
    for cur, cur_point, nxt, nxt_point in endpoint_pairs:
        add_constraint_safe("Coincident", cur["index"], cur_point, nxt["index"], nxt_point)


    # 2) User intentions, protected and emitted before calculated heuristics.
    #
    # Geometry first: tangences -> colinearities -> angles -> lengths -> distances.
    # These constraints seed the sketch before H/V, symmetry and calculated
    # relation heuristics, and are protected from desaturation.
    piece_map = _emit_user_intents_phase2(
        add_protected_constraint_safe,
        stats,
        geom_meta,
        user_intents,
    )


    # 2b) Primitive construction intent.  These are strong geometric relations
    # inferred directly from the drawn primitives, not optional global cleanup:
    # local smooth tangency and significant repeated segment directions.  Emit
    # them before automatic symmetry so symmetry cannot consume the same points
    # and freeze the sketch against local construction intent.
    junctions = list(connected_junctions(geom_meta, tol_join))
    segments = [meta for meta in geom_meta if meta.get("type") == "segment"]
    dist_tol = max(float(tol_join) * 0.25, 1e-6)
    # Points in this set are reserved from automatic symmetry.  Keep it narrow:
    # tangency is a local construction intent tied to a junction point, while
    # collinearity and parallelism are better protected by their own constraints
    # and can still benefit from a small amount of symmetry to propagate edits.
    primitive_relation_points = set()
    primitive_tangent_pairs = set()
    collinear_count = 0

    def reserve_tangent_cluster_points(*refs):
        positions = []
        for meta, point_id in refs:
            pos = meta.get("start") if int(point_id) == 1 else meta.get("end")
            if pos is not None:
                positions.append(pos)
        for meta in geom_meta:
            for point_id, key_name in ((1, "start"), (2, "end")):
                pos = meta.get(key_name)
                if pos is None:
                    continue
                for ref_pos in positions:
                    try:
                        if math.hypot(float(pos[0]) - float(ref_pos[0]), float(pos[1]) - float(ref_pos[1])) <= float(tol_join):
                            primitive_relation_points.add(_symmetry_point_key(meta, point_id))
                            break
                    except Exception:
                        pass

    def try_add_primitive_tangent(cur, cur_point, nxt, nxt_point):
        cur_type = cur.get("type")
        nxt_type = nxt.get("type")
        if "arc" not in {cur_type, nxt_type}:
            return False
        if cur_type not in {"segment", "arc"} or nxt_type not in {"segment", "arc"}:
            return False
        if not are_tangent_vectors(_tangent_vec_at_endpoint(cur, cur_point), _tangent_vec_at_endpoint(nxt, nxt_point)):
            return False
        if has_directional_user_intent(user_intents, cur, nxt):
            return False
        key = tuple(sorted((int(cur["index"]), int(nxt["index"]))))
        if key in primitive_tangent_pairs:
            reserve_tangent_cluster_points((cur, cur_point), (nxt, nxt_point))
            return False
        if add_protected_constraint_safe("Tangent", cur["index"], nxt["index"]):
            primitive_tangent_pairs.add(key)
            reserve_tangent_cluster_points((cur, cur_point), (nxt, nxt_point))
            stats["primitive_tangencies"] += 1
            return True
        return False

    for cur, cur_point, nxt, nxt_point in endpoint_pairs:
        try_add_primitive_tangent(cur, cur_point, nxt, nxt_point)

    for _i, cur, nxt in junctions:
        try_add_primitive_tangent(cur, 2, nxt, 1)

    groups = group_collinear_segments(segments, dist_tol=dist_tol)
    for group in groups:
        ref = _choose_collinear_reference(group)
        stats["collinear_groups"] += 1
        stats["collinear_members"] += len(group)

        emitted_for_group = 0
        for child in group:
            if child is ref:
                continue
            if has_directional_user_intent(user_intents, child, ref):
                stats["auto_skipped_by_user_intent"] += 1
                stats["skipped_relations"] += 1
                continue
            if _add_collinearity_to_reference(add_protected_constraint_safe, child, ref):
                collinear_count += 1
                emitted_for_group += 1

    for group in _parallel_direction_groups(segments):
        try:
            max_length = max(float(segment_length(meta)) for meta in group)
        except Exception:
            max_length = 0.0
        strong = [meta for meta in group if _strong_parallel_candidate(meta, max_length)]
        if len(strong) < 2:
            continue
        ref = _choose_collinear_reference(strong)
        emitted_for_group = 0
        for child in strong:
            if child is ref:
                continue
            try:
                if are_collinear_segments(child, ref, dist_tol=max(float(tol_join) * 0.25, 1e-6)):
                    continue
            except Exception:
                pass
            if has_directional_user_intent(user_intents, child, ref):
                continue
            if _add_parallel_to_reference(add_protected_constraint_safe, child, ref):
                emitted_for_group += 1
                stats["parallel_links"] += 1
        if emitted_for_group:
            stats["parallel_groups"] += 1


    # 3) Symmetry: conservative axis passes.  Work on endpoint clusters so
    # coincident duplicates do not all receive their own symmetry constraint.
    # In Sketcher, the horizontal and vertical sketch axes are addressed with
    # geometry ids -1 and -2 respectively.  If a FreeCAD version rejects that
    # form, the safe wrapper simply skips the constraint and logs the failure.
    symmetry_tol = max(float(tol_join), 1e-5)
    used_symmetry_pairs = set()
    used_symmetry_points = set()

    def mark_symmetry_pair(meta_a, point_a, meta_b, point_b):
        used_symmetry_pairs.add(_symmetry_pair_key(meta_a, point_a, meta_b, point_b))
        used_symmetry_points.add(_symmetry_point_key(meta_a, point_a))
        used_symmetry_points.add(_symmetry_point_key(meta_b, point_b))

    def symmetry_pair_blocked_by_primitive(meta_a, point_a, meta_b, point_b):
        return (
            _symmetry_point_key(meta_a, point_a) in primitive_relation_points
            or _symmetry_point_key(meta_b, point_b) in primitive_relation_points
        )

    def symmetry_pair_available(meta_a, point_a, meta_b, point_b):
        key = _symmetry_pair_key(meta_a, point_a, meta_b, point_b)
        if key in used_symmetry_pairs:
            return False
        if _symmetry_point_key(meta_a, point_a) in used_symmetry_points:
            return False
        if _symmetry_point_key(meta_b, point_b) in used_symmetry_points:
            return False
        if symmetry_pair_blocked_by_primitive(meta_a, point_a, meta_b, point_b):
            return False
        return True

    symmetry_y_count = 0
    if _axial_symmetry_y_enabled():
        for left, left_point, right, right_point in mirrored_endpoint_pairs_y_axis(geom_meta, symmetry_tol):
            if not symmetry_pair_available(left, left_point, right, right_point):
                if symmetry_pair_blocked_by_primitive(left, left_point, right, right_point):
                    stats["symmetry_skipped_by_primitive"] += 1
                else:
                    stats["symmetry_skipped_by_cluster"] += 1
                stats["skipped_relations"] += 1
                continue
            if add_constraint_safe("Symmetric", left["index"], left_point, right["index"], right_point, -2):
                symmetry_y_count += 1
                stats["symmetry_y"] += 1
                mark_symmetry_pair(left, left_point, right, right_point)
    else:
        stats["symmetry_y_disabled"] = len(list(mirrored_endpoint_pairs_y_axis(geom_meta, symmetry_tol)))

    symmetry_x_count = 0
    if _axial_symmetry_x_enabled():
        for top, top_point, bottom, bottom_point in mirrored_endpoint_pairs_x_axis(geom_meta, symmetry_tol):
            if not symmetry_pair_available(top, top_point, bottom, bottom_point):
                if symmetry_pair_blocked_by_primitive(top, top_point, bottom, bottom_point):
                    stats["symmetry_skipped_by_primitive"] += 1
                else:
                    stats["symmetry_skipped_by_cluster"] += 1
                stats["skipped_relations"] += 1
                continue
            if add_constraint_safe("Symmetric", top["index"], top_point, bottom["index"], bottom_point, -1):
                symmetry_x_count += 1
                stats["symmetry_x"] += 1
                mark_symmetry_pair(top, top_point, bottom, bottom_point)
    else:
        stats["symmetry_x_disabled"] = len(list(mirrored_endpoint_pairs_x_axis(geom_meta, symmetry_tol)))

    symmetry_center_count = 0
    if _central_symmetry_enabled():
        origin_index = None
        for a, a_point, b, b_point in mirrored_endpoint_pairs_center_origin(geom_meta, symmetry_tol):
            if not symmetry_pair_available(a, a_point, b, b_point):
                if symmetry_pair_blocked_by_primitive(a, a_point, b, b_point):
                    stats["symmetry_skipped_by_primitive"] += 1
                else:
                    stats["symmetry_skipped_by_cluster"] += 1
                stats["skipped_relations"] += 1
                continue
            if origin_index is None:
                origin_index = _get_or_create_locked_origin_point(sk, Sketcher, stats, exported_constraint_indices)
                if origin_index is None:
                    break
            if _add_central_symmetry_safe(sk, Sketcher, stats, exported_constraint_indices, a, a_point, b, b_point, origin_index):
                symmetry_center_count += 1
                stats["symmetry_center"] += 1
                mark_symmetry_pair(a, a_point, b, b_point)
    else:
        stats["central_symmetry_disabled"] = len(list(mirrored_endpoint_pairs_center_origin(geom_meta, symmetry_tol)))

    # 1c) v6.5.2 arbitrary symmetry axes.
    #
    # In practical CAD usage, axial symmetries are generally more structural
    # than central symmetries.  Arbitrary axes are therefore selected before
    # arbitrary centers and consume the same residual symmetry budget.
    min_sym_score = _arbitrary_symmetry_min_score()
    #
    # Axes are detected as perpendicular bisectors of relevant point pairs.
    # They are selected after axial/origin/arbitrary-center symmetries and use
    # the same residual greedy budget: a point already consumed by a stronger
    # symmetry family cannot be reused by an arbitrary axis.
    arbitrary_axis_constraint_count = 0

    def useful_pairs_for_axis_candidate(candidate):
        useful = []
        for item in candidate.get("pairs", []):
            if len(item) >= 3:
                node_a, node_b, relevance = item[:3]
            else:
                node_a, node_b = item[:2]
                relevance = 1.0
            _kind_a, _ax, _ay, rep_a = node_a[:4]
            _kind_b, _bx, _by, rep_b = node_b[:4]
            _order_a, meta_a, point_a, _pos_a = rep_a
            _order_b, meta_b, point_b, _pos_b = rep_b
            if symmetry_pair_available(meta_a, point_a, meta_b, point_b):
                useful.append((meta_a, point_a, meta_b, point_b, float(relevance)))
        return useful

    if _arbitrary_symmetry_axes_enabled():
        remaining_axis_candidates = list(arbitrary_axis_symmetry_candidates(geom_meta, symmetry_tol, min_sym_score))
        stats["arbitrary_axis_candidates"] = len(remaining_axis_candidates)
        stats["arbitrary_axis_pairs"] = sum(int(c.get("score", 0)) for c in remaining_axis_candidates)

        while remaining_axis_candidates:
            scored = []
            for idx, candidate in enumerate(remaining_axis_candidates):
                useful_pairs = useful_pairs_for_axis_candidate(candidate)
                useful_score = len(useful_pairs)
                useful_weight = sum(float(p[4]) for p in useful_pairs)
                raw_score = int(candidate.get("score", 0))
                raw_pairs = int(candidate.get("raw_pairs", 0))
                weighted_score = float(candidate.get("weighted_score", raw_score))
                axis = candidate.get("axis", {})
                px, py = axis.get("point", (0.0, 0.0))
                ux, uy = axis.get("direction", (1.0, 0.0))
                relevant, relevance_reason, axis_dispersion, axis_useful_weight, axis_strong_pairs = _arbitrary_axis_global_relevance(
                    candidate, useful_pairs, geom_meta, min_sym_score
                )
                _log(
                    "Export arbitrary symmetry axis candidate: point=(%.6g, %.6g) dir=(%.6g, %.6g) score=%d weighted=%.2f raw_pairs=%d useful=%d useful_weight=%.2f dispersion=%.3f strong_pairs=%d relevant=%d reason=%s"
                    % (
                        float(px), float(py), float(ux), float(uy), raw_score, weighted_score, raw_pairs,
                        useful_score, useful_weight, float(axis_dispersion), int(axis_strong_pairs),
                        1 if relevant else 0, str(relevance_reason),
                    )
                )
                if useful_score >= min_sym_score and relevant:
                    scored.append((useful_weight, useful_score, weighted_score, raw_score, -idx, idx, candidate, useful_pairs))
                elif useful_score >= min_sym_score and not relevant:
                    stats["arbitrary_axis_skipped_by_global_structure"] += 1

            if not scored:
                stats["arbitrary_axis_skipped_by_competition"] += len(remaining_axis_candidates)
                break

            scored.sort(reverse=True)
            useful_weight, useful_score, weighted_score, raw_score, _neg_idx, idx, candidate, useful_pairs = scored[0]
            axis = candidate.get("axis", {})
            axis_index = _get_or_create_locked_arbitrary_axis_line(
                sk, Sketcher, stats, exported_constraint_indices, axis, geom_meta
            )
            if axis_index is None:
                remaining_axis_candidates.pop(idx)
                stats["arbitrary_axis_skipped_by_competition"] += 1
                continue

            kept_for_axis = 0
            kept_weight = 0.0
            for meta_a, point_a, meta_b, point_b, relevance in useful_pairs:
                if not symmetry_pair_available(meta_a, point_a, meta_b, point_b):
                    if symmetry_pair_blocked_by_primitive(meta_a, point_a, meta_b, point_b):
                        stats["symmetry_skipped_by_primitive"] += 1
                    else:
                        stats["symmetry_skipped_by_cluster"] += 1
                    stats["skipped_relations"] += 1
                    continue
                if add_constraint_safe("Symmetric", meta_a["index"], point_a, meta_b["index"], point_b, axis_index):
                    arbitrary_axis_constraint_count += 1
                    kept_for_axis += 1
                    kept_weight += float(relevance)
                    mark_symmetry_pair(meta_a, point_a, meta_b, point_b)

            if kept_for_axis > 0:
                stats["arbitrary_axis_selected"] += 1
                stats["arbitrary_axis_selected_pairs"] += kept_for_axis
                stats["arbitrary_axis_greedy_rounds"] += 1
                stats["arbitrary_axis_weighted_score"] += float(kept_weight)
                px, py = axis.get("point", (0.0, 0.0))
                ux, uy = axis.get("direction", (1.0, 0.0))
                _log(
                    "Export arbitrary symmetry axis selected: point=(%.6g, %.6g) dir=(%.6g, %.6g) useful=%d useful_weight=%.2f raw_score=%d weighted=%.2f kept=%d"
                    % (float(px), float(py), float(ux), float(uy), useful_score, kept_weight, raw_score, weighted_score, kept_for_axis)
                )
            else:
                px, py = axis.get("point", (0.0, 0.0))
                _log("Export arbitrary symmetry axis emitted no constraints: point=(%.6g, %.6g)" % (float(px), float(py)))

            remaining_axis_candidates.pop(idx)
    else:
        stats["arbitrary_axes_disabled"] = 1

    # 1d) v6.5.2 arbitrary central symmetry candidates.
    #
    # v6.4c processed candidates in their raw detection order.  That was good
    # enough to prove emission, but it could still pick a high raw-score center
    # whose useful pairs had already been mostly consumed by axial/origin
    # symmetries, before a lower raw-score candidate with more remaining useful
    # pairs.  v6.4d turns this into a residual greedy selection:
    #
    #   1. compute useful pairs against the symmetry state already emitted
    #      by Y/X/origin passes;
    #   2. select the candidate with the highest useful score;
    #   3. emit it and mark its points as consumed;
    #   4. recompute the useful scores of the remaining candidates;
    #   5. stop when no candidate still reaches the configured threshold.
    #
    # This is still intentionally simple, but it makes arbitrary centers
    # cooperate with the global symmetry budget instead of competing blindly.
    arbitrary_center_constraint_count = 0

    def useful_pairs_for_candidate(candidate):
        useful = []
        for item in candidate.get("pairs", []):
            # v6.4e stores semantic relevance as the third tuple item while
            # remaining backward-compatible with v6.4d two-item pairs.
            if len(item) >= 3:
                node_a, node_b, relevance = item[:3]
            else:
                node_a, node_b = item[:2]
                relevance = 1.0
            _kind_a, _ax, _ay, rep_a = node_a[:4]
            _kind_b, _bx, _by, rep_b = node_b[:4]
            _order_a, meta_a, point_a, _pos_a = rep_a
            _order_b, meta_b, point_b, _pos_b = rep_b
            if symmetry_pair_available(meta_a, point_a, meta_b, point_b):
                useful.append((meta_a, point_a, meta_b, point_b, float(relevance)))
        return useful

    if _arbitrary_symmetry_centers_enabled():
        # If explicit origin central symmetry is disabled, (0,0) must remain a
        # valid arbitrary-center candidate.  Disabling the dedicated mode means
        # "do not force origin symmetry through the specialized pass", not
        # "ban the origin from arbitrary detection".
        remaining_candidates = list(arbitrary_center_symmetry_candidates(
            geom_meta, symmetry_tol, min_sym_score, include_origin=not _central_symmetry_enabled()
        ))
        stats["arbitrary_center_candidates"] = len(remaining_candidates)
        stats["arbitrary_center_pairs"] = sum(int(c.get("score", 0)) for c in remaining_candidates)

        while remaining_candidates:
            scored = []
            for idx, candidate in enumerate(remaining_candidates):
                useful_pairs = useful_pairs_for_candidate(candidate)
                useful_score = len(useful_pairs)
                useful_weight = sum(float(p[4]) for p in useful_pairs)
                raw_score = int(candidate.get("score", 0))
                raw_pairs = int(candidate.get("raw_pairs", 0))
                weighted_score = float(candidate.get("weighted_score", raw_score))
                cx, cy = candidate.get("center", (0.0, 0.0))
                _log(
                    "Export arbitrary symmetry center candidate: center=(%.6g, %.6g) score=%d weighted=%.2f raw_pairs=%d useful=%d useful_weight=%.2f"
                    % (float(cx), float(cy), raw_score, weighted_score, raw_pairs, useful_score, useful_weight)
                )
                if useful_score >= min_sym_score:
                    # Primary ranking is semantic relevance, not raw count.
                    scored.append((useful_weight, useful_score, weighted_score, raw_score, -idx, idx, candidate, useful_pairs))

            if not scored:
                # Every remaining center has become redundant with symmetries
                # already emitted or with higher-ranked arbitrary centers.
                stats["arbitrary_center_skipped_by_competition"] += len(remaining_candidates)
                break

            scored.sort(reverse=True)
            useful_weight, useful_score, weighted_score, raw_score, _neg_idx, idx, candidate, useful_pairs = scored[0]
            cx, cy = candidate.get("center", (0.0, 0.0))
            center_index = _get_or_create_locked_arbitrary_center_point(
                sk, Sketcher, stats, exported_constraint_indices, cx, cy
            )
            if center_index is None:
                remaining_candidates.pop(idx)
                stats["arbitrary_center_skipped_by_competition"] += 1
                continue

            # v1.3.8: arbitrary-center detection can legitimately find many
            # compatible pairs for the same center.  Emitting all of them often
            # creates a saturated sketch, because once the center is locked a
            # small set of high-quality pairs usually carries the intention.
            # Keep only the best local pairs, capped by the configured minimum
            # score.  The minimum score is therefore both the acceptance
            # threshold and the initial emission budget.
            useful_pairs_to_emit = sorted(
                useful_pairs,
                key=lambda item: (float(item[4]), _point_role_weight(item[0], item[1]) + _point_role_weight(item[2], item[3])),
                reverse=True,
            )[:max(1, int(min_sym_score))]

            kept_for_center = 0
            kept_weight = 0.0
            for meta_a, point_a, meta_b, point_b, relevance in useful_pairs_to_emit:
                # Re-check availability because each emitted pair marks its
                # endpoints.  This protects the greedy pass from stale scores.
                if not symmetry_pair_available(meta_a, point_a, meta_b, point_b):
                    if symmetry_pair_blocked_by_primitive(meta_a, point_a, meta_b, point_b):
                        stats["symmetry_skipped_by_primitive"] += 1
                    else:
                        stats["symmetry_skipped_by_cluster"] += 1
                    stats["skipped_relations"] += 1
                    continue
                if _add_central_symmetry_safe(
                    sk, Sketcher, stats, exported_constraint_indices,
                    meta_a, point_a, meta_b, point_b, center_index
                ):
                    arbitrary_center_constraint_count += 1
                    kept_for_center += 1
                    kept_weight += float(relevance)
                    mark_symmetry_pair(meta_a, point_a, meta_b, point_b)

            if kept_for_center > 0:
                stats["arbitrary_center_selected"] += 1
                stats["arbitrary_center_selected_pairs"] += kept_for_center
                stats["arbitrary_center_greedy_rounds"] += 1
                stats["arbitrary_center_weighted_score"] += float(kept_weight)
                _log(
                    "Export arbitrary symmetry center selected: center=(%.6g, %.6g) useful=%d useful_weight=%.2f raw_score=%d weighted=%.2f kept=%d"
                    % (float(cx), float(cy), useful_score, kept_weight, raw_score, weighted_score, kept_for_center)
                )
            else:
                _log(
                    "Export arbitrary symmetry center emitted no constraints: center=(%.6g, %.6g)"
                    % (float(cx), float(cy))
                )

            remaining_candidates.pop(idx)
    else:
        stats["arbitrary_centers_disabled"] = 1

    # 2) Direction profile only.  We deliberately do not emit automatic
    # Horizontal/Vertical constraints here: absolute orientation in the sketch
    # frame is a downstream engineering decision, not path topology.
    global_direction_profile = _compute_global_direction_profile(segments)
    stats["global_horizontal_score"] = float(_global_direction_score(global_direction_profile, "horizontal"))
    stats["global_vertical_score"] = float(_global_direction_score(global_direction_profile, "vertical"))
    hv_count = 0

    # 4) Circular support reduction: several exported arc fragments can come
    # from the same construction circle.  Attach the smaller fragments to one
    # representative with center Coincident + Equal radius.  This preserves the
    # construction circle without adding numeric radius dimensions.
    arcs = [meta for meta in geom_meta if meta.get("type") == "arc"]
    circle_groups = group_same_circle_arcs(arcs, dist_tol=dist_tol, radius_tol=dist_tol)
    circle_ref_by_id = {}
    circle_count = 0
    for group in circle_groups:
        ref = _choose_circle_reference(group)
        stats["circle_groups"] += 1
        stats["circle_members"] += len(group)
        for meta in group:
            circle_ref_by_id[id(meta)] = ref
        for child in group:
            if child is ref:
                continue
            if _add_same_circle_to_reference(add_constraint_safe, child, ref):
                circle_count += 1

    # 5) Local smoothness: only add tangent when neighbouring path elements
    # really share a smooth tangent.  This covers line/arc, arc/line, and
    # arc/arc transitions.  Pure segment/segment support collinearity is already
    # handled structurally above, so it is intentionally excluded here.
    tangent_count = int(stats.get("primitive_tangencies", 0))
    for _i, cur, nxt in junctions:
        cur_type = cur.get("type")
        nxt_type = nxt.get("type")
        if "arc" not in {cur_type, nxt_type}:
            continue
        if cur_type not in {"segment", "arc"} or nxt_type not in {"segment", "arc"}:
            continue
        key = tuple(sorted((int(cur["index"]), int(nxt["index"]))))
        if key in primitive_tangent_pairs:
            continue
        # If two neighbouring arcs are already attached to the same circle
        # support, Coincident center + Equal radius + endpoint Coincident makes
        # their smoothness a consequence.  Do not add a redundant Tangent.
        if cur_type == "arc" and nxt_type == "arc" and same_circle_support(cur, nxt, dist_tol=dist_tol, radius_tol=dist_tol):
            stats["skipped_relations"] += 1
            continue
        if are_tangent_vectors(tangent_vec_end(cur), tangent_vec_start(nxt)):
            if has_directional_user_intent(user_intents, cur, nxt):
                stats["auto_skipped_by_user_intent"] += 1
                stats["skipped_relations"] += 1
                continue
            if add_constraint_safe("Tangent", cur["index"], nxt["index"]):
                tangent_count += 1

    # Count explicit dimension intents that are currently intentionally ignored.
    for meta in geom_meta:
        src = meta.get("source_meta", {}) or {}
        if src.get("mode") in {"parallel-ref-series", "point-angle", "line-grid"}:
            stats["skipped_dimensions"] += 1


    # User intents were emitted earlier in Phase 2.
    # Keep desaturation as the final reduction pass; protected user constraints
    # are tracked through protected_constraint_indices.

    removed_constraints = _desaturate_export_constraints(sk, stats, exported_constraint_indices, protected_constraint_indices=protected_constraint_indices)

    shape_state = _diagnose_shape_constraint_state(sk, Sketcher, geom_meta)
    try:
        if shape_state.get("dof") is not None:
            stats["shape_dof"] = int(shape_state.get("dof"))
        if shape_state.get("anchored_dof") is not None:
            stats["shape_anchor_dof"] = int(shape_state.get("anchored_dof"))
        stats["shape_position_only"] = 1 if shape_state.get("position_only") else 0
        stats["shape_status"] = str(shape_state.get("status", "unknown"))
    except Exception:
        stats["shape_status"] = "unknown"

    _log(
        "Export constraints v1.3.8 capped-arbitrary-center-pairs: endpoint_coincidences=%d symmetry_y=%d symmetry_x=%d symmetry_center=%d symmetry_y_disabled=%d symmetry_x_disabled=%d central_symmetry_disabled=%d symmetry_skipped_by_cluster=%d symmetry_skipped_by_primitive=%d traversal_junctions=%d primitive_tangencies=%d parallel_groups=%d parallel_links=%d hv=%d collinear_groups=%d collinear_members=%d collinear_links=%d circle_groups=%d circle_members=%d circle_links=%d tangencies=%d hv_skipped_by_symmetry=%d hv_skipped_by_global_direction=%d global_h_score=%.2f global_v_score=%.2f arbitrary_center_candidates=%d arbitrary_center_pairs=%d arbitrary_center_selected=%d arbitrary_center_selected_pairs=%d arbitrary_center_greedy_rounds=%d arbitrary_center_weighted_score=%.2f arbitrary_center_skipped_by_competition=%d arbitrary_centers_disabled=%d arbitrary_axis_candidates=%d arbitrary_axis_pairs=%d arbitrary_axis_selected=%d arbitrary_axis_selected_pairs=%d arbitrary_axis_greedy_rounds=%d arbitrary_axis_weighted_score=%.2f arbitrary_axis_skipped_by_competition=%d arbitrary_axis_skipped_by_global_structure=%d arbitrary_axes_disabled=%d shape_dof=%d shape_anchor_dof=%d shape_position_only=%d shape_status=%s user_intents=%d user_intent_conflicts=%d user_forced_tangent=%d user_forced_colinearity=%d user_forced_length=%d user_forced_distance=%d user_forced_angle=%d user_forced_skipped=%d auto_skipped_by_user_intent=%d desaturation_enabled=%d desaturation_solver_reported=%d desaturation_solver_removed=%d desaturation_tried=%d desaturation_removed=%d desaturation_kept=%d desaturation_skipped=%d desaturation_no_dof=%d skipped_relations=%d skipped_dimension_sources=%d added=%d failed=%d"
        % (
            len(endpoint_pairs),
            stats["symmetry_y"],
            stats["symmetry_x"],
            stats["symmetry_center"],
            stats["symmetry_y_disabled"],
            stats["symmetry_x_disabled"],
            stats["central_symmetry_disabled"],
            stats["symmetry_skipped_by_cluster"],
            stats["symmetry_skipped_by_primitive"],
            len(junctions),
            stats["primitive_tangencies"],
            stats["parallel_groups"],
            stats["parallel_links"],
            hv_count,
            stats["collinear_groups"],
            stats["collinear_members"],
            collinear_count,
            stats["circle_groups"],
            stats["circle_members"],
            circle_count,
            tangent_count,
            stats["hv_skipped_by_symmetry"],
            stats["hv_skipped_by_global_direction"],
            float(stats["global_horizontal_score"]),
            float(stats["global_vertical_score"]),
            stats["arbitrary_center_candidates"],
            stats["arbitrary_center_pairs"],
            stats["arbitrary_center_selected"],
            stats["arbitrary_center_selected_pairs"],
            stats["arbitrary_center_greedy_rounds"],
            float(stats["arbitrary_center_weighted_score"]),
            stats["arbitrary_center_skipped_by_competition"],
            stats["arbitrary_centers_disabled"],
            stats["arbitrary_axis_candidates"],
            stats["arbitrary_axis_pairs"],
            stats["arbitrary_axis_selected"],
            stats["arbitrary_axis_selected_pairs"],
            stats["arbitrary_axis_greedy_rounds"],
            float(stats["arbitrary_axis_weighted_score"]),
            stats["arbitrary_axis_skipped_by_competition"],
            stats["arbitrary_axis_skipped_by_global_structure"],
            stats["arbitrary_axes_disabled"],
            stats["shape_dof"],
            stats["shape_anchor_dof"],
            stats["shape_position_only"],
            stats.get("shape_status", "unknown"),
            stats["user_intents"],
            stats["user_intent_conflicts"],
            stats["user_forced_tangent"],
            stats["user_forced_colinearity"],
            stats["user_forced_length"],
            stats["user_forced_distance"],
            stats["user_forced_angle"],
            stats["user_forced_skipped"],
            stats["auto_skipped_by_user_intent"],
            stats["desaturation_enabled"],
            stats["desaturation_solver_reported"],
            stats["desaturation_solver_removed"],
            stats["desaturation_tried"],
            stats["desaturation_removed"],
            stats["desaturation_kept"],
            stats["desaturation_skipped"],
            stats["desaturation_no_dof"],
            stats["skipped_relations"],
            stats["skipped_dimensions"],
            stats["added"],
            stats["failed"],
        )
    )

    return {
        "indices": exported_constraint_indices,
        "stats": stats,
        "policy": "minimal-v1.3.7-aggressive-local-desaturation",
        "desaturation_removed": removed_constraints,
    }
