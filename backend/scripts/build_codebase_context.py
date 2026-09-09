"""Build a source-only index for Scout, excluding secrets, assets and private runtime data."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
source = {}
for folder in ("app", "src", "admin/src", "backend/app", "docs"):
    for path in sorted((ROOT / folder).rglob("*")):
        if not path.is_file() or path.suffix not in (".py", ".ts", ".tsx", ".md", ".css"):
            continue
        if any(
            p.startswith(".") or p in ("node_modules", "__pycache__")
            for p in path.relative_to(ROOT).parts
        ):
            continue
        if path.name in ("config.py", "authentication.py"):
            continue
        if path.stat().st_size > 180000:
            continue
        source[str(path.relative_to(ROOT))] = path.read_text()
(ROOT / "backend/codebase-context.json").write_text(json.dumps(source))
print(f"Indexed {len(source)} source files for read-only assistant retrieval")
