# SPDX-License-Identifier: LGPL-2.1-or-later
"""Constraint export helpers for euSKlid Sketcher exports.

This package is intentionally small for v1: it provides a candidate/reducer/
emitter layer so path export stops mixing topology analysis and Sketcher API
calls directly inside the UI tool.
"""

from .emit import add_path_constraints

__all__ = ["add_path_constraints"]
