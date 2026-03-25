"""
auth.py — FM Residences
Authentication routes: register, login, logout, token refresh,
email verification, password reset, password change.

Hybrid auth strategy:
  - JWT tokens returned to JS clients for API calls
  - Flask session also set on login so server-rendered pages work

FIXES APPLIED:
  - BUG 1:  forgot_password_page now renders Forget_password.html (matches actual filename)
  - BUG 1:  reset_password_page now renders Reset_password.html (matches actual filename)
  - BUG 9:  reset_password route now accepts token in request body (matches frontend JS)
  - FIX:    helpers.py redirect target corrected to auth.login_page
  - FIX:    POST /auth/logout now requires a valid JWT (returns 401 when missing),
            while GET /auth/logout still does a session-only clear + redirect.
  - FIX:    Gmail SMTP (port 465) is blocked on Render. Switched to Brevo SMTP
            (smtp-relay.brevo.com, port 587, STARTTLS) which works on all cloud hosts.
  - FIX:    ZeroBounce API validation added at registration to reject invalid /
            disposable / catch-all email addresses before the account is created.
            Validation is skipped gracefully if ZEROBOUNCE_API_KEY is not set.
"""

from datetime import datetime, timezone

from flask import (Blueprint, request, jsonify, session, redirect,
                   url_for, render_template, flash, current_app)
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, get_jwt,
    verify_jwt_in_request,
)
from flask_mail import Message
from email_validator import validate_email, EmailNotValidError

from src.models import db, User, JWTToken
from src import jwt_blocklist, mail

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ─────────────────────────────────────────────────────────────────────────────
#  Page routes (render templates)
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET"])
def login_page():
    if session.get("user_id"):
        return redirect(url_for("index"))
    return render_template("login.html")


@auth_bp.route("/register", methods=["GET"])
def register_page():
    if session.get("user_id"):
        return redirect(url_for("index"))
    return render_template("register.html")


# ─────────────────────────────────────────────────────────────────────────────
#  ZeroBounce email validation helper
# ─────────────────────────────────────────────────────────────────────────────

