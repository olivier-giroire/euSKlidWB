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

from .detect import (
    arc_sweep_length,
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
        _add_constraint_safe(sk, Sketcher, stats, exported_constraint_indices, "Lock", int(idx))
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
        _add_constraint_safe(sk, Sketcher, stats, exported_constraint_indices, "Lock", int(idx))
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
        _add_constraint_safe(sk, Sketcher, stats, exported_constraint_indices, "Lock", int(idx))
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


def add_path_constraints(sk, Sketcher, geom_meta, tol_join):
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
        "hv_skipped_by_symmetry": 0,
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
        "arbitrary_axes_disabled": 0,
    }
    exported_constraint_indices = []

    def add_constraint_safe(*args):
        return _add_constraint_safe(sk, Sketcher, stats, exported_constraint_indices, *args)

    # Preserve path traversal index for deterministic tie-breaking.
    for order, meta in enumerate(geom_meta):
        try:
            meta.setdefault("path_order", order)
        except Exception:
            pass

    # 1) Topology: endpoint coincidences.  This is the mandatory family and
    # must never be reduced away by support-line or support-circle logic.
    # Use all geometric endpoint pairs, not only successive traversal
    # neighbours: outer circular supports can be exported as non-consecutive
    # fragments while still sharing real topological endpoints.
    endpoint_pairs = list(endpoint_coincidence_pairs(geom_meta, tol_join))
    for cur, cur_point, nxt, nxt_point in endpoint_pairs:
        add_constraint_safe("Coincident", cur["index"], cur_point, nxt["index"], nxt_point)


    # 1b) Symmetry: conservative axis passes.  Work on endpoint clusters so
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

    def symmetry_pair_available(meta_a, point_a, meta_b, point_b):
        key = _symmetry_pair_key(meta_a, point_a, meta_b, point_b)
        if key in used_symmetry_pairs:
            return False
        if _symmetry_point_key(meta_a, point_a) in used_symmetry_points:
            return False
        if _symmetry_point_key(meta_b, point_b) in used_symmetry_points:
            return False
        return True

    symmetry_y_count = 0
    if _axial_symmetry_y_enabled():
        for left, left_point, right, right_point in mirrored_endpoint_pairs_y_axis(geom_meta, symmetry_tol):
            if not symmetry_pair_available(left, left_point, right, right_point):
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
                _log(
                    "Export arbitrary symmetry axis candidate: point=(%.6g, %.6g) dir=(%.6g, %.6g) score=%d weighted=%.2f raw_pairs=%d useful=%d useful_weight=%.2f"
                    % (float(px), float(py), float(ux), float(uy), raw_score, weighted_score, raw_pairs, useful_score, useful_weight)
                )
                if useful_score >= min_sym_score:
                    scored.append((useful_weight, useful_score, weighted_score, raw_score, -idx, idx, candidate, useful_pairs))

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

            kept_for_center = 0
            kept_weight = 0.0
            for meta_a, point_a, meta_b, point_b, relevance in useful_pairs:
                # Re-check availability because each emitted pair marks its
                # endpoints.  This protects the greedy pass from stale scores.
                if not symmetry_pair_available(meta_a, point_a, meta_b, point_b):
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

    # Keep traversal junctions separately for local smoothness decisions.
    junctions = list(connected_junctions(geom_meta, tol_join))

    # 2) Structural reduction: common support lines.  A construction line may
    # appear as many disconnected path fragments; only its reference fragment
    # gets the H/V direction marker.  Other fragments are attached by support
    # collinearity instead of repeating the same direction constraint.
    segments = [meta for meta in geom_meta if meta.get("type") == "segment"]
    # tol_join is a geometric model tolerance; support grouping needs to be a
    # little stricter than endpoint joining but still tolerant of exported float
    # noise.
    dist_tol = max(float(tol_join) * 0.25, 1e-6)
    groups = group_collinear_segments(segments, dist_tol=dist_tol)
    grouped_ids = set()
    hv_count = 0
    collinear_count = 0
    for group in groups:
        ref = _choose_collinear_reference(group)
        stats["collinear_groups"] += 1
        stats["collinear_members"] += len(group)
        for meta in group:
            grouped_ids.add(id(meta))

        dx, dy = segment_dir(ref)
        if is_horizontal(dx, dy):
            # Symmetry has priority over H/V: if any fragment of this support
            # line has endpoints mirrored about Y, horizontality is already a
            # consequence of the Symmetric constraint plus support Tangent links.
            if _group_has_symmetry_implied_horizontal(group, max(float(tol_join), 1e-5)):
                stats["hv_skipped_by_symmetry"] += 1
                stats["skipped_relations"] += 1
            elif add_constraint_safe("Horizontal", ref["index"]):
                hv_count += 1
        elif is_vertical(dx, dy):
            # Same for verticality: endpoint symmetry about X implies vertical.
            if _group_has_symmetry_implied_vertical(group, max(float(tol_join), 1e-5)):
                stats["hv_skipped_by_symmetry"] += 1
                stats["skipped_relations"] += 1
            elif add_constraint_safe("Vertical", ref["index"]):
                hv_count += 1

        for child in group:
            if child is ref:
                continue
            if _add_collinearity_to_reference(add_constraint_safe, child, ref):
                collinear_count += 1

    # 3) Standalone H/V hints: only for segments that are not part of a detected
    # support group.
    for meta in segments:
        if id(meta) in grouped_ids:
            continue
        dx, dy = segment_dir(meta)
        if is_horizontal(dx, dy):
            if _endpoint_mirrored_y(meta, max(float(tol_join), 1e-5)):
                stats["hv_skipped_by_symmetry"] += 1
                stats["skipped_relations"] += 1
            elif add_constraint_safe("Horizontal", meta["index"]):
                hv_count += 1
        elif is_vertical(dx, dy):
            if _endpoint_mirrored_x(meta, max(float(tol_join), 1e-5)):
                stats["hv_skipped_by_symmetry"] += 1
                stats["skipped_relations"] += 1
            elif add_constraint_safe("Vertical", meta["index"]):
                hv_count += 1

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
    tangent_count = 0
    for _i, cur, nxt in junctions:
        cur_type = cur.get("type")
        nxt_type = nxt.get("type")
        if "arc" not in {cur_type, nxt_type}:
            continue
        if cur_type not in {"segment", "arc"} or nxt_type not in {"segment", "arc"}:
            continue
        # If two neighbouring arcs are already attached to the same circle
        # support, Coincident center + Equal radius + endpoint Coincident makes
        # their smoothness a consequence.  Do not add a redundant Tangent.
        if cur_type == "arc" and nxt_type == "arc" and same_circle_support(cur, nxt, dist_tol=dist_tol, radius_tol=dist_tol):
            stats["skipped_relations"] += 1
            continue
        if are_tangent_vectors(tangent_vec_end(cur), tangent_vec_start(nxt)):
            if add_constraint_safe("Tangent", cur["index"], nxt["index"]):
                tangent_count += 1

    # Count explicit dimension intents that are currently intentionally ignored.
    for meta in geom_meta:
        src = meta.get("source_meta", {}) or {}
        if src.get("mode") in {"parallel-ref-series", "point-angle", "line-grid"}:
            stats["skipped_dimensions"] += 1

    _log(
        "Export constraints v6.5.2 axes-before-centers: endpoint_coincidences=%d symmetry_y=%d symmetry_x=%d symmetry_center=%d symmetry_y_disabled=%d symmetry_x_disabled=%d central_symmetry_disabled=%d symmetry_skipped_by_cluster=%d traversal_junctions=%d hv=%d collinear_groups=%d collinear_members=%d collinear_links=%d circle_groups=%d circle_members=%d circle_links=%d tangencies=%d hv_skipped_by_symmetry=%d arbitrary_center_candidates=%d arbitrary_center_pairs=%d arbitrary_center_selected=%d arbitrary_center_selected_pairs=%d arbitrary_center_greedy_rounds=%d arbitrary_center_weighted_score=%.2f arbitrary_center_skipped_by_competition=%d arbitrary_centers_disabled=%d arbitrary_axis_candidates=%d arbitrary_axis_pairs=%d arbitrary_axis_selected=%d arbitrary_axis_selected_pairs=%d arbitrary_axis_greedy_rounds=%d arbitrary_axis_weighted_score=%.2f arbitrary_axis_skipped_by_competition=%d arbitrary_axes_disabled=%d skipped_relations=%d skipped_dimension_sources=%d added=%d failed=%d"
        % (
            len(endpoint_pairs),
            stats["symmetry_y"],
            stats["symmetry_x"],
            stats["symmetry_center"],
            stats["symmetry_y_disabled"],
            stats["symmetry_x_disabled"],
            stats["central_symmetry_disabled"],
            stats["symmetry_skipped_by_cluster"],
            len(junctions),
            hv_count,
            stats["collinear_groups"],
            stats["collinear_members"],
            collinear_count,
            stats["circle_groups"],
            stats["circle_members"],
            circle_count,
            tangent_count,
            stats["hv_skipped_by_symmetry"],
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
            stats["arbitrary_axes_disabled"],
            stats["skipped_relations"],
            stats["skipped_dimensions"],
            stats["added"],
            stats["failed"],
        )
    )

    return {
        "indices": exported_constraint_indices,
        "stats": stats,
        "policy": "minimal-v6.5.2-axes-before-centers",
    }
