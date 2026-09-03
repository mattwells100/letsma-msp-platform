"""
app/deps.py

Shared FastAPI dependencies for enforcing staff login (see
app/routers/auth.py for the actual login flow). Two variants, since this
app mixes JSON APIs and server-rendered HTML pages:

  - require_login_json: for JSON API routers (customers, tickets, billing,
    etc.) - returns a clean 401 JSON error if not logged in. Applied via
    app.include_router(x.router, dependencies=[Depends(require_login_json)])
    in main.py, so NO individual router files need to be touched.

  - require_login_page: for server-rendered HTML page routes (portal.py) -
    redirects the browser to /auth/login if not logged in. NOT applied
    blanket-wide via include_router, since portal.py also contains the
    external customer-facing /portal/{customer_id} route, which must stay
    ungated (customers don't have Letsma Azure accounts). Instead, add
    `_=Depends(require_login_page)` as a parameter to each STAFF-facing
    route function in portal.py individually (dashboard, customers_page,
    tickets_page, etc.) - deliberately NOT to customer_portal().

Both simply check request.session["user"], which is populated by
app/routers/auth.py on successful login and cleared on logout. Requires
SessionMiddleware to be registered in app/main.py (uses settings.SECRET_KEY
to sign the session cookie - itsdangerous, already a dependency).
"""
from fastapi import Request, HTTPException


def get_current_user(request: Request):
    """Returns the logged-in user's session dict, or None if not logged in.
    Safe to call anywhere - never raises."""
    return request.session.get("user")


def require_login_json(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated - please log in via the web UI first.")
    return user


def require_login_page(request: Request):
    user = request.session.get("user")
    if not user:
        # 303 See Other + Location header - browsers follow this as a
        # redirect automatically, same effect as a RedirectResponse but
        # usable from within a dependency (which can only return a value
        # or raise, not directly return a Response).
        raise HTTPException(status_code=303, headers={"Location": "/auth/login"})
    return user
