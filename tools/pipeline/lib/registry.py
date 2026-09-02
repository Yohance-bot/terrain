"""Stage discovery.

Stage files are named `01_download_data.py` through `13_publish_gameplay.py`. Numbering
them on disk means `ls stages/` tells you the pipeline order, which is worth a
lot when many files each do something a reader cannot guess from the name.

The cost is that `01_download_data` is not a legal Python identifier, so the
modules cannot be imported with `import`. They are loaded by file path instead.
That is contained entirely in this file, and every other module -- orchestrator,
tests, stage bodies -- works with ordinary objects.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
STAGES_DIR = PIPELINE_ROOT / "stages"

_STAGE_FILENAME = re.compile(r"^(\d{2})_[a-z0-9_]+\.py$")

_REQUIRED_ATTRIBUTES = ("NUMBER", "NAME", "REQUIRES", "PRODUCES", "run")


class StageLoadError(RuntimeError):
    """A stage file exists but does not satisfy the Stage contract."""


@dataclass(frozen=True)
class LoadedStage:
    number: int
    name: str
    path: Path
    module: ModuleType

    @property
    def requires(self):
        return self.module.REQUIRES

    @property
    def produces(self):
        return self.module.PRODUCES

    def run(self, ctx):
        return self.module.run(ctx)


def _ensure_importable() -> None:
    """Make `from lib...` work inside stage modules loaded by path.

    A module loaded via importlib resolves its own imports through `sys.path`
    like any other, so the pipeline root has to be on it. pytest already does
    this via `pythonpath`; the CLI does not.
    """
    root = str(PIPELINE_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _load_module(path: Path) -> ModuleType:
    _ensure_importable()
    module_name = f"pipeline_stage_{path.stem}"
    # Reuse an already-loaded module. Reloading on every discover_stages() call
    # would discard monkeypatches (and any other in-process state) that tests
    # and long-running tools attach to the stage module.
    existing = sys.modules.get(module_name)
    if existing is not None and getattr(existing, "__file__", None) == str(path):
        return existing

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise StageLoadError(f"could not load stage module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def discover_stages(stages_dir: Path | None = None) -> list[LoadedStage]:
    """Load every stage in numeric order, validating the contract as we go."""
    directory = stages_dir or STAGES_DIR
    stages: list[LoadedStage] = []
    seen_numbers: dict[int, Path] = {}

    for path in sorted(directory.glob("*.py")):
        match = _STAGE_FILENAME.match(path.name)
        if not match:
            continue

        module = _load_module(path)
        missing = [attr for attr in _REQUIRED_ATTRIBUTES if not hasattr(module, attr)]
        if missing:
            raise StageLoadError(f"{path.name} is missing {', '.join(missing)}")

        number = int(match.group(1))
        if module.NUMBER != number:
            raise StageLoadError(
                f"{path.name} declares NUMBER={module.NUMBER} but its filename says {number}"
            )
        if number in seen_numbers:
            raise StageLoadError(
                f"stage number {number} is claimed by both "
                f"{seen_numbers[number].name} and {path.name}"
            )
        seen_numbers[number] = path

        stages.append(LoadedStage(number=number, name=module.NAME, path=path, module=module))

    if not stages:
        raise StageLoadError(f"no stage modules found in {directory}")
    return sorted(stages, key=lambda s: s.number)


def select_stages(
    stages: list[LoadedStage], from_stage: int | None = None, to_stage: int | None = None
) -> list[LoadedStage]:
    low = from_stage if from_stage is not None else stages[0].number
    high = to_stage if to_stage is not None else stages[-1].number
    if low > high:
        raise ValueError(f"--from-stage {low} is after --to-stage {high}")
    selected = [s for s in stages if low <= s.number <= high]
    if not selected:
        raise ValueError(f"no stages in range {low}..{high}")
    return selected
