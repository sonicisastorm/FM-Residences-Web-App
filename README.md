# FM Residences

A full-stack hotel management web application built with Flask. Guests can search and book rooms, rent cars, and pay securely via Stripe. Staff manage inventory and reservations through an admin panel.

**Live:** [https://fm-residences-web-app.onrender.com](https://fm-residences-web-app.onrender.com)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, Flask 3.0 |
| ORM | SQLAlchemy 2.0 + Flask-SQLAlchemy 3.1 |
| Auth | Flask-JWT-Extended (API tokens) + Flask session (server-rendered pages) |
| Payments | Stripe (PaymentIntents API) |
| Email | Brevo SMTP (port 587 / STARTTLS) via Flask-Mail |
| Email Validation | ZeroBounce API (optional — rejects invalid/disposable addresses) |
| Templates | Jinja2 + Tailwind CSS (CDN) + Bootstrap Icons |
| Database | PostgreSQL (production) / SQLite (local dev & tests) |
| Tests | pytest + pytest-flask |
| CI/CD | GitHub Actions → Render deploy hook |
| Hosting | Render (web service + managed PostgreSQL) |

---

## Project Structure

```
FM-Residences-Web-App/
├── src/
│   ├── __init__.py          # App factory, extensions, blueprints, context processors
│   ├── models.py            # User, Room, RoomAvailability, Booking,
│   │                        #   Cars, CarRental, Payment, JWTToken
│   ├── auth.py              # Register, login, logout, email verification,
│   │                        #   forgot/reset password, ZeroBounce validation
│   ├── bookings.py          # Room search, bookings, car rentals,
│   │                        #   checkout, my-bookings
│   ├── admin.py             # Dashboard, room/car/user CRUD,
│   │                        #   staff registration, booking & rental management
│   ├── payments.py          # Stripe PaymentIntent creation, webhook,
│   │                        #   direct confirm (no-webhook fallback), refunds
│   ├── helpers.py           # Auth decorators
│   ├── room_search.py       # Availability search logic
│   ├── static/              # Uploaded images, JS
│   └── templates/
│       ├── layout.html              # Base template (nav with mobile menu, footer)
│       ├── index.html               # Landing page + date picker search form
│       ├── offer_rooms.html         # Room search results (step 2 progress bar)
│       ├── checkout.html            # Stripe payment form (step 3)
│       ├── confirmation.html        # Booking confirmed page
│       ├── Cars.html                # Car fleet listing + rental form
│       ├── My_bookings.html         # User booking & rental history
│       ├── login.html               # Login
│       ├── register.html            # Guest registration
│       ├── Forget_password.html     # Forgot password
│       ├── Reset_password.html      # Reset password
│       ├── admin_dashboard.html     # Admin dashboard (stats + quick actions)
│       ├── admin_bookings.html      # All bookings + status actions
│       ├── admin_rentals.html       # All rentals + status actions
│       ├── admin_users.html         # User management + promote/demote/delete
│       ├── manage_cars.html         # Add / delete cars
│       ├── create_rooms.html        # Add / delete rooms
│       ├── availability.html        # 14-day availability grid
│       └── admin_register.html      # Create staff account
├── tests/
│   ├── conftest.py          # Fixtures: app, db, client, users, rooms, cars
│   ├── Test_auth.py
│   ├── Test_admin.py
│   ├── Test_bookings.py
│   ├── Test_models.py
│   ├── Test_payments.py
│   └── Test_security.py
├── .github/
│   └── workflows/
│       └── CI.yml           # Lint → Test (py3.10/3.11/3.12) → Docker → Deploy
├── db_setup.py              # Creates tables + seeds admin account, rooms, cars
├── Dockerfile               # Multi-stage build, gunicorn entrypoint
├── runtime.txt              # python-3.11.0
├── requirements.txt
└── README.md
```

---

## Local Setup

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/sonicisastorm/FM-Residences-Web-App.git
cd FM-Residences-Web-App
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment variables

Create a `.env` file in the project root:

```env
# Flask
SECRET_KEY=your-random-secret-key-here
JWT_SECRET_KEY=another-random-secret-key
FLASK_ENV=development

# Database (SQLite for local dev)
DATABASE_URL=sqlite:///dev.db

# Stripe (test keys from dashboard.stripe.com)
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Email — Brevo SMTP (free at brevo.com, 300 emails/day)
MAIL_SERVER=smtp-relay.brevo.com
MAIL_PORT=587
MAIL_USERNAME=your_brevo_login@example.com
MAIL_PASSWORD=your_brevo_smtp_key
MAIL_USE_TLS=true
MAIL_USE_SSL=false
MAIL_SENDER_NAME=FM Residences

# ZeroBounce email validation (optional — zerobounce.net)
# Leave blank to skip validation
ZEROBOUNCE_API_KEY=

# Admin account created by db_setup.py
ADMIN_USERNAME=admin
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=ChangeMe123!
```

### 3. Create tables and seed data

```bash
python db_setup.py
```

This creates all database tables and seeds:
- An admin account (credentials from `.env` above)
- 3 sample rooms with 365 days of availability
- 3 sample cars

### 4. Run the development server

```bash
python run.py
```

Visit [http://localhost:5000](http://localhost:5000)

---

## User Flows

### Guest — book a room

1. Visit the home page
2. Click the date inputs to open the calendar picker — select check-in and check-out
3. Choose number of rooms and adults, click **Search Availability**
4. Available rooms appear (step 2) — click **Select Room →**
5. If not logged in, redirected to login first
6. Stripe checkout page (step 3) — enter card details
7. Test card: `4242 4242 4242 4242` · any future date · any CVC
8. Payment confirmed → booking appears in **My Bookings**

### Guest — rent a car

1. Click **Cars** in the nav
2. Choose a car, enter pickup and return dates, click **Rent This Car**
3. Complete payment on the Stripe checkout page
4. Rental appears in **My Bookings** under Car Rentals

### Admin — manage inventory

1. Log in with an admin account → `/admin/dashboard`
2. **Add Room** → form with room type, number, price, capacity, image
   - 365 days of availability auto-seeded on creation
3. **Manage Cars** → add new car or delete existing ones
4. **Availability** → 14-day calendar grid showing rooms left to sell per day
5. **All Bookings** → view every reservation, check in / check out / cancel
6. **All Rentals** → mark rentals as active or returned
7. **Manage Users** → promote users to staff, demote staff, delete accounts

---

## Authentication

The app uses a **hybrid** auth strategy:

- **JWT tokens** are issued on login and sent as `Authorization: Bearer <token>` headers for JSON API calls (dashboard data, status updates, payment intents).
- **Flask session** is set on login so server-rendered HTML pages (nav, admin pages, checkout) work without tokens.

Both expire independently — the session lasts the browser session, JWT access tokens expire after 30 minutes (configurable via `JWT_ACCESS_EXPIRES_MINUTES`).

---

## Email Verification

New user accounts require email verification before login. The verification email is sent via **Brevo SMTP** (port 587 / STARTTLS) in a background thread so registration responds instantly.

Before creating the account, the email is optionally validated by **ZeroBounce** which rejects:
- Invalid addresses (don't exist)
- Disposable / throwaway inboxes (Mailinator etc.)
- Known abuse/spam sources

If `ZEROBOUNCE_API_KEY` is not set, validation is skipped and all format-valid addresses are accepted.

---

## API Reference

All JSON API endpoints require `Authorization: Bearer <token>`. Admin endpoints additionally require role `admin` or `staff`.

### Auth

| Method | Path | Description |
|---|---|---|
| POST | `/auth/register` | Register new user account |
| POST | `/auth/login` | Login → returns JWT tokens + sets session |
| GET | `/auth/logout` | Session logout → redirects to home |
| POST | `/auth/logout` | API logout → blocklists JWT |
| GET | `/auth/verify-email/<token>` | Verify email address |
| POST | `/auth/forgot-password` | Request password reset email |
| POST | `/auth/reset-password` | Reset password with token |
| POST | `/auth/refresh` | Refresh access token |

### Admin — Dashboard

| Method | Path | Description |
|---|---|---|
| GET | `/admin/dashboard-data` | Stats + recent bookings & rentals (session auth) |

### Admin — Rooms

| Method | Path | Description |
|---|---|---|
| GET | `/admin/create-room` | Add room page |
| POST | `/admin/create-room` | Create room + auto-seed 365 days availability |
| POST | `/admin/delete-room` | Delete room |
| GET | `/admin/availability` | 14-day availability grid |
| POST | `/admin/rooms/<id>/availability` | Seed availability for date range (API) |
| PATCH | `/admin/rooms/<id>/toggle` | Activate / deactivate room (API) |

### Admin — Cars

| Method | Path | Description |
|---|---|---|
| GET | `/admin/manage-cars` | Manage cars page |
| POST | `/admin/create-car` | Add car |
| POST | `/admin/delete-car` | Delete car |
| PATCH | `/admin/api/cars/<id>/toggle` | Toggle availability (API) |

### Admin — Bookings & Rentals

| Method | Path | Description |
|---|---|---|
| GET | `/admin/bookings` | All bookings page |
| PATCH | `/admin/api/bookings/<id>/status` | Update status (confirmed→checked_in→checked_out) |
| GET | `/admin/rentals` | All rentals page |
| PATCH | `/admin/api/rentals/<id>/status` | Update status (confirmed→active→returned) |

### Admin — Users

| Method | Path | Description |
|---|---|---|
| GET | `/admin/users` | Manage users page |
| POST | `/admin/users/<id>/delete` | Delete user account |
| PATCH | `/admin/api/users/<id>/role` | Promote / demote role |
| POST | `/admin/register` | Create staff/admin account |

### Payments

| Method | Path | Description |
|---|---|---|
| POST | `/payments/create-intent/booking/<id>` | Create Stripe PaymentIntent for booking |
| POST | `/payments/create-intent/car-rental/<id>` | Create Stripe PaymentIntent for rental |
| POST | `/payments/confirm-payment` | Confirm payment directly (webhook fallback) |
| POST | `/payments/webhook` | Stripe webhook receiver |
| POST | `/payments/refund/<id>` | Issue full refund (admin only) |

---

## CI/CD Pipeline

GitHub Actions runs on every push:

1. **Lint** — flake8 (style) + bandit (security)
2. **Test** — pytest across Python 3.10, 3.11, 3.12 with SQLite in-memory DB
3. **Docker** — builds image + smoke tests app starts correctly
4. **Deploy** — triggers Render deploy hook (main branch only)

Render auto-deploys on every successful push to `main`. The build command runs `db_setup.py` on each deploy (idempotent — skips existing data).

---

## Deployment (Render)

### Requirements

- Render account (free tier works)
- PostgreSQL database on Render (Frankfurt region recommended)
- Brevo account for email (free, 300/day)
- Stripe account (test keys for staging, live keys for production)

### Steps

1. **Create PostgreSQL** on Render → copy the Internal Database URL
2. **Create Web Service** → connect GitHub repo, branch `main`
   - Runtime: Python 3.11
   - Build command: `pip install -r requirements.txt && python db_setup.py`
   - Start command: `gunicorn --bind 0.0.0.0:$PORT --timeout 120 run:app`
3. **Set environment variables** in Render dashboard (see `.env` section above, plus `DATABASE_URL` from step 1)
4. **Set Stripe webhook** → Stripe dashboard → Webhooks → endpoint `https://your-app.onrender.com/payments/webhook`
   - Events: `payment_intent.succeeded`, `payment_intent.payment_failed`, `charge.refunded`
   - Copy signing secret → `STRIPE_WEBHOOK_SECRET` in Render
5. **Add deploy hook** to GitHub → repo Settings → Secrets → `RENDER_DEPLOY_HOOK_URL`

---

## Testing

```bash
pytest tests/ -v
```

Tests use an in-memory SQLite database and never touch your real database or Stripe.

```bash
# Run a specific test file
pytest tests/Test_auth.py -v

# With coverage
pytest tests/ --cov=src --cov-report=term-missing
```

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | Flask session secret |
| `JWT_SECRET_KEY` | Yes | JWT signing secret |
| `DATABASE_URL` | Yes | PostgreSQL or SQLite URL |
| `FLASK_ENV` | Yes | `development` or `production` |
| `STRIPE_SECRET_KEY` | Yes | Stripe secret key (`sk_test_` or `sk_live_`) |
| `STRIPE_PUBLISHABLE_KEY` | Yes | Stripe publishable key |
| `STRIPE_WEBHOOK_SECRET` | Yes | Stripe webhook signing secret (`whsec_`) |
| `MAIL_SERVER` | Yes | SMTP server (`smtp-relay.brevo.com`) |
| `MAIL_PORT` | Yes | SMTP port (`587`) |
| `MAIL_USERNAME` | Yes | Brevo login email |
| `MAIL_PASSWORD` | Yes | Brevo SMTP key |
| `MAIL_USE_TLS` | Yes | `true` for Brevo |
| `MAIL_USE_SSL` | Yes | `false` for Brevo |
| `MAIL_SENDER_NAME` | No | Display name in emails (default: `FM Residences`) |
| `ZEROBOUNCE_API_KEY` | No | ZeroBounce API key — skipped if blank |
| `ADMIN_USERNAME` | Yes | Admin username for db_setup.py |
| `ADMIN_EMAIL` | Yes | Admin email for db_setup.py |
| `ADMIN_PASSWORD` | Yes | Admin password for db_setup.py |
| `JWT_ACCESS_EXPIRES_MINUTES` | No | JWT lifetime in minutes (default: 30) |
| `RENDER_DEPLOY_HOOK_URL` | CI only | Render deploy hook URL (GitHub secret) |
