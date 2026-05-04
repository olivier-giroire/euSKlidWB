# SPDX-License-Identifier: LGPL-2.1-or-later
"""Small data model for Sketcher constraint export candidates."""

from dataclasses import dataclass, field
from typing import Any, Tuple


@dataclass(frozen=True)
class ConstraintCandidate:
    """A Sketcher constraint proposal before reduction/emission.

    ``args`` are the positional arguments passed to ``Sketcher.Constraint``.
    Lower priority values are emitted first.  ``source`` is for logs/debugging
    and should describe whether the candidate comes from topology, intent, or a
    post-detection rule.
    """

    kind: str
    args: Tuple[Any, ...]
    priority: int = 100
    source: str = "detected"
    reason: str = ""
    meta: dict = field(default_factory=dict)

    def key(self):
        return (self.kind, self.args)
