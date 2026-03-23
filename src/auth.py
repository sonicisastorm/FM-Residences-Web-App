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
"""

from datetime import datetime, timezone

from flask import (Blueprint, request, jsonify, session, redirect,
                   url_for, render_template, flash)
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
#  Register
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/register", methods=["POST"])
def register():
    """Register a new user account. Accepts JSON or form data."""
    data = request.get_json() or request.form

    if not all(data.get(f) for f in ("username", "email", "password")):
        return jsonify({"error": "Username, email, and password are required"}), 400

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

    try:
        user = User(username=data["username"], email=email, role="user")
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

def _send_verification_email(user: User, token: str):
    try:
        verify_url = url_for("auth.verify_email", token=token, _external=True)
        msg = Message(
            subject    = "FM Residences — Verify your email",
            recipients = [user.email],
            html       = f"""
                <h2>Welcome to FM Residences, {user.username}!</h2>
                <p>Click the button below to verify your email address:</p>
                <a href="{verify_url}"
                   style="background:#C9A84C;color:#000;padding:12px 24px;
                          text-decoration:none;border-radius:6px;font-weight:bold;">
                   Verify Email
                </a>
                <p style="color:#666;margin-top:16px;">
                  Link expires in 24 hours.
                </p>
            """,
        )
        mail.send(msg)
    except Exception:
        pass   # Don't block registration if email is misconfigured in dev


def _send_reset_email(user: User, token: str):
    try:
        # FIX BUG 9: token goes in query param, not URL path
        reset_url = url_for("auth.reset_password_page", token=token, _external=True)
        msg = Message(
            subject    = "FM Residences — Password Reset",
            recipients = [user.email],
            html       = f"""
                <h2>Password Reset Request</h2>
                <p>Click below to reset your password. This link expires in 1 hour.</p>
                <a href="{reset_url}"
                   style="background:#C9A84C;color:#000;padding:12px 24px;
                          text-decoration:none;border-radius:6px;font-weight:bold;">
                   Reset Password
                </a>
                <p style="color:#666;margin-top:16px;">
                  If you didn't request this, ignore this email.
                </p>
            """,
        )
        mail.send(msg)
    except Exception:
        pass