from pathlib import Path
from datetime import datetime
import shutil

# ------------------------------------------------------------------
# Patch 1: app/services/teams_service.py
# Create ticket even when customer cannot be matched
# ------------------------------------------------------------------

svc = Path("app/services/teams_service.py")

backup = f"{svc}.bak-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(svc, backup)

txt = svc.read_text(encoding="utf-8")

old = """    ticket = None
    if customer:
        ticket = Ticket(
            ticket_number=next_ticket_number(db),
            customer_id=customer.id,
            subject=text[:80],
            description=f"Logged via Teams by {sender} in '{channel}':\\n\\n{text}",
            source=TicketSource.TEAMS,
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        log.ticket_id = ticket.id
"""

new = """    ticket = Ticket(
        ticket_number=next_ticket_number(db),
        customer_id=customer.id if customer else None,
        subject=text[:80],
        description=f"Logged via Teams by {sender} in '{channel}':\\n\\n{text}",
        source=TicketSource.TEAMS,
    )

    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    log.ticket_id = ticket.id
"""

if old in txt:
    txt = txt.replace(old, new)
else:
    print("[WARN] teams_service block not found")

svc.write_text(txt, encoding="utf-8")

# ------------------------------------------------------------------
# Patch 2: app/routers/webhooks_teams.py
# Better Teams reply text
# ------------------------------------------------------------------

router = Path("app/routers/webhooks_teams.py")

backup2 = f"{router}.bak-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(router, backup2)

txt = router.read_text(encoding="utf-8")

old = """    if ticket:
        reply_text = f"✅ Ticket #{ticket.ticket_number} logged for {ticket.customer.name}."
    else:
        reply_text = "⚠️ Message logged, but I couldn't match a customer. Please raise this in the portal or include 'for <Customer Name>'."
"""

new = """    if ticket:
        if ticket.customer:
            reply_text = (
                f"✅ Ticket #{ticket.ticket_number} logged "
                f"for {ticket.customer.name}."
            )
        else:
            reply_text = (
                f"✅ Ticket #{ticket.ticket_number} logged "
                f"(customer could not be matched)."
            )
    else:
        reply_text = "❌ Ticket creation failed."
"""

txt = txt.replace(old, new)

router.write_text(txt, encoding="utf-8")

print()
print("[OK] Teams ticket logging updated")
print(f"[OK] Backup: {backup}")
print(f"[OK] Backup: {backup2}")