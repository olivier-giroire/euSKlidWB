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

import re

from .core import logging as elog


class DistanceSeries(list):
    def __init__(self, values=(), meta=None, items=None):
        super(DistanceSeries, self).__init__(values)
        self.meta = meta or {}
        self.items = items or []


_NUMBER_RE = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"


def _split_top_level_commas(text):
    """Split on commas that are not inside a sequence pattern."""
    parts = []
    start = 0
    depth = 0

    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1

    tail = text[start:].strip()
    if tail:
        parts.append(tail)

    return [p for p in parts if p]


def _parse_pattern(text):
    vals = []
    for tok in _split_top_level_commas(text):
        tok = tok.strip()
        if not tok:
            continue
        vals.append(float(tok))
    return vals


def _parse_value(text):
    if re.fullmatch(r"\s*%s\s*" % _NUMBER_RE, text):
        return float(text)
    raise ValueError("invalid value: %s" % text)


def _parse_repeat_token(token, seq_index):
    """Parse repeat sequence token.

    Accepted forms:
        repeat 13 (0,1) origin 0 step 2.5
        repeat 13 (0,1) org 0 stp 2.5
        repeat 13 (0,1) o 0 s 2.5
        rep 13 (0,1) o 0 s 2.5
        r 13 (0,1) o 0 s 2.5

    Sequence tokens must always start with repeat/rep/r.
    The origin and all values are relative to the picked reference.
    """
    token = token.strip()
    pattern = re.compile(
        r"^\s*"
        r"(?:repeat|rep|r)\s+(?P<count>\d+)\s*"
        r"\((?P<pattern>[^\)]+)\)\s*"
        r"(?:(?:origin|org|o)\s+(?P<origin>%s)\s*)?"
        r"(?:step|stp|s)\s+(?P<step>%s)"
        r"\s*$" % (_NUMBER_RE, _NUMBER_RE),
        re.IGNORECASE,
    )
    m = pattern.match(token)
    if not m:
        return None

    count = int(m.group("count"))
    origin = float(m.group("origin") if m.group("origin") is not None else 0.0)
    step = float(m.group("step"))
    pattern_values = _parse_pattern(m.group("pattern"))

    if count < 0:
        raise ValueError("repeat count must be positive")
    if not pattern_values:
        raise ValueError("empty repeat pattern")

    values = []
    items = []
    block_id = "seq-%d" % seq_index

    for repeat_index in range(count):
        base = origin + repeat_index * step
        for pattern_index, pattern_value in enumerate(pattern_values):
            distance = base + pattern_value
            values.append(distance)
            items.append({
                "distance": distance,
                "block_id": block_id,
                "block_kind": "repeat",
                "repeat_index": repeat_index,
                "pattern_index": pattern_index,
                "pattern_value": pattern_value,
                "origin": origin,
                "step": step,
                "repeat": count,
                "pattern": list(pattern_values),
            })

    meta = {
        "kind": "mixed",
        "raw_kind": "repeat",
        "block_id": block_id,
        "origin": origin,
        "repeat": count,
        "pattern": list(pattern_values),
        "step": step,
    }
    return DistanceSeries(values, meta=meta, items=items)


def parse_distance_series(text):
    """Parse Series //Ref distances.

    Value separator:
        comma only. Spaces around commas are optional.

    Values:
        30,33,40,43

    Repeat sequence:
        repeat 13 (0,1) origin 0 step 2.5
        repeat 13 (0,1) org 0 stp 2.5
        repeat 13 (0,1) o 0 s 2.5
        rep 13 (0,1) o 0 s 2.5
        r 13 (0,1) o 0 s 2.5

    Mixed:
        repeat 13 (0,1) origin 0 step 2.5,30,33,40,43
        repeat 13 (0,1) org 0 step 2.5, repeat 6 (0,2) o 40 s 8

    All distances are relative to the selected reference.
    """
    if text is None:
        return DistanceSeries()

    raw = str(text).strip()
    if not raw:
        return DistanceSeries()

    tokens = _split_top_level_commas(raw)
    values = []
    items = []
    sequence_count = 0

    for token_index, token in enumerate(tokens):
        seq = _parse_repeat_token(token, sequence_count)
        if seq is not None:
            sequence_count += 1
            base_index = len(values)
            values.extend(seq)
            for local_i, item in enumerate(seq.items):
                enriched = dict(item)
                enriched["token_index"] = token_index
                enriched["sequence_index"] = base_index + local_i
                items.append(enriched)
            continue

        value = _parse_value(token)
        values.append(value)
        items.append({
            "distance": value,
            "block_kind": "value",
            "token_index": token_index,
            "sequence_index": len(values) - 1,
        })

    result = DistanceSeries(values, meta={
        "kind": "mixed" if sequence_count else "list",
        "raw": raw,
        "sequence_blocks": sequence_count,
    }, items=items)

    if sequence_count:
        elog.info("Series //Ref sequence expanded to %d distance(s)" % len(result))

    return result
