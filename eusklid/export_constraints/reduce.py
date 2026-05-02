# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reduction helpers for export constraint candidates.

The v1 reducer is deliberately conservative: it removes exact duplicates and
emits candidates by priority.  More semantic redundancy rules can be added here
without touching Path UI/export code.
"""


def reduce_candidates(candidates):
    seen = set()
    out = []
    for candidate in sorted(candidates, key=lambda c: (c.priority, c.kind, repr(c.args))):
        key = candidate.key()
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out
