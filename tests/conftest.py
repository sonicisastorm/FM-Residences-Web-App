"""
conftest.py — FM Residences
Shared pytest fixtures: app factory, test client, seeded DB.

FIXES APPLIED:
  - BUG 13: `Car` → `Cars`  (the model class is named Cars, not Car)
  - BUG 14: Room fixture used `name=`, `room_description=` which don't
            exist on the model. Fixed to use `room_type=`, `room_number=`,
            `description=`, `price_per_night=`
  - BUG 14: Car fixture used `plate=` which doesn't exist.
            Fixed to `plate_number=`
  - FIX: Removed session.bind pattern (removed in Flask-SQLAlchemy 3.x).
         Now uses delete-all-rows approach which works with all versions.
  - FIX: Added `now` context processor so templates don't crash with
         UndefinedError: 'now' is undefined
"""

import pytest
from datetime import datetime, timezone, date, timedelta


# ─────────────────────────────────────────────────────────────────────────────
# App / client fixtures
# ─────────────────────────────────────────────────────────────────────────────
from sqlalchemy.pool import StaticPool

@pytest.fixture(scope="session")
def app():
    """Create an application instance configured for testing (in-memory SQLite)."""
    import os
    os.environ["SECRET_KEY"]     = "test-secret-key"
    os.environ["JWT_SECRET_KEY"] = "test-jwt-secret"
    os.environ["DATABASE_URL"]   = "sqlite:///:memory:"
    os.environ["FLASK_ENV"]      = "testing"

    from src import create_app
    application = create_app()
    application.config["TESTING"]            = True
    application.config["WTF_CSRF_ENABLED"]   = False
    application.config["MAIL_SUPPRESS_SEND"] = True

    application.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }

    # FIX: inject `now` so templates that use {{ now.year }} don't crash
    @application.context_processor
    def inject_now():
        return {"now": datetime.now(timezone.utc)}

    yield application


@pytest.fixture(scope="session")
def _db(app):
    """Create all tables once per test session, drop them at the end."""
    from src import db as _db_instance
    with app.app_context():
        _db_instance.create_all()
        yield _db_instance
        _db_instance.drop_all()


@pytest.fixture(scope="function")
def db(app, _db):
    """
    Provide a clean DB for each test by deleting all rows after the test.

    FIX: The old approach used session.bind which was removed in
    Flask-SQLAlchemy 3.x. This simpler approach works with all versions.
    """
    from src import db as _db_instance
    with app.app_context():
        yield _db_instance
        # Clean up all rows after each test so tests don't interfere
        _db_instance.session.remove()
        for table in reversed(_db_instance.metadata.sorted_tables):
            _db_instance.session.execute(table.delete())
        _db_instance.session.commit()


@pytest.fixture(scope="function")
def client(app, db):
    """Test HTTP client with DB cleanup per test."""
    with app.test_client() as c:
        yield c


# ─────────────────────────────────────────────────────────────────────────────
# Seeded data fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def regular_user(db, app):
    """A verified, regular-role user."""
    from src.models import User
    with app.app_context():
        u = User(username="testuser", email="test@fmresidences.com", role="user")
        u.set_password("TestPass123!")
        u.is_verified = True
        db.session.add(u)
        db.session.commit()
        return {
            "id":       u.id,
            "username": u.username,
            "email":    u.email,
            "password": "TestPass123!",
        }


@pytest.fixture
def admin_user(db, app):
    """A verified admin user."""
    from src.models import User
    with app.app_context():
        u = User(username="adminuser", email="admin@fmresidences.com", role="admin")
        u.set_password("AdminPass123!")
        u.is_verified = True
        db.session.add(u)
        db.session.commit()
        return {
            "id":       u.id,
            "username": u.username,
            "email":    u.email,
            "password": "AdminPass123!",
        }


@pytest.fixture
def sample_room(db, app):
    """
    A basic room type with a seeded availability row for the next 30 days.
    """
    from src.models import Room, RoomAvailability

    with app.app_context():
        r = Room(
            room_number        = "101",
            room_type          = "Deluxe Suite",
            description        = "A luxurious suite with ocean view.",
            price_per_night    = 150.0,
            total_of_this_type = 5,
            max_guests         = 4,
            min_guests         = 1,
            max_adults         = 4,
            max_children       = 2,
            is_active          = True,
        )
        db.session.add(r)
        db.session.flush()

        today = date.today()
        for i in range(30):
            avail = RoomAvailability(
                room_id      = r.id,
                date         = today + timedelta(days=i),
                total_rooms  = r.total_of_this_type,
                booked       = 0,
                left_to_sell = r.total_of_this_type,
                is_available = True,
            )
            db.session.add(avail)

        db.session.commit()
        return {"id": r.id, "room_type": r.room_type, "room_number": r.room_number}


@pytest.fixture
def sample_car(db, app):
    """A basic car listing."""
    from src.models import Cars

    with app.app_context():
        c = Cars(
            model         = "Mercedes E-Class",
            plate_number  = "FM-001",
            description   = "Executive sedan",
            price_per_day = 150.0,
            is_available  = True,
        )
        db.session.add(c)
        db.session.commit()
        return {"id": c.id, "model": c.model}


@pytest.fixture
def auth_headers(client, regular_user):
    """Log in and return JWT Authorization headers."""
    resp  = client.post("/auth/login", json={
        "username": regular_user["username"],
        "password": regular_user["password"],
    })
    token = resp.get_json().get("access_token")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_auth_headers(client, admin_user):
    """Log in as admin and return JWT Authorization headers."""
    resp  = client.post("/auth/login", json={
        "username": admin_user["username"],
        "password": admin_user["password"],
    })
    token = resp.get_json().get("access_token")
    return {"Authorization": f"Bearer {token}"}