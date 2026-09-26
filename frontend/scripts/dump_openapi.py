"""Write the FastAPI app's OpenAPI schema to frontend/src/api/openapi.json.

Imports `api.main.app` directly rather than fetching /openapi.json from a running server,
so `npm run generate-client` works without uvicorn up and is byte-identical on every
machine (sorted keys, fixed indent). Run through the repo's uv environment:
`npm run generate-client` does this for you.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = REPO_ROOT / "frontend" / "src" / "api" / "openapi.json"

sys.path.insert(0, str(REPO_ROOT))

from api.main import app  # needs the repo root on sys.path first

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
# newline="\n": LF on Windows too, so the committed file doesn't churn between machines.
OUT_PATH.write_text(
    json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
)
print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)}")