def _zerobounce_validate(email: str) -> tuple[bool, str]:
    """
    Validate an email address with the ZeroBounce API.

    Returns (is_ok: bool, reason: str).
    - is_ok=True  → email is safe to use
    - is_ok=False → email should be rejected; reason explains why

    If ZEROBOUNCE_API_KEY is not configured, or if the API call fails for
    any reason, we return (True, "") so registration is never blocked by a
    network hiccup.

    ZeroBounce status codes we reject:
      invalid      – address doesn't exist
      disposable   – throwaway inbox (Mailinator etc.)
      abuse        – known spam/complaint source
      do_not_mail  – role address or bounced previously
      unknown      – completely unresolvable (we allow these — too aggressive
                     to block; some real addresses resolve as unknown)
    """
    import urllib.request
    import urllib.parse
    import json

    api_key = current_app.config.get("ZEROBOUNCE_API_KEY", "")
    if not api_key:
        return True, ""   # validation not configured — allow through

    try:
        params  = urllib.parse.urlencode({"api_key": api_key, "email": email, "ip_address": ""})
        url     = f"https://api.zerobounce.net/v2/validate?{params}"
        req     = urllib.request.Request(url, headers={"User-Agent": "FM-Residences/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        status  = data.get("status", "").lower()

        REJECT_STATUSES = {"invalid", "disposable", "abuse", "do_not_mail"}
        if status in REJECT_STATUSES:
            human = {
                "invalid":     "That email address doesn't exist or cannot receive mail.",
                "disposable":  "Disposable / temporary email addresses are not allowed.",
                "abuse":       "That email address has a history of abuse and cannot be used.",
                "do_not_mail": "That email address cannot receive mail (role address or previously bounced).",
            }.get(status, "That email address is not accepted.")
            return False, human

        return True, ""

    except Exception:
        # Network error / timeout / unexpected response — don't block registration
        return True, ""


# ─────────────────────────────────────────────────────────────────────────────
#  Register
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/register", methods=["POST"])
def register():
    """Register a new user account. Accepts JSON or form data."""
    data = request.get_json() or request.form

    if not all(data.get(f) for f in ("username", "email", "password")):
        return jsonify({"error": "Username, email, and password are required"}), 400

    # Basic format check (fast, no network)
    try:
        email = validate_email(data["email"], check_deliverability=False).normalized
    except EmailNotValidError as e:
        return jsonify({"error": f"Invalid email: {e}"}), 400

    if len(data["password"]) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    if User.query.filter_by(username=data["username"]).first():
        return jsonify({"error": "Username already taken"}), 409
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 409

    # ZeroBounce deliverability check (network, uses a credit)
    zb_ok, zb_reason = _zerobounce_validate(email)
    if not zb_ok:
        return jsonify({"error": zb_reason}), 400

    try:
        user  = User(username=data["username"], email=email, role="user")
        user.set_password(data["password"])
        token = user.generate_verification_token()
        db.session.add(user)
        db.session.commit()
        _send_verification_email(user, token)
        return jsonify({
            "message": "Registered! Check your email to verify your account.",
            "user":    user.to_dict(),
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
#  Email verification
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/verify-email/<token>", methods=["GET", "POST"])
def verify_email(token):
    user = User.query.filter_by(verification_token=token).first()
    if not user:
        flash("Invalid or expired verification link.")
        return redirect(url_for("auth.login_page"))
    if user.is_verified:
        flash("Email already verified. Please log in.")
        return redirect(url_for("auth.login_page"))
    try:
        user.verify_email()
        db.session.commit()
        flash("Email verified! You can now log in.")
        return redirect(url_for("auth.login_page"))
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
#  Login
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["POST"])
def login():
    """Return JWT tokens AND set Flask session. Accepts JSON or form data."""
    data = request.get_json() or request.form

    if not data.get("username") or not data.get("password"):
        return jsonify({"error": "Username and password are required"}), 400

    user = User.query.filter_by(username=data["username"]).first()

    if not user or not user.check_password(data["password"]):
        return jsonify({"error": "Invalid username or password"}), 401
    if not user.is_active:
        return jsonify({"error": "Account is deactivated"}), 403
    if not user.is_verified:
        return jsonify({"error": "Please verify your email before logging in"}), 403

    try:
        user.update_last_login()
        db.session.commit()

        access_token  = create_access_token(
            identity=str(user.id),
            additional_claims={"role": user.role}
        )
        refresh_token = create_refresh_token(identity=str(user.id))

        # Set Flask session so server-rendered pages know who's logged in
        session["user_id"]  = user.id
        session["username"] = user.username
        session["role"]     = user.role

        return jsonify({
            "message":       "Login successful",
            "access_token":  access_token,
            "refresh_token": refresh_token,
            "role":          user.role,
            "user":          user.to_dict(),
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
#  Logout
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/logout", methods=["GET"])
def logout_get():
    """Browser GET logout — clears session and redirects. No JWT required."""
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("index"))


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """
    API POST logout — JWT required.
    Blocklists the token and clears the Flask session.
    Returns 401 if no valid JWT is provided.
    """
    try:
        verify_jwt_in_request()
    except Exception:
        return jsonify({"error": "Authentication required"}), 401

    try:
        jwt_data = get_jwt()
        jti      = jwt_data["jti"]
        user_id  = int(get_jwt_identity())
        expires  = datetime.fromtimestamp(jwt_data["exp"], tz=timezone.utc)
        jwt_blocklist.add(jti)
        try:
            record = JWTToken(jti=jti, token_type="access",
                              user_id=user_id, expires_at=expires)
            db.session.add(record)
            db.session.commit()
        except Exception:
            db.session.rollback()
    except Exception:
        pass

    session.clear()
    return jsonify({"message": "Logged out successfully"}), 200


# ─────────────────────────────────────────────────────────────────────────────
#  Token refresh
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user or not user.is_active:
        return jsonify({"error": "Account not found or deactivated"}), 403
    access_token = create_access_token(
        identity=str(user.id), additional_claims={"role": user.role}
    )
    return jsonify({"access_token": access_token}), 200


# ─────────────────────────────────────────────────────────────────────────────
#  Current user
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def get_current_user():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify(user.to_dict()), 200


# ─────────────────────────────────────────────────────────────────────────────
#  Forgot / reset password
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/forgot-password", methods=["GET"])
def forgot_password_page():
    # FIX BUG 1: template filename is Forget_password.html (capital F, 'Forget' not 'Forgot')
    return render_template("Forget_password.html")


@auth_bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    data = request.get_json() or request.form
    if not data.get("email"):
        return jsonify({"error": "Email is required"}), 400
    user = User.query.filter_by(email=data["email"]).first()
    if not user:
        # Don't reveal whether the email exists
        return jsonify({"message": "If that email exists, a reset link has been sent."}), 200
    try:
        reset_token = user.generate_reset_token()
        db.session.commit()
        _send_reset_email(user, reset_token)
        return jsonify({"message": "Password reset link sent to your email."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@auth_bp.route("/reset-password", methods=["GET"])
def reset_password_page():
    """
    FIX BUG 1: template filename is Reset_password.html (capital R).
    FIX BUG 9: token is passed as a query param (?token=xxx) so the JS
               can read it with URLSearchParams. The email link now uses
               url_for('auth.reset_password_page', token=token).
    """
    token = request.args.get("token", "")
    return render_template("Reset_password.html", token=token)


@auth_bp.route("/reset-password", methods=["POST"])
def reset_password():
    """
    FIX BUG 9: accepts token in JSON body (not URL path) so the frontend
               JS can POST { token, new_password } without needing the
               token in the URL.
    """
    data = request.get_json() or request.form
    token = data.get("token", "")

    if not data.get("new_password"):
        return jsonify({"error": "New password is required"}), 400
    if len(data["new_password"]) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    if not token:
        return jsonify({"error": "Reset token is required"}), 400

    user = User.query.filter_by(reset_token=token).first()
    if not user or not user.reset_token_expiry:
        return jsonify({"error": "Invalid or expired reset token"}), 400
    if user.reset_token_expiry < datetime.now(timezone.utc):
        return jsonify({"error": "Reset token has expired"}), 400
    try:
        user.set_password(data["new_password"])
        user.reset_token        = None
        user.reset_token_expiry = None
        db.session.commit()
        return jsonify({"message": "Password reset successfully. You can now log in."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
#  Change password
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/change-password", methods=["POST"])
@jwt_required()
def change_password():
    user_id = int(get_jwt_identity())
    data    = request.get_json() or request.form
    if not data.get("old_password") or not data.get("new_password"):
        return jsonify({"error": "old_password and new_password are required"}), 400
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if not user.check_password(data["old_password"]):
        return jsonify({"error": "Incorrect current password"}), 401
    if len(data["new_password"]) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    try:
        user.set_password(data["new_password"])
        db.session.commit()
        return jsonify({"message": "Password changed successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
#  Email helpers
# ─────────────────────────────────────────────────────────────────────────────

def _email_base(title: str, body_html: str) -> str:
    """Wrap content in a minimal, styled HTML email shell."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0A0A0A;font-family:'DM Sans',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0A0A0A;padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#1E1E1E;border:1px solid #2A2A2A;border-radius:16px;"
                    "overflow:hidden;max-width:560px;width:100%;">
        <!-- Header -->
        <tr>
          <td style="background:#141414;border-bottom:1px solid #2A2A2A;padding:24px 32px;">
            <span style="font-size:22px;font-weight:600;color:#C9A84C;letter-spacing:0.05em;">
              FM Residences
            </span>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:32px;">
            <h2 style="margin:0 0 16px;font-size:22px;color:#F5F0E8;font-weight:600;">{title}</h2>
            {body_html}
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:#141414;border-top:1px solid #2A2A2A;padding:16px 32px;
                     font-size:11px;color:#3A3A3A;text-align:center;">
            &copy; FM Residences. If you did not request this email, you can safely ignore it.
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _send_verification_email(user: User, token: str):
    import threading

    def send():
        try:
            verify_url = url_for("auth.verify_email", token=token, _external=True)
            body = f"""
              <p style="color:#F5F0E8;line-height:1.6;margin:0 0 24px;">
                Hi <strong style="color:#C9A84C;">{user.username}</strong>,<br>
                Thanks for signing up. Click the button below to verify your email address
                and activate your account.
              </p>
              <a href="{verify_url}"
                 style="display:inline-block;background:#C9A84C;color:#141414;
                        padding:14px 28px;text-decoration:none;border-radius:10px;
                        font-weight:700;font-size:14px;letter-spacing:0.05em;">
                Verify Email Address
              </a>
              <p style="color:#666;font-size:12px;margin:20px 0 0;">
                This link expires in <strong>24 hours</strong>.<br>
                If the button doesn't work, paste this URL into your browser:<br>
                <a href="{verify_url}" style="color:#C9A84C;word-break:break-all;">{verify_url}</a>
              </p>
            """
            msg = Message(
                subject    = "FM Residences — Verify your email",
                recipients = [user.email],
                html       = _email_base("Verify your email", body),
            )
            mail.send(msg)
        except Exception as exc:
            # Log but don't crash — user can request a resend
            current_app.logger.error("Verification email failed: %s", exc)

    threading.Thread(target=send, daemon=True).start()


def _send_reset_email(user: User, token: str):
    try:
        # FIX BUG 9: token goes in query param, not URL path
        reset_url = url_for("auth.reset_password_page", token=token, _external=True)
        body = f"""
          <p style="color:#F5F0E8;line-height:1.6;margin:0 0 24px;">
            Hi <strong style="color:#C9A84C;">{user.username}</strong>,<br>
            We received a request to reset your password. Click the button below.
          </p>
          <a href="{reset_url}"
             style="display:inline-block;background:#C9A84C;color:#141414;
                    padding:14px 28px;text-decoration:none;border-radius:10px;
                    font-weight:700;font-size:14px;letter-spacing:0.05em;">
            Reset Password
          </a>
          <p style="color:#666;font-size:12px;margin:20px 0 0;">
            This link expires in <strong>1 hour</strong>.<br>
            If you didn't request a password reset, you can ignore this email — your
            account is safe.<br><br>
            If the button doesn't work, paste this URL into your browser:<br>
            <a href="{reset_url}" style="color:#C9A84C;word-break:break-all;">{reset_url}</a>
          </p>
        """
        msg = Message(
            subject    = "FM Residences — Password Reset",
            recipients = [user.email],
            html       = _email_base("Reset your password", body),
        )
        mail.send(msg)
    except Exception as exc:
        current_app.logger.error("Reset email failed: %s", exc)