import os
from dotenv import load_dotenv
from flask import Flask, render_template
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_wtf import CSRFProtect
from flask_mail import Mail
from datetime import timedelta

from src.models import db


load_dotenv()


bcrypt = Bcrypt()
jwt    = JWTManager()
csrf   = CSRFProtect()
mail   = Mail()

# In-memory JWT blocklist — reloaded from DB on startupp
jwt_blocklist: set = set()


def create_app() -> Flask:
    app = Flask(__name__)

    # ── Core ──────────────────────────────────────────────────────────────────
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY not set — check .env")

    # ── Database ──────────────────────────────────────────────────────────────
    basedir    = os.path.abspath(os.path.dirname(__file__))
    default_db = "sqlite:///" + os.path.join(basedir, "hotel.db")
    app.config["SQLALCHEMY_DATABASE_URI"]        = os.getenv("DATABASE_URL", default_db)
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # ── JWT ───────────────────────────────────────────────────────────────────
    app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY")
    if not app.config["JWT_SECRET_KEY"]:
        raise RuntimeError("JWT_SECRET_KEY not set — check .env")

    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(
        minutes=int(os.getenv("JWT_ACCESS_EXPIRES_MINUTES", 30))
    )

    app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=int(os.getenv("JWT_REFRESH_EXPIRES_DAYS", 7)))
    app.config["JWT_TOKEN_LOCATION"]        = ["headers"]
    app.config["JWT_HEADER_NAME"]           = "Authorization"
    app.config["JWT_HEADER_TYPE"]           = "Bearer"

    # ── Session cookies ───────────────────────────────────────────────────────
    app.config["SESSION_COOKIE_SECURE"]   = os.getenv("FLASK_ENV") == "production"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # ── Uploads ───────────────────────────────────────────────────────────────
    app.config["UPLOAD_FOLDER"]      = os.getenv("UPLOAD_FOLDER", "static/uploads/")
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
    app.config["ALLOWED_EXTENSIONS"] = {"png", "jpg", "jpeg", "gif"}

    # ── Email ─────────────────────────────────────────────────────────────────
    app.config["MAIL_SERVER"]         = os.getenv("MAIL_SERVER",  "smtp.gmail.com")
    app.config["MAIL_PORT"]           = int(os.getenv("MAIL_PORT", 465))
    app.config["MAIL_USERNAME"]       = os.getenv("MAIL_USERNAME")
    app.config["MAIL_PASSWORD"]       = os.getenv("MAIL_PASSWORD")
    app.config["MAIL_USE_TLS"]        = os.getenv("MAIL_USE_TLS", "false").lower() == "true"
    app.config["MAIL_USE_SSL"]        = os.getenv("MAIL_USE_SSL", "true").lower()  == "true"
    app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_USERNAME")

    # ── Stripe ────────────────────────────────────────────────────────────────
    app.config["STRIPE_SECRET_KEY"]      = os.getenv("STRIPE_SECRET_KEY")
    app.config["STRIPE_PUBLISHABLE_KEY"] = os.getenv("STRIPE_PUBLISHABLE_KEY")
    app.config["STRIPE_WEBHOOK_SECRET"]  = os.getenv("STRIPE_WEBHOOK_SECRET")

    # ── Bind extensions ───────────────────────────────────────────────────────
    db.init_app(app)
    bcrypt.init_app(app)
    jwt.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)

    # ── JWT blocklist ─────────────────────────────────────────────────────────
    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        return jwt_payload["jti"] in jwt_blocklist

    # ── Inject `now` into every template ─────────────────────────────────────
    @app.context_processor
    def inject_now():
        from datetime import datetime, timezone
        return {"now": datetime.now(timezone.utc)}

    # ── Security headers ──────────────────────────────────────────────────────
    @app.after_request
    def apply_security_headers(response):
        response.headers["X-Frame-Options"]        = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"]       = "1; mode=block"
        response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            # Tailwind CDN, Stripe, jQuery, Bootstrap Datepicker, DataTables, FontAwesome
            "script-src 'self' 'unsafe-inline' https://js.stripe.com https://code.jquery.com "
            "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com "
            "https://cdn.datatables.net https://cdn.tailwindcss.com; "
            "frame-src https://js.stripe.com; "
            # Tailwind CDN injects a <style> tag — needs 'unsafe-inline'
            # Google Fonts stylesheet must be allowed explicitly
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
            "https://cdnjs.cloudflare.com https://cdn.datatables.net "
            "https://fonts.googleapis.com; "
            "img-src 'self' data:; "
            # Google Fonts serves font files from fonts.gstatic.com
            "font-src 'self' data: https://cdnjs.cloudflare.com https://use.fontawesome.com "
            "https://fonts.gstatic.com https://cdn.jsdelivr.net;"
        )
        return response

    with app.app_context():
        # ── Blueprints ────────────────────────────────────────────────────────
        from src.auth     import auth_bp
        from src.payments import payments_bp
        from src.admin    import admin_bp
        # FIX #1: was `from src.bookings` but file was named booking.py
        # File has been renamed to bookings.py
        from src.bookings import bookings_bp

        app.register_blueprint(auth_bp)       # /auth/...
        app.register_blueprint(payments_bp)   # /payments/...
        app.register_blueprint(admin_bp)      # /admin/...
        app.register_blueprint(bookings_bp)   # /search, /bookings, /car-rentals, /cars, /checkout

        # FIX: Exempt the Stripe webhook from CSRF — Stripe posts raw bytes, no token
        csrf.exempt(payments_bp)

        # ── Index route ───────────────────────────────────────────────────────
        @app.route("/", methods=["GET", "POST"])
        def index():
            from flask import request, redirect, url_for
            if request.method == "POST":
                return redirect(url_for("bookings.search"), code=307)  # 307 preserves POST body
            return render_template("index.html")

        # ── Create all DB tables ──────────────────────────────────────────────
        db.create_all()

        # ── Reload JWT blocklist from DB ──────────────────────────────────────
        try:
            from src.models import JWTToken
            from datetime import datetime, timezone
            now     = datetime.now(timezone.utc)
            revoked = JWTToken.query.filter(JWTToken.expires_at > now).all()
            for r in revoked:
                jwt_blocklist.add(r.jti)
        except Exception:
            pass   # DB doesn't exist yet on first run

    return app