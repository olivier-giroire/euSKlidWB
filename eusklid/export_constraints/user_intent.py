# SPDX-License-Identifier: LGPL-2.1-or-later
"""User intent normalization and validation for euSKlid Path export.

This module deliberately does not emit Sketcher constraints directly.
It converts UI overload records into a small, stable semantic layer used by the
exporter to:

- give user-forced constraints priority over calculated constraints;
- detect contradictions between user intentions before export reduction;
- protect user-forced constraints from global desaturation/removal.
"""

from __future__ import annotations


RELATION_KINDS = {
    "tangent",
    "preserve_tangent",
    "radius",
    "distance",
    "angle",
    "colinearity",
    "collinearity",
}


def _as_int(value, default=None):
    try:
        return int(value)
    except Exception:
        return default


def _piece_pair(pieces):
    vals = []
    try:
        for p in pieces or []:
            ip = _as_int(p)
            if ip is not None:
                vals.append(ip)
    except Exception:
        pass
    if len(vals) < 2:
        return None
    return tuple(sorted(vals[:2]))


def _ref_key(ref):
    """Return a stable key for point/segment references."""
    ref = ref or {}
    piece = _as_int(ref.get("piece"))
    kind = str(ref.get("kind") or "segment")
    try:
        t = round(float(ref.get("t", 0.5)), 6)
    except Exception:
        t = 0.5
    return (kind, piece, t)


def _range_pair(range_data):
    try:
        a = _ref_key((range_data or {}).get("start") or {})
        b = _ref_key((range_data or {}).get("end") or {})
        return tuple(sorted([a, b]))
    except Exception:
        return None


def _canonical_kind(kind):
    k = str(kind or "").strip().lower()
    if k == "preserve_tangent":
        return "tangent"
    if k == "collinearity":
        return "colinearity"
    return k


def normalize_overload(ov, ordinal=0):
    """Normalize a raw Path overload into an export user-intent record."""
    if not isinstance(ov, dict):
        return None

    kind = _canonical_kind(ov.get("kind"))
    if kind not in RELATION_KINDS:
        return None

    pieces = []
    try:
        pieces = [_as_int(p) for p in (ov.get("pieces", []) or [])]
        pieces = [p for p in pieces if p is not None]
    except Exception:
        pieces = []

    rng = ov.get("range", {}) or {}

    if kind in ("tangent", "colinearity", "angle"):
        pair = _piece_pair(pieces)
        if pair is None:
            return None
        key = ("piece_pair", pair)
    elif kind == "radius":
        if not pieces:
            return None
        key = ("piece", int(pieces[0]))
    elif kind == "distance":
        pair = _range_pair(rng)
        if pair is None:
            pair = _piece_pair(pieces)
            if pair is None:
                return None
            key = ("piece_pair", pair)
        else:
            key = ("ref_pair", pair)
    else:
        return None

    return {
        "kind": kind,
        "pieces": pieces,
        "piece_pair": _piece_pair(pieces),
        "range": rng,
        "key": key,
        "raw": ov,
        "ordinal": int(ordinal),
        "protected": True,
    }


def normalize_overloads(overloads):
    out = []
    try:
        iterable = list(overloads or [])
    except Exception:
        iterable = []

    for i, ov in enumerate(iterable):
        n = normalize_overload(ov, ordinal=i)
        if n is not None:
            out.append(n)
    return out


def _conflict(a, b):
    """Return a human-readable conflict reason or None."""
    if a is b:
        return None

    ka = a.get("kind")
    kb = b.get("kind")

    # Same piece pair, directional relations.
    if a.get("piece_pair") is not None and a.get("piece_pair") == b.get("piece_pair"):
        pair = a.get("piece_pair")

        # Tangent and colinearity are equivalent for two straight segments in
        # FreeCAD's Sketcher overload used here. They do not conflict.
        if {ka, kb} <= {"tangent", "colinearity"}:
            return None

        # An explicit angle on the same pair conflicts with a tangent/colinear
        # forced relation unless a future UI stores an angle value of 0/pi.
        if "angle" in (ka, kb) and ("tangent" in (ka, kb) or "colinearity" in (ka, kb)):
            return "angle conflicts with tangent/colinearity on pieces %s" % (pair,)

    # Same geometric reference pair with duplicate dimensional intents.
    if a.get("key") == b.get("key"):
        # Duplicate same-kind overload is redundant, not blocking.
        return None

    return None


def validate_user_intents(intents):
    """Validate normalized intents.

    Returns:
        {
            "ok": bool,
            "conflicts": [str],
            "warnings": [str],
        }
    """
    conflicts = []
    warnings = []

    for i, a in enumerate(intents or []):
        for b in list(intents or [])[i + 1:]:
            reason = _conflict(a, b)
            if reason:
                conflicts.append(reason)

    # Repeated identical intents are tolerated but reported.
    seen = {}
    for it in intents or []:
        key = (it.get("kind"), it.get("key"))
        if key in seen:
            warnings.append("duplicate user intent ignored: %s %s" % key)
        else:
            seen[key] = it

    return {
        "ok": not conflicts,
        "conflicts": conflicts,
        "warnings": warnings,
    }


def piece_pair_for_meta(a, b):
    try:
        pa = _as_int(a.get("piece_order"))
        pb = _as_int(b.get("piece_order"))
        if pa is None or pb is None:
            return None
        return tuple(sorted((pa, pb)))
    except Exception:
        return None


def has_intent_for_piece_pair(intents, kind, a, b):
    pair = piece_pair_for_meta(a, b)
    if pair is None:
        return False
    ck = _canonical_kind(kind)
    for it in intents or []:
        if it.get("kind") == ck and it.get("piece_pair") == pair:
            return True
    return False


def has_directional_user_intent(intents, a, b):
    pair = piece_pair_for_meta(a, b)
    if pair is None:
        return False
    for it in intents or []:
        if it.get("piece_pair") == pair and it.get("kind") in {"tangent", "colinearity", "angle"}:
            return True
    return False


def forced_piece_pair_intents(intents, kinds=None):
    wanted = None
    if kinds is not None:
        wanted = {_canonical_kind(k) for k in kinds}
    for it in intents or []:
        if wanted is not None and it.get("kind") not in wanted:
            continue
        pair = it.get("piece_pair")
        if pair is None:
            continue
        yield it, pair


def forced_piece_pairs_for_intent(intent):
    """Yield one or more piece pairs carried by a normalized intent.

    Tangency ranges may contain more than two pieces.  In that case the user
    intent applies to each consecutive local transition in the selected range.
    """
    pieces = []
    try:
        pieces = [int(p) for p in (intent.get("pieces", []) or [])]
    except Exception:
        pieces = []

    if len(pieces) >= 2:
        for a, b in zip(pieces, pieces[1:]):
            yield tuple(sorted((int(a), int(b))))
        return

    pair = intent.get("piece_pair")
    if pair is not None:
        yield pair


def forced_piece_pair_intents_expanded(intents, kinds=None):
    wanted = None
    if kinds is not None:
        wanted = {_canonical_kind(k) for k in kinds}
    for it in intents or []:
        if wanted is not None and it.get("kind") not in wanted:
            continue
        for pair in forced_piece_pairs_for_intent(it):
            yield it, pair


def forced_dimension_intents(intents):
    for it in intents or []:
        if it.get("kind") in {"radius", "distance"}:
            yield it
