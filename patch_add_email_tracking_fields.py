#!/usr/bin/env python3

from pathlib import Path
from datetime import datetime
import shutil
import py_compile
import re

STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")

MODELS = Path("app/models.py")

if not MODELS.exists():
    raise SystemExit("[FAIL] app/models.py not found")

backup = f"{MODELS}.bak-{STAMP}"
shutil.copy2(MODELS, backup)
print(f"[BACKUP] {backup}")

text = MODELS.read_text(encoding="utf-8")

if "email_message_id" not in text:

    pattern = r"(source\s*=.*?\n)"

    replacement = r"""\1
    email_message_id = Column(String, nullable=True, index=True)
    email_conversation_id = Column(String, nullable=True, index=True)
"""

    text, count = re.subn(
        pattern,
        replacement,
        text,
        count=1,
        flags=re.MULTILINE
    )

    if count:
        MODELS.write_text(text, encoding="utf-8")
        print("[OK] Added email tracking fields")
    else:
        print(
            "[WARN] Could not automatically locate insertion point."
        )

else:
    print("[OK] Fields already exist")

try:
    py_compile.compile(
        str(MODELS),
        doraise=True
    )
    print("[COMPILE OK] app/models.py")

except Exception as ex:
    print(f"[COMPILE FAIL] {ex}")
    raise

print("\n[SUCCESS] Model updated")