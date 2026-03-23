# FM Residences

A full-stack hotel management web application built with Flask. Guests can search and book rooms, rent cars, and pay via Stripe. Staff manage inventory and reservations through an admin panel.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, Flask 2.3 |
| ORM | SQLAlchemy 2.0 + Flask-SQLAlchemy |
| Auth | Flask-JWT-Extended (tokens) + Flask session (server-rendered pages) |
| Payments | Stripe (PaymentIntents API) |
| Email | Flask-Mail |
| Templates | Jinja2 + Tailwind CSS (CDN) |
| Database | PostgreSQL (prod) / SQLite (dev/test) |
| Tests | pytest |

---

## Project Structure

```
FM-Residences/
├── src/
│   ├── __init__.py          # App factory, extensions, context processors
│   ├── models.py            # SQLAlchemy models: User, Room, RoomAvailability,
│   │                        #   Booking, Cars, CarRental, Payment, JWTToken
│   ├── auth.py              # Auth blueprint: register, login, logout,
│   │                        #   email verification, forgot/reset password
│   ├── bookings.py          # Booking blueprint: room search, bookings, car rentals,
│   │                        #   checkout page, my-bookings page
│   ├── admin.py             # Admin blueprint: dashboard, room/car/user CRUD,
│   │                        #   staff registration, booking management
│   ├── payments.py          # Payments blueprint: Stripe intent creation, webhook
│   ├── helpers.py           # Auth decorators: login_required, admin_required
│   ├── room_search.py       # Availability search logic
│   ├── static/              # CSS, JS, uploaded images
│   └── templates/
│       ├── layout.html      # Base template (nav, footer)
│       ├── index.html       # Landing page + search form
│       ├── offer_rooms.html # Room search results
│       ├── Cars.html        # Car fleet listing + rental form
│       ├── checkout.html    # Stripe payment form
│       ├── My_bookings.html # User booking history
│       ├── login.html       # Login page
│       ├── register.html    # Guest registration
│       ├── Forget_password.html
│       ├── Reset_password.html
│       ├── admin_dashboard.html
│       ├── admin_bookings.html
│       ├── admin_rentals.html
│       ├── admin_users.html
│       ├── admin_cars.html
│       └── admin_register.html
├── tests/
│   ├── Conftest.py          # Fixtures: app, db, client, users, rooms, cars
│   ├── test_bookings.py
│   ├── test_admin.py
│   ├── test_payments.py
│   └── test_models.py
├── db_setup.py              # Creates tables + seeds initial admin account
├── requirements.txt         # App dependencies
├── requirements-prod.txt    # Production-only (meinheld, gunicorn)
├── .env.example
└── README.md
```

---

## Local Setup

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/your-org/fm-residences.git
cd fm-residences
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment variables

Copy `.env.example` to `.env` and fill in every value:

```bash
cp .env.example .env
```

```env
# Flask
SECRET_KEY=your-random-secret-key-here
FLASK_ENV=development
DATABASE_URL=sqlite:///fm_residences.db

# JWT
JWT_SECRET_KEY=another-random-secret

# Stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Email (use Mailtrap for dev)
MAIL_SERVER=smtp.mailtrap.io
MAIL_PORT=587
MAIL_USERNAME=your-mailtrap-user
MAIL_PASSWORD=your-mailtrap-pass
MAIL_DEFAULT_SENDER=noreply@fmresidences.com

# File uploads
UPLOAD_FOLDER=src/static/uploads
```

### 3. Create tables and seed initial admin account

```bash
python db_setup.py
```

This creates all database tables and inserts an admin user:
- **Username:** `admin`
- **Password:** `Admin@123456` *(change immediately after first login)*

### 4. Run the development server

```bash
flask run
# or
python -m flask run --debug
```

