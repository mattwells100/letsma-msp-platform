# fix_template_html_entities.py

from pathlib import Path

for f in Path("app/templates").rglob("*.html"):
    text = f.read_text(encoding="utf-8", errors="ignore")

    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')

    while "<a href=" in text and 'class="fai-ChatInputEntity__text' in text:
        start = text.find('<a href="https://')
        if start == -1:
            break

r = text[start:end + 4]

        marker = ">"
        p = anchor.rfind(marker)

        if p > -1:
            replacement = anchor[p + 1:-4]
            text = text.replace(anchor, replacement, 1)
        else:
            break

    f.write_text(text, encoding="utf-8")
    print("[FIXED]", f)

print("[DONE]")