# patch_ticket_whatsapp_link_ui_v3.py

from pathlib import Path
from datetime import datetime
import shutil

FILE = Path("app/templates/ticket_detail.html")

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

backup = Path(
    str(FILE) + f".bak-wa-ui-v3-{stamp}"
)

shutil.copy2(FILE, backup)

print(f"Backup: {backup}")

text = FILE.read_text(encoding="utf-8")

if "btnLinkWhatsappContact" in text:
    print("Already patched")
    raise SystemExit

insert_after = """
            &lt;/select&gt;
        &lt;/div&gt;
"""

card = r"""

{% set ticket_source = ticket.source.value if ticket.source.value is defined else ticket.source %}
{% if ticket_source == 'WhatsApp' %}

&lt;div class="card stat-card p-3 mt-3"&gt;
    &lt;h6 class="page-title"&gt;
        &lt;i class="bi bi-whatsapp"&gt;&lt;/i&gt;
        WhatsApp Linking
    &lt;/h6&gt;

    &lt;div class="alert alert-light py-2 mb-2"&gt;
        Number:
        &lt;strong id="detectedWhatsappNumber"&gt;Searching...&lt;/strong&gt;
    &lt;/div&gt;

    &lt;button
        class="btn btn-success btn-sm w-100"
        id="btnLinkWhatsappContact"
        onclick="linkWhatsappContact()"
    &gt;
        Link Current Contact
    &lt;/button&gt;

    &lt;div id="whatsappLinkResult" class="small mt-2"&gt;&lt;/div&gt;
&lt;/div&gt;

{% endif %}

"""

text = text.replace(
    insert_after,
    insert_after + card,
    1
)

js = r"""

function extractWhatsappNumber() {

    const title =
        document.querySelector("h2.page-title");

    if (!title) return null;

    const match =
        title.textContent.match(
            /unknown\s+(\d{8,15})/i
        );

    return match ? match[1] : null;
}

async function linkWhatsappContact() {

    const customerId =
        document.getElementById(
            "ticketCustomerSelect"
        ).value;

    const contactId =
        document.getElementById(
            "ticketContactSelect"
        ).value;

    const result =
        document.getElementById(
            "whatsappLinkResult"
        );

    const number =
        extractWhatsappNumber();

    if (!customerId) {
        result.innerHTML =
            '<div class="text-danger">Select customer first</div>';
        return;
    }

    if (!contactId) {
        result.innerHTML =
            '<div class="text-danger">Select end user first</div>';
        return;
    }

    if (!number) {
        result.innerHTML =
            '<div class="text-danger">Number not detected</div>';
        return;
    }

    const resp = await fetch(
        '/api/tickets/{{ ticket.id }}/link-whatsapp-contact',
        {
            method: 'POST',
            headers: {
                'Content-Type':'application/json'
            },
            body: JSON.stringify({
                customer_id: customerId,
                contact_id: contactId,
                whatsapp_number: number
            })
        }
    );

    const data = await resp.json();

    if (resp.ok) {
        result.innerHTML =
            '<div class="text-success">✅ Linked successfully</div>';
    } else {
        result.innerHTML =
            '<div class="text-danger">' +
            (data.detail || 'Failed') +
            '</div>';
    }
}

document.addEventListener(
    "DOMContentLoaded",
    function() {

        const el =
            document.getElementById(
                "detectedWhatsappNumber"
            );

        if (el) {
            el.textContent =
                extractWhatsappNumber() ||
                "Not detected";
        }
    }
);

"""

text = text.replace(
    "&lt;/script&gt;",
    js + "\n&lt;/script&gt;",
    1
)

FILE.write_text(
    text,
    encoding="utf-8"
)

print("SUCCESS")