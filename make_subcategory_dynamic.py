from pathlib import Path
from datetime import datetime
import shutil

p = Path("app/templates/tickets.html")

text = p.read_text(encoding="utf-8")

backup = f"{p}.bak-subcategory-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(p, backup)

# Replace textbox with dropdown
old = """
<input
            id="subcategoryFilter"
            class="form-control"
            placeholder="Subcategory"
            onchange="applyFilters()">
"""

new = """
<select
            id="subcategoryFilter"
            class="form-select"
            onchange="applyFilters()">
    <option value="">All Subcategories</option>
</select>
"""

text = text.replace(old, new)

# Add dynamic javascript before closing script
marker = """
function applyFilters() {
"""

inject = """
const categoryMap = {
    "Microsoft 365": [
        "Outlook",
        "Exchange Online",
        "Teams",
        "SharePoint",
        "OneDrive",
        "Licence Management",
        "MFA and Authentication",
        "Entra ID",
        "Other"
    ],
    "Cyber Security": [
        "Microsoft Defender",
        "Phishing",
        "Malware",
        "Account Compromise",
        "Conditional Access",
        "Security Alert",
        "Other"
    ],
    "Device Support": [
        "Windows",
        "Mobile Device",
        "Printer",
        "Hardware",
        "Performance",
        "Updates",
        "Other"
    ],
    "Network": [
        "Internet",
        "Wi-Fi",
        "VPN",
        "DNS",
        "Firewall",
        "Other"
    ],
    "Backup and Recovery": [
        "Backup Failure",
        "File Restore",
        "Disaster Recovery",
        "Other"
    ],
    "Application Support": [
        "Line of Business Application",
        "Third-Party Application",
        "Installation",
        "Other"
    ],
    "User Administration": [
        "New User",
        "Leaver",
        "Password Reset",
        "Permissions",
        "Shared Mailbox",
        "Other"
    ],
    "Billing and Licensing": [
        "Invoice Query",
        "Licence Change",
        "Subscription",
        "Other"
    ],
    "General Support": [
        "How-To",
        "Service Request",
        "Incident",
        "Other"
    ]
};

function updateSubcategories() {

    const category =
        document.getElementById("categoryFilter").value;

    const sub =
        document.getElementById("subcategoryFilter");

    sub.innerHTML =
        '<option value="">All Subcategories</option>';

    if (!categoryMap[category]) {
        return;
    }

    categoryMap[category].forEach(item => {
        const option =
            document.createElement("option");

        option.value = item;
        option.textContent = item;

        sub.appendChild(option);
    });
}

document.addEventListener(
    "DOMContentLoaded",
    function () {

        const category =
            document.getElementById(
                "categoryFilter"
            );

        if (category) {
            category.addEventListener(
                "change",
                updateSubcategories
            );

            updateSubcategories();
        }
    }
);

function applyFilters() {
"""

text = text.