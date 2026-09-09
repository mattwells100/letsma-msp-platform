from pathlib import Path
from datetime import datetime
import shutil
import re

p = Path("app/routers/ai_assist.py")

backup = f"{p}.bak-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(p, backup)

txt = p.read_text(encoding="utf-8")

pattern = re.compile(
    r'raw_result\s*=\s*await\s+azure_openai_service\.draft_ticket_reply\((.*?)\n\s*\)',
    re.DOTALL,
)

replacement = """raw_result = await azure_openai_service.classify_ticket(
            prompt
        )"""

new_txt, count = pattern.subn(replacement, txt, count=1)

if count != 1:
    raise SystemExit(
        f"Expected to replace 1 call, replaced {count}. "
        "Open ai_assist.py and inspect manually."
    )

p.write_text(new_txt, encoding="utf-8")

print("[OK] ai_assist.py patched")
print("[OK] Backup:", backup)