"""
helpers.py — FM Residences
Utility functions and decorators.

FIXES APPLIED:
  - BUG 11: login_required and admin_required redirected to "auth.login"
            which is the POST JSON endpoint (causes 405).
            Fixed to redirect to "auth.login_page" (the GET HTML page).
"""

from functools import wraps

from flask import redirect, url_for, current_app
from flask_jwt_extended import verify_jwt_in_request, get_jwt


# ─────────────────────────────────────────────────────────────────────────────
#  Auth decorators
# ─────────────────────────────────────────────────────────────────────────────

def login_required(f):
    """
    Decorator for routes that require a logged-in user (any role).
    Redirects to /auth/login if no valid JWT is present.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            verify_jwt_in_request()
        except Exception:
            # FIX BUG 11: was "auth.login" (POST endpoint) — now correctly "auth.login_page" (GET)
            return redirect(url_for("auth.login_page"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """
    Decorator for routes that require admin or staff role.
    Returns redirect to login if token is missing or role is insufficient.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            verify_jwt_in_request()
            claims = get_jwt()
            if claims.get("role") not in ("admin", "staff"):
                # FIX BUG 11: same fix as login_required
                return redirect(url_for("auth.login_page"))
        except Exception:
            return redirect(url_for("auth.login_page"))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────────────────────
#  File upload helpers
# ─────────────────────────────────────────────────────────────────────────────

def allowed_file(filename: str) -> bool:
    """Return True if the file extension is in the allowed set."""
    allowed = current_app.config.get("ALLOWED_EXTENSIONS", {"png", "jpg", "jpeg", "gif"})
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed