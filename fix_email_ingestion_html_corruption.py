from pathlib import Path
import shutil
from datetime import datetime
import py_compile

target = Path("app/services/email_ingestion_service.py")

backup = str(target) + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(target, backup)

print("[BACKUP]", backup)

lines = target.read_text(encoding="utf-8", errors="ignore").splitlines()

new_lines = []

for line in lines:

    if line.strip().startswith("GRAPH_BASE ="):
        line = 'GRAPH_BASE = "https://graph.microsoft.com/v1.0"'

    if "token_url =" in line:
        line = '    token_url = f"https://login.microsoftonline.com/{settings.HELPDESK_GRAPH_TENANT_ID}/oauth2/v2.0/token"'

    if '"scope":' in line:
        line = '                "scope": "https://graph.microsoft.com/.default",'

    line = line.replace("</a>", "")
    line = line.replace("&quot;", '"')
    line = line.replace("&gt;", ">")
    line = line.replace("&lt;", "<")

    while "<a " in line:
        start = line.find("<a ")
        end = line.find(">", start)
        if end == -1:
            break
        line = line[:start] + line[end + 1:]

    new_lines.append(line)

target.write_text("\n".join(new_lines), encoding="utf-8")

print("[OK] Cleanup complete")

try:
    py_compile.compile(str(target), doraise=True)
    print("[COMPILE OK]")
except Exception as exc:
    print("[COMPILE FAIL]")
    print(exc)