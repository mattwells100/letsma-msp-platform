from pathlib import Path
from datetime import datetime
import py_compile
import shutil
import sys

ROUTER_CANDIDATES = [
    Path("app/routers/customers.py"),
    Path("app/routers/customer.py"),
]

TEMPLATE = Path("app/templates/customer_detail.html")

ROUTER = next((path for path in ROUTER_CANDIDATES if path.exists()), None)

if ROUTER is None:
    print("[ERROR] Could not find customers router.")
    print("Checked:")
    for candidate in ROUTER_CANDIDATES:
        print(f"  {candidate}")
    sys.exit(1)

if not TEMPLATE.exists():
    print(f"[ERROR] Missing template: {TEMPLATE}")
    sys.exit(1)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
router_backup = Path(str(ROUTER) + f".bak-contact-edit-{stamp}")
template_backup = Path(str(TEMPLATE) + f".bak-contact-edit-{stamp}")

shutil.copy2(ROUTER, router_backup)
shutil.copy2(TEMPLATE, template_backup)

print(f"[BACKUP] {router_backup}")
print(f"[BACKUP] {template_backup}")


def rollback(message: str) -> None:
    print(f"[FAILED] {message}")
    shutil.copy2(router_backup, ROUTER)
    shutil.copy2(template_backup, TEMPLATE)
    print("[ROLLBACK] Original router and template restored.")
    sys.exit(1)


