#!/usr/bin/env python3

from pathlib import Path
from datetime import datetime
import shutil
import py_compile

STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")

MODELS = Path("app/models.py")

backup = f"{MODELS}.bak-{STAMP}"
shutil.copy2(MODELS, backup)
print(f"[BACKUP] {backup}")

text = MODELS.read_text(encoding="utf-8")

text = text.replace(
    '    email_message_id = Column(String, nullable=True, index=True)\n',
    ''
)

text = text.replace(
    '    email_conversation_id = Column(String, nullable=True, index=True)\n',
    ''
)

MODELS.write_text(
    text,
    encoding="utf-8"
)

py_compile.compile(
    str(MODELS),
    doraise=True
)

print("[OK] Removed accidental Contact fields")
print("[SUCCESS]")
