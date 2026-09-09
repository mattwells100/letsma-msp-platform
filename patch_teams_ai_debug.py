from pathlib import Path
from datetime import datetime
import shutil

p = Path("app/routers/teams_bot.py")

backup = f"{p}.bak-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(p, backup)

txt = p.read_text(encoding="utf-8")

old = """    except Exception as exc:
        print("Teams AI classification failed:", exc)
"""

new = """    except Exception as exc:
        import traceback

        print("=" * 80)
        print("TEAMS AI CLASSIFICATION FAILED")
        print("Exception:", str(exc))
        traceback.print_exc()
        print("=" * 80)

        ticket.category = "AI ERROR"
        ticket.subcategory = str(exc)[:100]

        db.add(ticket)
        db.commit()
"""

if old not in txt:
    raise SystemExit("Could not find exception block")

txt = txt.replace(old, new)

p.write_text(txt, encoding="utf-8")

print("[OK] Added Teams AI debugging")
print("[OK] Backup:", backup)