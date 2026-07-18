"""Upload batches to R2 via the locally-installed wrangler (fast startup)."""

import subprocess
from pathlib import Path

BUCKET = "stem-diagrams-dataset"
WRANGLER = str(Path(__file__).resolve().parent / "node_modules" / ".bin" / "wrangler")


def put(local_path, key, content_type=None, timeout=900):
    cmd = [WRANGLER, "r2", "object", "put", f"{BUCKET}/{key}",
           "--file", str(local_path), "--remote"]
    if content_type:
        cmd += ["--content-type", content_type]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    ok = r.returncode == 0 and "Upload complete" in (r.stdout + r.stderr)
    return ok, (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr) else ""
