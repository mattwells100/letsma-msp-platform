from pathlib import Path
from datetime import datetime
import shutil
import re

p = Path("app/templates/tickets.html")

txt = p.read_text(encoding="utf-8")

backup = f"{p}.bak-fix-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(p, backup)

# Fix the first few lines completely
txt = re.sub(
    r'^\{\% extends "base.html" \%\}.*?\{\% block content \%\}',
    '{% extends "base.html" %}\n{% block title %}Helpdesk - Letsma MSP{% endblock %}\n{% block content %}',
    txt,
    flags=re.S
)

# Remove accidental duplicate applyFilters block near top
first = txt.find("function applyFilters()")
second = txt.find("function applyFilters()", first + 1)

if first != -1 and second != -1:
    script_start = txt.rfind("<script", 0, first)
    script_end = txt.find("</script>", first)

    if script_start != -1 and script_end != -1:
        txt = txt[:script_start] + txt[script_end + 9:]

p.write_text(txt, encoding="utf-8")

print("[OK] Header repaired")
print("[OK] Duplicate applyFilters removed")
print(f"[OK] Backup: {backup}")