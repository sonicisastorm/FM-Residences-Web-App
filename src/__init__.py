import os
from dotenv import load_dotenv
from flask import Flask, render_template, session, redirect, url_for, request
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_wtf import CSRFProtect
from flask_mail import Mail
from flask_babel import Babel
from datetime import timedelta

from src.models import db


load_dotenv()


bcrypt = Bcrypt()
jwt    = JWTManager()
csrf   = CSRFProtect()
mail   = Mail()
babel  = Babel()

# Supported languages — add more here later (e.g. "tr", "ar")
SUPPORTED_LANGUAGES = ["en", "az", "ru"]
DEFAULT_LANGUAGE    = "en"

# In-memory JWT blocklist — reloaded from DB on startup
jwt_blocklist: set = set()


def get_locale():
    """
    Language priority:
      1. Whatever is stored in the user's session  (set by /set-lang/<lang>)
      2. Best match from the browser's Accept-Language header
      3. Fall back to English
    """
    lang = session.get("lang")
    if lang in SUPPORTED_LANGUAGES:
        return lang
    return request.accept_languages.best_match(SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE)


def create_app() -> Flask:
    app = Flask(__name__)

    # ── Core ──────────────────────────────────────────────────────────────────
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY not set — check .env")

    # ── Database ──────────────────────────────────────────────────────────────
    basedir    = os.path.abspath(os.path.dirname(__file__))
    default_db = "sqlite:///" + os.path.join(basedir, "hotel.db")
    database_url = os.getenv("DATABASE_URL", default_db)
    # Fix Render's postgres:// → postgresql:// for SQLAlchemy 2.x
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"]        = database_url
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

    # ── Email (Brevo SMTP — works on Render, port 465/SSL is blocked) ─────────
    app.config["MAIL_SERVER"]         = os.getenv("MAIL_SERVER",   "smtp-relay.brevo.com")
    app.config["MAIL_PORT"]           = int(os.getenv("MAIL_PORT", 587))
    app.config["MAIL_USERNAME"]       = os.getenv("MAIL_USERNAME")
    app.config["MAIL_PASSWORD"]       = os.getenv("MAIL_PASSWORD")
    app.config["MAIL_USE_TLS"]        = os.getenv("MAIL_USE_TLS",  "true").lower()  == "true"
    app.config["MAIL_USE_SSL"]        = os.getenv("MAIL_USE_SSL",  "false").lower() == "false"
    app.config["MAIL_DEFAULT_SENDER"] = (
        os.getenv("MAIL_SENDER_NAME", "FM Residences"),
        os.getenv("MAIL_USERNAME", ""),
    )
    app.config["MAIL_TIMEOUT"]        = 15

    # ── ZeroBounce (optional email validation at registration) ────────────────
    app.config["ZEROBOUNCE_API_KEY"]  = os.getenv("ZEROBOUNCE_API_KEY", "")

    # ── Stripe ────────────────────────────────────────────────────────────────
    app.config["STRIPE_SECRET_KEY"]      = os.getenv("STRIPE_SECRET_KEY")
    app.config["STRIPE_PUBLISHABLE_KEY"] = os.getenv("STRIPE_PUBLISHABLE_KEY")
    app.config["STRIPE_WEBHOOK_SECRET"]  = os.getenv("STRIPE_WEBHOOK_SECRET")

    # ── Babel (i18n) ──────────────────────────────────────────────────────────
    app.config["BABEL_DEFAULT_LOCALE"]   = DEFAULT_LANGUAGE
    app.config["BABEL_SUPPORTED_LOCALES"] = SUPPORTED_LANGUAGES

    # ── Bind extensions ───────────────────────────────────────────────────────
    db.init_app(app)
    bcrypt.init_app(app)
    jwt.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)
    babel.init_app(app, locale_selector=get_locale)

    # ── JWT blocklist ─────────────────────────────────────────────────────────
    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        return jwt_payload["jti"] in jwt_blocklist

    # ── Inject helpers into every template ───────────────────────────────────
    @app.context_processor
    def inject_globals():
        from datetime import datetime, timezone
        from flask_babel import get_locale as babel_get_locale
        return {
            "now":                datetime.now(timezone.utc),
            "current_lang":       session.get("lang", DEFAULT_LANGUAGE),
            "supported_languages": SUPPORTED_LANGUAGES,
            # Human-readable language names for the switcher UI
            "language_names": {
                "en": "English",
                "az": "Azərbaycanca",
                "ru": "Русский",
            },
        }

    # ── Security headers ──────────────────────────────────────────────────────
    @app.after_request
    def apply_security_headers(response):
        response.headers["X-Frame-Options"]        = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"]       = "1; mode=block"
        response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://js.stripe.com https://code.jquery.com "
            "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com "
            "https://cdn.datatables.net https://cdn.tailwindcss.com; "
            "frame-src https://js.stripe.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
            "https://cdnjs.cloudflare.com https://cdn.datatables.net "
            "https://fonts.googleapis.com; "
            "img-src 'self' data:; "
            "font-src 'self' data: https://cdnjs.cloudflare.com https://use.fontawesome.com "
            "https://fonts.gstatic.com https://cdn.jsdelivr.net;"
        )
        return response

    with app.app_context():
        # ── Blueprints ────────────────────────────────────────────────────────
        from src.auth     import auth_bp
        from src.payments import payments_bp
        from src.admin    import admin_bp
        from src.bookings import bookings_bp

        app.register_blueprint(auth_bp)       # /auth/...
        app.register_blueprint(payments_bp)   # /payments/...
        app.register_blueprint(admin_bp)      # /admin/...
        app.register_blueprint(bookings_bp)   # /search, /bookings, /car-rentals, /cars, /checkout

        # FIX: Exempt the Stripe webhook from CSRF — Stripe posts raw bytes, no token
        csrf.exempt(payments_bp)

        # ── Language switcher route ───────────────────────────────────────────
        @app.route("/set-lang/<lang>")
        def set_language(lang):
            """
            Store the chosen language in the session, then send the user
            back to wherever they came from (or home if no referrer).
            Example: <a href="/set-lang/az">AZ</a>
            """
            if lang in SUPPORTED_LANGUAGES:
                session["lang"] = lang
            return redirect(request.referrer or url_for("index"))

        # ── Index route ───────────────────────────────────────────────────────
        @app.route("/", methods=["GET", "POST"])
        def index():
            if request.method == "POST":
                return redirect(url_for("bookings.search"), code=307)
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