from pathlib import Path
from datetime import datetime
import shutil, subprocess, sys

PORTAL = Path("app/routers/portal.py")
bak = Path(f"{PORTAL}.bak-now-{datetime.now():%Y%m%d-%H%M%S}")
shutil.copy2(PORTAL, bak)

t = PORTAL.read_text(encoding="utf-8")
anchor = '"unassigned_count": unassigned_count,\n    })'
inject = '"unassigned_count": unassigned_count,\n        "now": datetime.utcnow(),\n    })'
if '"now": datetime.utcnow()' not in t:
    if anchor not in t:
        raise SystemExit("context anchor not found")
    t = t.replace(anchor, inject, 1)

# ensure datetime imported
if "from datetime import datetime" not in t and "import datetime" not in t:
    t = t.replace("from fastapi", "from datetime import datetime\nfrom fastapi", 1)

PORTAL.write_text(t, encoding="utf-8")

r = subprocess.run([sys.executable, "-m", "py_compile", str(PORTAL)],
                   capture_output=True, text=True)
if r.returncode != 0:
    shutil.copy2(bak, PORTAL)
    print("[FAILED] rolled back\n" + r.stdout + r.stderr)
    raise SystemExit(1)

print("[OK] 'now' added to tickets template context")
print(f"[OK] Backup: {bak.name}")
