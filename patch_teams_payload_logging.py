from pathlib import Path
from datetime import datetime
import shutil

p = Path("app/routers/teams_bot.py")

backup = f"{p}.bak-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(p, backup)

txt = p.read_text(encoding="utf-8")

if "import json" not in txt:
    txt = txt.replace(
        "from sqlalchemy.orm import Session",
        "from sqlalchemy.orm import Session\nimport json"
    )

old = "    payload = await request.json()"

new = """    payload = await request.json()

    print("=" * 80)
    print("TEAMS PAYLOAD")
    print(json.dumps(payload, indent=2, default=str))
    print("=" * 80)
"""

if old not in txt:
    raise SystemExit("Could not find payload line")

txt = txt.replace(old, new, 1)

p.write_text(txt, encoding="utf-8")

print("[OK] Teams payload logging added")
print("[OK] Backup:", backup)