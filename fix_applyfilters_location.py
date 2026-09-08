from pathlib import Path

p = Path("app/templates/tickets.html")
txt = p.read_text(encoding="utf-8")

start = txt.find("<script>\n\nfunction applyFilters")
if start == -1:
    print("applyFilters block not found")
    raise SystemExit(1)

block = txt[start:]
txt = txt[:start]

txt = txt.replace(
    "{% endblock %}",
    block + "\n{% endblock %}"
)

p.write_text(txt, encoding="utf-8")

print("[OK] Moved applyFilters() inside template block")