from pathlib import Path
from datetime import datetime
import shutil

p = Path("app/templates/tickets.html")

backup = f"{p}.bak-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(p, backup)

txt = p.read_text(encoding="utf-8")

categories = [
    "Microsoft 365",
    "Cyber Security",
    "Device Support",
    "Network",
    "Backup and Recovery",
    "Application Support",
    "User Administration",
    "Billing and Licensing",
    "General Support",
]

for cat in categories:
    old = f"<option>{cat}</option>"
    new = (
        f'<option value="{cat}" '
        f'{{% if category == "{cat}" %}}selected{{% endif %}}>'
        f'{cat}</option>'
    )
    txt = txt.replace(old, new)

# Preserve subcategory when page reloads
marker = """document.addEventListener(
    "DOMContentLoaded",
    function () {"""

inject = """
const selectedSubcategory =
    "{{ subcategory or '' }}";

document.addEventListener(
    "DOMContentLoaded",
    function () {
"""

txt = txt.replace(marker, inject, 1)

old = """    categoryMap[selected].forEach(item => {

        const option =
            document.createElement("option");

        option.value = item;
        option.textContent = item;

        sub.appendChild(option);

    });
}"""

new = """    categoryMap[selected].forEach(item => {

        const option =
            document.createElement("option");

        option.value = item;
        option.textContent = item;

        if (item === selectedSubcategory) {
            option.selected = true;
        }

        sub.appendChild(option);

    });
}"""

txt = txt.replace(old, new)

p.write_text(txt, encoding="utf-8")

print("[OK] Category selection persistence added")
print("[OK] Subcategory selection persistence added")
print("[OK] Backup:", backup)