
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
