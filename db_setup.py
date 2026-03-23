"""
db_setup.py — FM Residences
Run this ONCE after first install to:
  1. Create all database tables
  2. Create the first admin account
  3. Seed sample rooms and cars so the site has something to show

Usage:
    python db_setup.py

You will be prompted for the admin username, email, and password.
After that the script exits — your normal app uses run.py.
"""

import sys
import os
from datetime import date, timedelta

# Make sure the src package is importable when running from project root
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src import create_app, db
from src.models import User, Room, RoomAvailability, Cars, Hotels


def create_tables(app):
    with app.app_context():
        db.create_all()
        print("✅  All tables created.")


def create_admin(app):
    with app.app_context():
        print("\n── Create first admin account ───────────────────────────")

        username = input("Admin username : ").strip()
        email    = input("Admin email    : ").strip()
        password = input("Admin password : ").strip()

        if not username or not email or not password:
            print("❌  All fields are required.")
            return

        if len(password) < 8:
            print("❌  Password must be at least 8 characters.")
            return

        if User.query.filter_by(username=username).first():
            print(f"⚠️   User '{username}' already exists — skipping.")
            return

        admin = User(username=username, email=email, role="admin")
        admin.set_password(password)
        admin.is_verified = True   # admin doesn't need email verification
        admin.is_active   = True

        db.session.add(admin)
        db.session.commit()
        print(f"✅  Admin account '{username}' created.")


def seed_rooms(app):
    with app.app_context():
        if Room.query.count() > 0:
            print("\n⚠️   Rooms already exist — skipping room seed.")
            return

        print("\n── Seeding sample rooms ─────────────────────────────────")

        sample_rooms = [
            {
                "room_number":        "101",
                "room_type":          "Standard Room",
                "price_per_night":    89.00,
                "total_of_this_type": 5,
                "max_guests":         2,
                "min_guests":         1,
                "max_adults":         2,
                "max_children":       0,
                "description":        "Comfortable standard room with queen bed and city view.",
            },
            {
                "room_number":        "201",
                "room_type":          "Deluxe Room",
                "price_per_night":    139.00,
                "total_of_this_type": 4,
                "max_guests":         3,
                "min_guests":         1,
                "max_adults":         2,
                "max_children":       1,
                "description":        "Spacious deluxe room with king bed, sea view, and lounge area.",
            },
            {
                "room_number":        "301",
                "room_type":          "Family Suite",
                "price_per_night":    219.00,
                "total_of_this_type": 2,
                "max_guests":         5,
                "min_guests":         2,
                "max_adults":         2,
                "max_children":       3,
                "description":        "Two-bedroom suite ideal for families, with kitchenette.",
            },
        ]

        today     = date.today()
        end_date  = today + timedelta(days=365)   # seed 1 year ahead

        for data in sample_rooms:
            room = Room(**data)
            db.session.add(room)
            db.session.flush()   # get room.id before commit

            # Seed RoomAvailability for every day in the window
            current = today
            while current < end_date:
                avail = RoomAvailability(
                    room_id      = room.id,
                    date         = current,
                    total_rooms  = room.total_of_this_type,
                    booked       = 0,
                    left_to_sell = room.total_of_this_type,
                    is_available = True,
                )
                db.session.add(avail)
                current += timedelta(days=1)

            print(f"   ➕  {room.room_type} (room #{room.room_number}) + 365 availability rows")

        db.session.commit()
        print("✅  Rooms seeded.")


def seed_cars(app):
    with app.app_context():
        if Cars.query.count() > 0:
            print("\n⚠️   Cars already exist — skipping car seed.")
            return

        print("\n── Seeding sample cars ──────────────────────────────────")

        sample_cars = [
            {
                "model":         "Toyota Corolla 2023",
                "plate_number":  "FM-001",
                "price_per_day": 45.00,
                "description":   "Economical sedan, ideal for city driving.",
                "is_available":  True,
            },
            {
                "model":         "Toyota Land Cruiser 2022",
                "plate_number":  "FM-002",
                "price_per_day": 110.00,
                "description":   "Premium SUV for families or off-road excursions.",
                "is_available":  True,
            },
            {
                "model":         "Mercedes-Benz C-Class 2023",
                "plate_number":  "FM-003",
                "price_per_day": 155.00,
                "description":   "Luxury sedan for business travel.",
                "is_available":  True,
            },
        ]

        for data in sample_cars:
            car = Cars(**data)
            db.session.add(car)
            print(f"   ➕  {car.model} [{car.plate_number}]")

        db.session.commit()
        print("✅  Cars seeded.")


def seed_hotel_info(app):
    with app.app_context():
        if Hotels.query.count() > 0:
            print("\n⚠️   Hotel info already exists — skipping.")
            return

        print("\n── Seeding hotel info ───────────────────────────────────")
        hotel = Hotels(
            name        = "FM Residences",
            location    = "123 Ocean Drive, Miami, FL 33139",
            description = "Luxury boutique hotel and residences steps from the beach.",
        )
        db.session.add(hotel)
        db.session.commit()
        print("✅  Hotel info seeded.")


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("═" * 55)
    print("  FM Residences — Database Setup")
    print("═" * 55)

    app = create_app()

    create_tables(app)
    create_admin(app)
    seed_rooms(app)
    seed_cars(app)
    seed_hotel_info(app)

    print("\n" + "═" * 55)
    print("  Setup complete. Run the app with:  python run.py")
    print("═" * 55 + "\n")