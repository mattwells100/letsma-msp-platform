from pathlib import Path

print("=" * 60)
print("Applying Friendly SKU Name Fix")
print("=" * 60)

# --------------------------------------------------
# Update billing_settings.html
# --------------------------------------------------

billing_file = Path("app/templates/billing_settings.html")

if billing_file.exists():
    text = billing_file.read_text(encoding="utf-8")

    old = "{{ p.sku_part_number }}"
    new = "{{ p.friendly_name or p.sku_part_number }}"

    if old in text:
        text = text.replace(old, new)
        print("✓ Updated SKU display in billing_settings.html")

    old_dropdown = '{% for sku in known_skus %}<option value="{{ sku }}">{% endfor %}'
    new_dropdown = """
{% for sku_code, sku_name in known_skus %}
<option value="{{ sku_code }}">
    {{ sku_name }}
</option>
{% endfor %}
"""

    if old_dropdown in text:
        text = text.replace(old_dropdown, new_dropdown)
        print("✓ Updated SKU dropdown rendering")

    billing_file.write_text(text, encoding="utf-8")

else:
    print("✗ billing_settings.html not found")


# --------------------------------------------------
# Update portal.py
# --------------------------------------------------

portal_file = Path("app/routers/portal.py")

if portal_file.exists():
    text = portal_file.read_text(encoding="utf-8")

    old_block = "known_skus = sorted(priced_skus | assigned_skus)"

    new_block = """
    all_assignments = db.query(LicenseAssignment).all()

    sku_lookup = {}

    for a in all_assignments:
        sku_lookup[a.sku_part_number] = (
            a.friendly_name or a.sku_part_number
        )

    known_skus = sorted(
        sku_lookup.items(),
        key=lambda x: x[1]
    )
"""

    if old_block in text:
        text = text.replace(old_block, new_block)
        print("✓ Updated known_skus logic")
    else:
        print("! Could not find known_skus line")

    # Add LicenseAssignment import if missing
    if "LicenseAssignment" not in text:
        print("! LicenseAssignment import may need adding manually")

    portal_file.write_text(text, encoding="utf-8")

else:
    print("✗ portal.py not found")

print()
print("Done.")
print()
print("Now run:")
print("  python apply_friendly_sku_fix.py")
print()
print("Then check:")
print("  git diff app/routers/portal.py")
print("  git diff app/templates/billing_settings.html")