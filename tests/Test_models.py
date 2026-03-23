"""
test_models.py — FM Residences

FIXES APPLIED:
  - BUG 18: `from src.models import Car` → `from src.models import Cars`
  - BUG 18: `plate=` → `plate_number=`
"""

import pytest
from datetime import date, timedelta


# ─────────────────────────────────────────────────────────────────────────────
#  User model
# ─────────────────────────────────────────────────────────────────────────────

class TestUserModel:

    def test_create_user(self, db, app):
        from src.models import User
        with app.app_context():
            u = User(username="modeltest", email="modeltest@fm.com", role="user")
            u.set_password("SecurePass123!")
            db.session.add(u)
            db.session.commit()

            fetched = User.query.filter_by(username="modeltest").first()
            assert fetched is not None
            assert fetched.email == "modeltest@fm.com"
            assert fetched.role  == "user"

    def test_password_hashing(self, db, app):
        from src.models import User
        with app.app_context():
            u = User(username="hashtest", email="hash@fm.com", role="user")
            u.set_password("MyPassword99!")
            db.session.add(u)
            db.session.commit()

            assert u.check_password("MyPassword99!")  is True
            assert u.check_password("wrongpassword")  is False
            assert u.password_hash != "MyPassword99!"

    def test_duplicate_username_rejected(self, db, app):
        from src.models import User
        from sqlalchemy.exc import IntegrityError
        with app.app_context():
            u1 = User(username="dupcheck", email="dup1@fm.com", role="user")
            u1.set_password("Pass123!")
            db.session.add(u1)
            db.session.commit()

            u2 = User(username="dupcheck", email="dup2@fm.com", role="user")
            u2.set_password("Pass123!")
            db.session.add(u2)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_email_verification_token(self, db, app):
        from src.models import User
        with app.app_context():
            u = User(username="verifytest", email="verify@fm.com", role="user")
            u.set_password("Pass123!")
            token = u.generate_verification_token()
            db.session.add(u)
            db.session.commit()

            assert token is not None
            assert u.verification_token == token

    def test_to_dict_excludes_password(self, db, app):
        from src.models import User
        with app.app_context():
            u = User(username="dicttest", email="dict@fm.com", role="user")
            u.set_password("Pass123!")
            db.session.add(u)
            db.session.commit()

            d = u.to_dict()
            assert "password_hash" not in d
            assert "id"            in d
            assert "username"      in d
            assert "email"         in d


# ─────────────────────────────────────────────────────────────────────────────
#  Room model
# ─────────────────────────────────────────────────────────────────────────────

class TestRoomModel:

    def test_create_room(self, db, app):
        from src.models import Room
        with app.app_context():
            r = Room(
                room_number        = "301",     # FIX: field is room_number
                room_type          = "Standard", # FIX: field is room_type (not name)
                description        = "A standard room",
                price_per_night    = 100.0,
                total_of_this_type = 10,
            )
            db.session.add(r)
            db.session.commit()

            fetched = Room.query.filter_by(room_number="301").first()
            assert fetched is not None
            assert fetched.room_type == "Standard"

    def test_room_to_dict(self, db, app):
        from src.models import Room
        with app.app_context():
            r = Room(
                room_number        = "302",
                room_type          = "Deluxe",
                price_per_night    = 175.0,
                total_of_this_type = 5,
            )
            db.session.add(r)
            db.session.commit()

            d = r.to_dict()
            assert d["room_type"]       == "Deluxe"
            assert d["price_per_night"] == 175.0
            assert "id"                 in d


# ─────────────────────────────────────────────────────────────────────────────
#  Cars model  (FIX BUG 18)
# ─────────────────────────────────────────────────────────────────────────────

class TestCarsModel:

    def test_create_car(self, db, app):
        # FIX BUG 18: was `from src.models import Car` — model is named Cars (plural)
        from src.models import Cars
        with app.app_context():
            c = Cars(
                model        = "Audi A6",
                plate_number = "FM-TEST-01",   # FIX BUG 18: was plate=
                price_per_day = 120.0,
                is_available  = True,
            )
            db.session.add(c)
            db.session.commit()

            # FIX BUG 18: query via Cars, not Car
            fetched = Cars.query.filter_by(plate_number="FM-TEST-01").first()
            assert fetched is not None
            assert fetched.model        == "Audi A6"
            assert fetched.price_per_day == 120.0

    def test_car_to_dict(self, db, app):
        from src.models import Cars   # FIX BUG 18
        with app.app_context():
            c = Cars(
                model         = "VW Passat",
                plate_number  = "FM-TEST-02",  # FIX BUG 18
                price_per_day = 80.0,
            )
            db.session.add(c)
            db.session.commit()

            d = c.to_dict()
            assert d["model"]        == "VW Passat"
            assert d["plate_number"] == "FM-TEST-02"  # FIX: key is plate_number
            assert "id"              in d

    def test_car_is_available_defaults_true(self, db, app):
        from src.models import Cars   # FIX BUG 18
        with app.app_context():
            c = Cars(
                model         = "Kia Sportage",
                plate_number  = "FM-TEST-03",   # FIX BUG 18
                price_per_day = 70.0,
            )
            db.session.add(c)
            db.session.commit()
            assert c.is_available is True


# ─────────────────────────────────────────────────────────────────────────────
#  Booking model
# ─────────────────────────────────────────────────────────────────────────────

class TestBookingModel:

    def test_create_booking(self, db, app, regular_user, sample_room):
        from src.models import Booking
        with app.app_context():
            b = Booking(
                user_id         = regular_user["id"],
                room_id         = sample_room["id"],
                check_in_date   = date.today() + timedelta(days=10),
                check_out_date  = date.today() + timedelta(days=12),
                num_rooms       = 1,
                num_guests      = 2,
                num_adults      = 2,
                num_children    = 0,
                price_per_night = 150.0,
                total_price     = 300.0,
                status          = "confirmed",
            )
            db.session.add(b)
            db.session.commit()
            assert b.id is not None
            assert b.status == "confirmed"

    def test_booking_cancel(self, db, app, regular_user, sample_room):
        from src.models import Booking
        with app.app_context():
            b = Booking(
                user_id         = regular_user["id"],
                room_id         = sample_room["id"],
                check_in_date   = date.today() + timedelta(days=10),
                check_out_date  = date.today() + timedelta(days=12),
                num_rooms       = 1,
                num_guests      = 2,
                num_adults      = 2,
                num_children    = 0,
                price_per_night = 150.0,
                total_price     = 300.0,
                status          = "confirmed",
            )
            db.session.add(b)
            db.session.commit()
            b.cancel()
            db.session.commit()
            assert b.status == "cancelled"

    def test_booking_cancel_checked_in_raises(self, db, app, regular_user, sample_room):
        from src.models import Booking
        with app.app_context():
            b = Booking(
                user_id         = regular_user["id"],
                room_id         = sample_room["id"],
                check_in_date   = date.today(),
                check_out_date  = date.today() + timedelta(days=2),
                num_rooms       = 1,
                num_guests      = 1,
                num_adults      = 1,
                num_children    = 0,
                price_per_night = 100.0,
                total_price     = 200.0,
                status          = "checked_in",
            )
            db.session.add(b)
            db.session.commit()
            with pytest.raises(ValueError):
                b.cancel()