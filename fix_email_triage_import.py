from pathlib import Path
from datetime import datetime
import shutil
import py_compile

target = Path("app/services/email_ingestion_service.py")

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup = f"{target}.bak-fix-{stamp}"

shutil.copy2(target, backup)
print(f"[BACKUP] {backup}")

text = target.read_text(encoding="utf-8")

old = "from app.services.ai_service import get_openai_client"
new = "from app.services.azure_openai_service import get_openai_client"

if old in text:
    text = text.replace(old, new)
    print("[OK] Replaced ai_service import")
else:
    print("[WARN] ai_service import not found")

target.write_text(text, encoding="utf-8")

try:
    py_compile.compile(str(target), doraise=True)
    print("[COMPILE OK]")
except Exception as exc:
    print(f"[COMPILE FAIL] {exc}")
