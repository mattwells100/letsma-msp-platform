from pathlib import Path
from datetime import datetime
import shutil, subprocess, sys

CONFIG = Path("app/config.py")
TICKETS = Path("app/routers/tickets.py")
SERVICE = Path("app/services/teams_reply_service.py")

for p in (CONFIG, TICKETS):
    if not p.exists():
        raise SystemExit(f"Missing {p}")

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
cfg_bak = Path(f"{CONFIG}.bak-{stamp}")
tik_bak = Path(f"{TICKETS}.bak-{stamp}")
shutil.copy2(CONFIG, cfg_bak)
shutil.copy2(TICKETS, tik_bak)

# 1. config.py additions
cfg = CONFIG.read_text(encoding="utf-8")
anchor = 'TEAMS_OUTGOING_WEBHOOK_SECRET: str = os.getenv("TEAMS_OUTGOING_WEBHOOK_SECRET", "")'
if "TEAMS_BOT_APP_ID" not in cfg:
    if anchor not in cfg:
        raise SystemExit("config anchor not found")
    cfg = cfg.replace(
        anchor,
        anchor
        + '\n    TEAMS_BOT_APP_ID: str = os.getenv("TEAMS_BOT_APP_ID", "")'
        + '\n    TEAMS_BOT_APP_SECRET: str = os.getenv("TEAMS_BOT_APP_SECRET", "")'
        + '\n    TEAMS_BOT_TENANT_ID: str = os.getenv("TEAMS_BOT_TENANT_ID", "")',
        1,
    )
    CONFIG.write_text(cfg, encoding="utf-8")

# 2. service file (correct return annotation + separate body line)
service_lines = [
    '"""Proactive Teams reply via Bot Framework (SingleTenant bot)."""',
    "from datetime import datetime",
    "from typing import Optional",
    "",
    "import httpx",
    "from sqlalchemy.orm import Session",
    "",
    "from app.config import settings",
    "from app.models import Ticket",
    "",
    "",
    "async def _get_token() -> Optional[str]:",
    "    if not (",
    "        settings.TEAMS_BOT_APP_ID",
    "        and settings.TEAMS_BOT_APP_SECRET",
    "        and settings.TEAMS_BOT_TENANT_ID",
    "    ):",
    "        return None",
    "",
    "    url = (",
    '        "https://login.microsoftonline.com/"',
    '        f"{settings.TEAMS_BOT_TENANT_ID}/oauth2/v2.0/token"',
    "    )",
    "    data = {",
    '        "grant_type": "client_credentials",',
    '        "client_id": settings.TEAMS_BOT_APP_ID,',
    '        "client_secret": settings.TEAMS_BOT_APP_SECRET,',
    '        "scope": "https://api.botframework.com/.default",',
    "    }",
    "",
    "    async with httpx.AsyncClient(timeout=30.0) as client:",
    "        resp = await client.post(url, data=data)",
    "        resp.raise_for_status()",
    '        return resp.json().get("access_token")',
    "",
    "",
    "async def send_teams_reply(",
    "    db: Session,",
    "    ticket: Ticket,",
    "    message: str,",
    '    author: str = "Letsma",',
    ") -> Optional[dict]:",
    "    conversation_id = ticket.conversation_id",
    "    service_url = ticket.external_ref",
    "",
    "    if not conversation_id or not service_url:",
    "        return None",
    "",
    "    token = await _get_token()",
    "    if not token:",
    "        return None",
    "",
    "    url = (",
    "        f\"{service_url.rstrip('/')}/v3/conversations/\"",
    '        f"{conversation_id}/activities"',
    "    )",
    '    body = {"type": "message", "text": message}',
    "",
    "    async with httpx.AsyncClient(timeout=30.0) as client:",
    "        resp = await client.post(",
    "            url,",
    '            headers={"Authorization": f"Bearer {token}"},',
    "            json=body,",
    "        )",
    "        resp.raise_for_status()",
    "",
    "    ticket.updated_at = datetime.utcnow()",
    "    db.commit()",
    '    return {"status": resp.status_code}',
    "",
]
SERVICE.write_text("\n".join(service_lines), encoding="utf-8")

# 3. tickets.py hook
tik = TICKETS.read_text(encoding="utf-8")

if "from app.services.teams_reply_service import send_teams_reply" not in tik:
    tik = tik.replace(
        "from app.services.whatsapp_service import send_ticket_reply",
        "from app.services.whatsapp_service import send_ticket_reply\n"
        "from app.services.teams_reply_service import send_teams_reply",
        1,
    )

teams_block = '''    if (
        ticket.source == models.TicketSource.TEAMS
        and not comment.is_internal_note
    ):
        try:
            print(f"TEAMS_REPLY_START ticket={ticket.id}")
            asyncio.run(
                send_teams_reply(
                    db=db,
                    ticket=ticket,
                    message=comment.message,
                    author=comment.author,
                )
            )
            print(f"TEAMS_REPLY_SUCCESS ticket={ticket.id}")
        except Exception as ex:
            import traceback
            print(f"TEAMS_REPLY_FAILED ticket={ticket.id} error={ex}")
            traceback.print_exc()

    return {"id": comment.id, "created_at": comment.created_at}'''

if "TEAMS_REPLY_START" not in tik:
    tik = tik.replace(
        '    return {"id": comment.id, "created_at": comment.created_at}',
        teams_block,
        1,
    )

TICKETS.write_text(tik, encoding="utf-8")

# verify + compile
errors = []
cfgtxt = CONFIG.read_text(encoding="utf-8")
tiktxt = TICKETS.read_text(encoding="utf-8")

for needle in ("TEAMS_BOT_APP_ID", "TEAMS_BOT_APP_SECRET", "TEAMS_BOT_TENANT_ID"):
    if needle not in cfgtxt:
        errors.append(f"Missing in config: {needle}")

if "send_teams_reply" not in tiktxt:
    errors.append("Teams import/hook missing in tickets.py")
if "TEAMS_REPLY_START" not in tiktxt:
    errors.append("Teams block missing in tickets.py")
if not SERVICE.exists():
    errors.append("service file missing")

for p in (CONFIG, TICKETS, SERVICE):
    r = subprocess.run([sys.executable, "-m", "py_compile", str(p)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        errors.append(f"Compile failed {p}:\n{r.stdout}{r.stderr}")

if errors:
    shutil.copy2(cfg_bak, CONFIG)
    shutil.copy2(tik_bak, TICKETS)
    if SERVICE.exists():
        SERVICE.unlink()
    print("[FAILED] Rolled back.")
    for e in errors:
        print(e)
    raise SystemExit(1)

print("[OK] config.py updated")
print("[OK] teams_reply_service.py created")
print("[OK] tickets.py hooked")
print("[OK] All files compile")
print(f"[OK] Backups: {cfg_bak.name}, {tik_bak.name}")