try:
    router_text = ROUTER.read_text(encoding="utf-8")
    template_text = TEMPLATE.read_text(encoding="utf-8")

    if "router = APIRouter" not in router_text:
        rollback(f"Could not find APIRouter declaration in {ROUTER}")

    # This endpoint uses Request.form() and opens its own short-lived DB
    # session, avoiding assumptions about the router's current dependency
    # parameter names.
    route_marker = 'name="update_customer_contact"'

    route_code = r'''

@router.post(
    "/customers/{customer_id}/contacts/{contact_id}/edit",
    name="update_customer_contact",
)
async def update_customer_contact(
    request,
    customer_id: str,
    contact_id: str,
):
    """Update a contact from the Customer Details page."""
    from fastapi.responses import RedirectResponse

    from app.database import SessionLocal
    from app.models import Contact

    db = SessionLocal()

    try:
        contact = (
            db.query(Contact)
            .filter(
                Contact.id == contact_id,
                Contact.customer_id == customer_id,
            )
            .first()
        )

        if contact is None:
            return RedirectResponse(
                url=f"/customers/{customer_id}?contact_error=not_found",
                status_code=303,
            )

        form = await request.form()

        def cleaned(field_name: str):
            value = form.get(field_name)
            if value is None:
                return None
            value = str(value).strip()
            return value or None

        name = cleaned("name")

        if not name:
            return RedirectResponse(
                url=f"/customers/{customer_id}?contact_error=name_required",
                status_code=303,
            )

        contact.name = name
        contact.first_name = cleaned("first_name")
        contact.last_name = cleaned("last_name")
        contact.email = cleaned("email")
        contact.phone = cleaned("phone")
        contact.business_phone = cleaned("business_phone")
        contact.mobile_phone = cleaned("mobile_phone")
        contact.whatsapp_number = cleaned("whatsapp_number")
        contact.role = cleaned("role")

        db.add(contact)
        db.commit()

        print(
            "CONTACT_UPDATED "
            f"customer={customer_id} "
            f"contact={contact_id} "
            f"whatsapp={contact.whatsapp_number or '-'}"
        )

        return RedirectResponse(
            url=f"/customers/{customer_id}?contact_updated=1",
            status_code=303,
        )

    except Exception as exc:
        db.rollback()

        print(
            "CONTACT_UPDATE_FAILED "
            f"customer={customer_id} "
            f"contact={contact_id} "
            f"error={repr(exc)}"
        )

        return RedirectResponse(
            url=f"/customers/{customer_id}?contact_error=save_failed",
            status_code=303,
        )

    finally:
        db.close()
'''

    if route_marker not in router_text:
        router_text = router_text.rstrip() + route_code + "\n"
        print(f"[PATCHED] Added contact update endpoint to {ROUTER}")
    else:
        print("[SKIPPED] Contact update endpoint already exists")

    contact_ui_marker = "LETSMA_CONTACT_EDITING"

    contact_ui = r'''
<!-- LETSMA_CONTACT_EDITING -->
<div class="card shadow-sm mt-4">
    <div class="card-header d-flex justify-content-between align-items-center">
        <div>
            <h5 class="mb-0">
                <i class="bi bi-person-lines-fill me-2"></i>
                Contacts
            </h5>
            <small class="text-muted">
                Maintain mobile and WhatsApp numbers for automatic ticket matching.
            </small>
        </div>
        <span class="badge bg-secondary">
            {{ customer.contacts | length }}
        </span>
    </div>

    <div class="card-body">
        {% if request.query_params.get('contact_updated') %}
        <div class="alert alert-success">
            <i class="bi bi-check-circle me-2"></i>
            Contact updated successfully.
        </div>
        {% endif %}

        {% if request.query_params.get('contact_error') == 'not_found' %}
        <div class="alert alert-danger">
            The selected contact could not be found for this customer.
        </div>
        {% elif request.query_params.get('contact_error') == 'name_required' %}
        <div class="alert alert-danger">
            Contact name is required.
        </div>
        {% elif request.query_params.get('contact_error') == 'save_failed' %}
        <div class="alert alert-danger">
            The contact could not be saved. Check the application logs for details.
        </div>
        {% endif %}

        {% if customer.contacts %}
        <div class="table-responsive">
            <table class="table table-hover align-middle mb-0">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Email</th>
                        <th>Mobile</th>
                        <th>WhatsApp</th>
                        <th class="text-end">Action</th>
                    </tr>
                </thead>
                <tbody>
                    {% for contact in customer.contacts %}
                    <tr>
                        <td>
                            <strong>{{ contact.name }}</strong>
                            {% if contact.role %}
                            <div class="small text-muted">{{ contact.role }}</div>
                            {% endif %}
                        </td>
                        <td>{{ contact.email or '-' }}</td>
                        <td>{{ contact.mobile_phone or '-' }}</td>
                        <td>
                            {% if contact.whatsapp_number %}
                            <span class="badge bg-success">
                                <i class="bi bi-whatsapp me-1"></i>
                                {{ contact.whatsapp_number }}
                            </span>
                            {% else %}
                            <span class="text-muted">Not set</span>
                            {% endif %}
                        </td>
                        <td class="text-end">
                            <button
                                type="button"
                                class="btn btn-sm btn-outline-primary"
                                data-bs-toggle="modal"
                                data-bs-target="#editContactModal{{ loop.index }}"
                            >
                                <i class="bi bi-pencil me-1"></i>
                                Edit
                            </button>
                        </td>
                    </tr>

                    <div
                        class="modal fade"
                        id="editContactModal{{ loop.index }}"
                        tabindex="-1"
                        aria-labelledby="editContactModalLabel{{ loop.index }}"
                        aria-hidden="true"
                    >
                        <div class="modal-dialog modal-lg">
                            <div class="modal-content">
                                /customers/{{ customer.id }}/contacts/{{ contact.id }}/edit
                                    <div class="modal-header">
                                        <h5
                                            class="modal-title"
                                            id="editContactModalLabel{{ loop.index }}"
                                        >
                                            Edit {{ contact.name }}
                                        </h5>
                                        <button
                                            type="button"
                                            class="btn-close"
                                            data-bs-dismiss="modal"
                                            aria-label="Close"
                                        ></button>
                                    </div>

                                    <div class="modal-body">
                                        <div class="row g-3">
                                            <div class="col-md-12">
                                                <label class="form-label">
                                                    Display Name
                                                </label>
                                                <input
                                                    type="text"
                                                    class="form-control"
                                                    name="name"
                                                    value="{{ contact.name or '' }}"
                                                    required
                                                >
                                            </div>

                                            <div class="col-md-6">
                                                <label class="form-label">
                                                    First Name
                                                </label>
                                                <input
                                                    type="text"
                                                    class="form-control"
                                                    name="first_name"
                                                    value="{{ contact.first_name or '' }}"
                                                >
                                            </div>

                                            <div class="col-md-6">
                                                <label class="form-label">
                                                    Last Name
                                                </label>
                                                <input
                                                    type="text"
                                                    class="form-control"
                                                    name="last_name"
                                                    value="{{ contact.last_name or '' }}"
                                                >
                                            </div>

                                            <div class="col-md-6">
                                                <label class="form-label">
               