Visit [http://localhost:5000](http://localhost:5000)

---

## User Flows

### Guest — book a room

1. Visit the home page
2. Select check-in / check-out dates, number of rooms and adults
3. Click **Search** → available rooms appear
4. Click **Select Room** → redirected to login if not authenticated
5. After login, redirected to the Stripe checkout page
6. Enter card details (use `4242 4242 4242 4242` in test mode) → payment confirmed
7. View the booking in **My Bookings**

### Guest — rent a car

1. Click **Cars** in the nav
2. Choose a car, enter pickup and return dates, click **Rent This Car**
3. Redirected to the Stripe checkout page
4. Complete payment
5. Rental appears in **My Bookings** under Car Rentals

### Admin — manage inventory

1. Log in with an admin account → redirected to `/admin/dashboard`
2. **Rooms** → add, edit, toggle active/inactive, seed availability calendars
3. **Cars** → add, edit, toggle availability
4. **Bookings** → view all reservations, update status (confirmed → checked-in → checked-out)
5. **Rentals** → view all rentals, mark as active / returned
6. **Users** → manage guest accounts, promote to staff

---

## Authentication

The app uses a **hybrid** auth strategy:

- **JWT tokens** are issued on login and must be sent as `Authorization: Bearer <token>` headers for all JSON API calls.
- **Flask session** is also set on login so server-rendered HTML pages can show the correct nav and gate page routes.

Token refresh: `POST /auth/refresh` with the refresh token (standard JWT refresh flow).

---

## API Reference (Admin)

All JSON API endpoints require `Authorization: Bearer <admin_token>`.

### Dashboard

| Method | Path | Description |
|---|---|---|
| GET | `/admin/dashboard-data` | Stats: total bookings, rentals, revenue, users; recent items |

### Rooms

| Method | Path | Description |
|---|---|---|
| GET | `/admin/rooms` | List all rooms |
| POST | `/admin/rooms` | Create room (multipart or JSON) |
| PATCH | `/admin/rooms/<id>` | Edit room fields |
| DELETE | `/admin/rooms/<id>` | Delete room (blocks if active bookings) |
| PATCH | `/admin/rooms/<id>/toggle` | Activate / deactivate |
| POST | `/admin/rooms/<id>/availability` | Seed availability for date range |

### Cars

| Method | Path | Description |
|---|---|---|
| GET | `/admin/api/cars` | List all cars |
| POST | `/admin/api/cars` | Add car |
| PATCH | `/admin/api/cars/<id>` | Edit car |
| DELETE | `/admin/api/cars/<id>` | Delete car |
| PATCH | `/admin/api/cars/<id>/toggle` | Toggle availability |

### Bookings

| Method | Path | Description |
|---|---|---|
| GET | `/admin/api/bookings` | List bookings (filter by status, room, user, date) |
| PATCH | `/admin/api/bookings/<id>/status` | Update booking status |
| DELETE | `/admin/api/bookings/<id>` | Delete booking |

### Rentals

| Method | Path | Description |
|---|---|---|
| GET | `/admin/api/rentals` | List rentals |
| PATCH | `/admin/api/rentals/<id>/status` | Update rental status |

### Users

| Method | Path | Description |
|---|---|---|
| GET | `/admin/api/users` | List users (filter by role, active, search) |
| POST | `/admin/register` | Create staff/admin account |
| PATCH | `/admin/api/users/<id>/role` | Change user role |
| PATCH | `/admin/api/users/<id>/toggle` | Activate/deactivate account |

### Payments

| Method | Path | Description |
|---|---|---|
| POST | `/payments/create-intent/booking/<id>` | Create Stripe PaymentIntent for booking |
| POST | `/payments/create-intent/car-rental/<id>` | Create Stripe PaymentIntent for rental |
| POST | `/payments/webhook` | Stripe webhook receiver |
| POST | `/payments/refund/<id>` | Issue full refund (admin only) |
| GET | `/payments/status/<id>` | Check payment status |

---

## Room Availability Seeding

Before rooms appear in search results, their availability must be seeded:

```bash
# Via API (admin token required)
curl -X POST http://localhost:5000/admin/rooms/1/availability \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"from_date": "2026-03-01", "to_date": "2026-12-31"}'
```

Or run a one-off script:

```python
from src import create_app, db
from src.models import Room, RoomAvailability
from datetime import date, timedelta

app = create_app()
with app.app_context():
    rooms = Room.query.all()
    start = date.today()
    end   = start + timedelta(days=365)
    for room in rooms:
        current = start
        while current < end:
            if not RoomAvailability.query.filter_by(room_id=room.id, date=current).first():
                db.session.add(RoomAvailability(
                    room_id=room.id, date=current,
                    total_rooms=room.total_of_this_type,
                    booked=0, left_to_sell=room.total_of_this_type,
                    is_available=True,
                ))
            current += timedelta(days=1)
    db.session.commit()
    print("Done")
```

---

## Stripe Webhook (local dev)

Install the Stripe CLI and forward events to the local server:

```bash
stripe listen --forward-to localhost:5000/payments/webhook
```

Copy the webhook signing secret the CLI prints and set it as `STRIPE_WEBHOOK_SECRET` in `.env`.

Key events handled:

| Event | Effect |
|---|---|
| `payment_intent.succeeded` | Booking/rental → `confirmed`, car → unavailable |
| `payment_intent.payment_failed` | Payment → `failed` |
| `charge.refunded` | Payment → `refunded`, booking/rental → `cancelled` |

---

## Running Tests

```bash
pytest tests/ -v
```

The test suite uses an in-memory SQLite database. Each test function runs in a rolled-back transaction so tests don't interfere with each other.

To run a specific test file:

```bash
pytest tests/test_bookings.py -v
pytest tests/test_admin.py -v
pytest tests/test_payments.py -v
pytest tests/test_models.py -v
```

---

## Docker (Production)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-prod.txt
COPY . .
EXPOSE 8000
CMD ["meinheld", "-b", "0.0.0.0:8000", "src:create_app()"]
```

```yaml
# docker-compose.yml
services:
  web:
    build: .
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      - db
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: fm_residences
      POSTGRES_USER: fm
      POSTGRES_PASSWORD: fm_secret
    volumes:
      - pgdata:/var/lib/postgresql/data
volumes:
  pgdata:
```

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | Flask session signing key |
| `JWT_SECRET_KEY` | Yes | JWT token signing key |
| `DATABASE_URL` | Yes | SQLAlchemy connection string |
| `STRIPE_SECRET_KEY` | Yes | Stripe secret key (`sk_live_` / `sk_test_`) |
| `STRIPE_PUBLISHABLE_KEY` | Yes | Stripe publishable key (sent to frontend) |
| `STRIPE_WEBHOOK_SECRET` | Yes | Webhook signature secret (`whsec_`) |
| `MAIL_SERVER` | Yes | SMTP host |
| `MAIL_PORT` | Yes | SMTP port (usually 587) |
| `MAIL_USERNAME` | Yes | SMTP username |
| `MAIL_PASSWORD` | Yes | SMTP password |
| `MAIL_DEFAULT_SENDER` | Yes | From address for outgoing emails |
| `UPLOAD_FOLDER` | No | Path for uploaded images (default: `src/static/uploads`) |
| `FLASK_ENV` | No | `development` / `production` |

---

## Context Processor

`src/__init__.py` must register a context processor so templates can use `{{ now.year }}` in the footer:

```python
from datetime import datetime

@app.context_processor
def inject_now():
    return {"now": datetime.now()}
```
