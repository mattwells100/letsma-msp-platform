from pathlib import Path
from datetime import datetime
import shutil

p = Path("app/routers/ai_assist.py")

text = p.read_text(encoding="utf-8")

backup = f"{p}.bak-unicode-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(p, backup)

old = """    category = str(value.get("category", "")).strip()
    subcategory = str(value.get("subcategory", "")).strip()
    priority = str(value.get("priority", "Normal")).strip()
"""

new = """    category = str(value.get("category", "")).strip()
    subcategory = str(value.get("subcategory", "")).strip()

    # Normalise common unicode hyphens returned by GPT
    category = (
        category
        .replace("‑", "-")
        .replace("–", "-")
        .replace("—", "-")
    )

    subcategory = (
        subcategory
        .replace("‑", "-")
        .replace("–", "-")
        .replace("—", "-")
    )

    priority = str(value.get("priority", "Normal")).strip()
"""

if old not in text:
    raise SystemExit("Target block not found")

text = text.replace(old, new, 1)

p.write_text(text, encoding="utf-8")

print("[OK] Unicode normalisation added")
print(f"[OK] Backup created: {backup}")