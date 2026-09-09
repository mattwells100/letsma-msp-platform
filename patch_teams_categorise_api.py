# patch_teams_categorise_api.py
from pathlib import Path
from datetime import datetime
import shutil

p = Path("app/routers/teams_bot.py")

backup = f"{p}.bak-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(p, backup)

txt = p.read_text(encoding="utf-8")

txt = txt.replace(
'''from app.routers.ai_assist import (
    _parse_ticket_classification,
    AI_TICKET_CATEGORIES,
)
from app.services import azure_openai_service
import json
''',
'''import httpx
'''
)

start = txt.find("try:")
end = txt.find("return {", start)

replacement = '''
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            await client.post(
                f"http://127.0.0.1:8000/api/ai/tickets/{ticket.id}/categorise"
            )
    except Exception as exc:
        print("Teams categorisation failed:", exc)

'''

txt = txt[:start] + replacement + txt[end:]

p.write_text(txt, encoding="utf-8")

print("[OK] patched")
print("[OK] backup:", backup)
