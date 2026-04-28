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


from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

@dataclass
class StepSpec:
    name: str
    input_kind: str
    snap_policy: str = "default"
    highlight_policy: str = "default"
    preview_policy: str = "default"

@dataclass
class CommandContext:
    name: str
    primitive: str
    steps: List[StepSpec]
    builder: Optional[Callable[..., Any]] = None
    sketch_obj: Any = None
    plane: Any = None
    current_step: int = 0
    inputs: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def step(self) -> StepSpec:
        return self.steps[self.current_step]
