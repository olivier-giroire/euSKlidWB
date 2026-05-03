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
        # Lock keeps the construction point at the sketch origin.  Some
        # FreeCAD builds may reject the exact overload; the safe wrapper keeps
        # this non-fatal.
        _add_constraint_safe(sk, Sketcher, stats, exported_constraint_indices, "Lock", int(idx), 1, 0.0, 0.0)
        return int(idx)
    except Exception as exc:
        _log("Export central symmetry skipped: cannot create origin point: %s" % exc)
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
        "Export constraints v6.3.3 symmetry-modes: endpoint_coincidences=%d symmetry_y=%d symmetry_x=%d symmetry_center=%d symmetry_y_disabled=%d symmetry_x_disabled=%d central_symmetry_disabled=%d symmetry_skipped_by_cluster=%d traversal_junctions=%d hv=%d collinear_groups=%d collinear_members=%d collinear_links=%d circle_groups=%d circle_members=%d circle_links=%d tangencies=%d hv_skipped_by_symmetry=%d skipped_relations=%d skipped_dimension_sources=%d added=%d failed=%d"
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
            stats["skipped_relations"],
            stats["skipped_dimensions"],
            stats["added"],
            stats["failed"],
        )
    )

    return {
        "indices": exported_constraint_indices,
        "stats": stats,
        "policy": "minimal-v6.3.3-symmetry-modes",
    }
