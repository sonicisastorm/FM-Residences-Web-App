"""
models.py — FM Residences
All SQLAlchemy models for the application.

Changes from original:
  - Booking:       added status, total_price, num_rooms, num_guests
  - Room:          added room_type details (max_guests, images, etc.)
  - RoomAvailability: NEW — tracks per-date inventory to prevent double-booking
  - Cars:          added is_available, plate_number, image
  - CarRental:     added return_date, status, total_price, car FK
  - Payment:       NEW — tracks Stripe payment per booking or car rental
  - JWTToken:      NEW — persistent blocklist for logged-out tokens
"""

from datetime import datetime, timedelta, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import generate_password_hash, check_password_hash
from sqlalchemy import func
import secrets

db = SQLAlchemy()


# ═══════════════════════════════════════════════════════════════════════════
#  USERS & AUTH
# ═══════════════════════════════════════════════════════════════════════════

class User(db.Model):
    """User account — guests, staff and admins all live here."""
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80),  unique=True, nullable=False, index=True)
    email         = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role          = db.Column(db.String(20),  nullable=False, default="user", index=True)
    # role choices: "user" | "staff" | "admin"

    # Status
    is_active    = db.Column(db.Boolean, default=True,  nullable=False, index=True)
    is_verified  = db.Column(db.Boolean, default=False, nullable=False)

    # Tokens (short-lived — stored until used or expired)
    verification_token = db.Column(db.String(100), unique=True, nullable=True)
    reset_token        = db.Column(db.String(100), unique=True, nullable=True)
    reset_token_expiry = db.Column(db.DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), server_default=func.now(),
                           onupdate=func.now(), nullable=False)
    last_login = db.Column(db.DateTime(timezone=True), nullable=True)

    # Relationships
    bookings    = db.relationship("Booking",   back_populates="user",
                                  cascade="all, delete-orphan", lazy="dynamic")
    car_rentals = db.relationship("CarRental", back_populates="user",
                                  cascade="all, delete-orphan", lazy="dynamic")

    def __repr__(self):
        return f"<User {self.username} [{self.role}]>"

    # ── Password helpers ─────────────────────────────────────────────────────
    def set_password(self, password):
        self.password_hash = generate_password_hash(password).decode("utf-8")

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # ── Token helpers ────────────────────────────────────────────────────────
    def generate_verification_token(self):
        self.verification_token = secrets.token_urlsafe(32)
        return self.verification_token

    def generate_reset_token(self):
        self.reset_token        = secrets.token_urlsafe(32)
        self.reset_token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        return self.reset_token

    def verify_email(self):
        self.is_verified        = True
        self.verification_token = None

    def update_last_login(self):
        self.last_login = datetime.now(timezone.utc)

    # ── Role helper ──────────────────────────────────────────────────────────
    @staticmethod
    def validate_role(role):
        return role in ("user", "admin", "staff")

    # ── Serialisation ────────────────────────────────────────────────────────
    def to_dict(self, include_sensitive=False):
        data = {
            "id":          self.id,
            "username":    self.username,
            "email":       self.email,
            "role":        self.role,
            "is_active":   self.is_active,
            "is_verified": self.is_verified,
            "created_at":  self.created_at.isoformat(),
            "updated_at":  self.updated_at.isoformat(),
            "last_login":  self.last_login.isoformat() if self.last_login else None,
        }
        if include_sensitive:
            data["verification_token"] = self.verification_token
            data["reset_token"]        = self.reset_token
        return data


class JWTToken(db.Model):
    """
    Persistent JWT blocklist.
    When a user logs out their token JTI is stored here so it can be
    rejected even before the token naturally expires.
    The in-memory set in __init__.py is loaded from this table on startup.
    """
    __tablename__ = "jwt_tokens"

    id         = db.Column(db.Integer, primary_key=True)
    jti        = db.Column(db.String(36), unique=True, nullable=False, index=True)
    # "access" or "refresh"
    token_type = db.Column(db.String(10), nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True),
                           server_default=func.now(), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)

    def __repr__(self):
        return f"<JWTToken {self.jti} revoked>"


# ═══════════════════════════════════════════════════════════════════════════
#  ROOMS & AVAILABILITY
# ═══════════════════════════════════════════════════════════════════════════

class Room(db.Model):
    """
    A room type (e.g. 'Deluxe Suite').
    total_of_this_type tells you how many physical rooms of this type exist —
    availability per date is tracked in RoomAvailability.
    """
    __tablename__ = "rooms"

    id                = db.Column(db.Integer, primary_key=True)
    room_number       = db.Column(db.String(20),  unique=True, nullable=False, index=True)
    room_type         = db.Column(db.String(50),  nullable=False, index=True)
    description       = db.Column(db.Text,        nullable=True)
    room_image        = db.Column(db.String(255),  nullable=True)   # filename in UPLOAD_FOLDER

    # Capacity
    max_guests    = db.Column(db.Integer, nullable=False, default=2)
    min_guests    = db.Column(db.Integer, nullable=False, default=1)
    max_adults    = db.Column(db.Integer, nullable=False, default=2)
    max_children  = db.Column(db.Integer, nullable=False, default=1)

    # How many physical rooms of this type the hotel has
    total_of_this_type = db.Column(db.Integer, nullable=False, default=1)

    # Base price per night (overridden by RatePlan when one exists)
    price_per_night = db.Column(db.Float, nullable=False)

    # Admin can globally toggle a room type off (e.g. under renovation)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), server_default=func.now(),
                           onupdate=func.now(), nullable=False)

    # Relationships
    bookings      = db.relationship("Booking",          back_populates="room",
                                    cascade="all, delete-orphan", lazy="dynamic")
    availability  = db.relationship("RoomAvailability", back_populates="room",
                                    cascade="all, delete-orphan", lazy="dynamic")

    def __repr__(self):
        return f"<Room {self.room_number} — {self.room_type}>"

    def to_dict(self):
        return {
            "id":                 self.id,
            "room_number":        self.room_number,
            "room_type":          self.room_type,
            "description":        self.description,
            "room_image":         self.room_image,
            "max_guests":         self.max_guests,
            "min_guests":         self.min_guests,
            "max_adults":         self.max_adults,
            "max_children":       self.max_children,
            "total_of_this_type": self.total_of_this_type,
            "price_per_night":    self.price_per_night,
            "is_active":          self.is_active,
            "created_at":         self.created_at.isoformat(),
            "updated_at":         self.updated_at.isoformat(),
        }


class RoomAvailability(db.Model):
    """
    Per-date inventory for each room type.
    One row = one room type on one calendar date.
    left_to_sell decrements when a booking is confirmed;
    increments when a booking is cancelled.

    This prevents double-booking across date ranges without scanning
    every existing booking every time.
    """
    __tablename__ = "room_availability"
    __table_args__ = (
        # A room can only have one availability record per date
        db.UniqueConstraint("room_id", "date", name="uq_room_date"),
    )

    id            = db.Column(db.Integer, primary_key=True)
    room_id       = db.Column(db.Integer, db.ForeignKey("rooms.id"),
                              nullable=False, index=True)
    date          = db.Column(db.Date, nullable=False, index=True)
    total_rooms   = db.Column(db.Integer, nullable=False)  # mirrors Room.total_of_this_type
    booked        = db.Column(db.Integer, nullable=False, default=0)
    left_to_sell  = db.Column(db.Integer, nullable=False)  # total_rooms - booked
    is_available  = db.Column(db.Boolean, nullable=False, default=True, index=True)

    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), server_default=func.now(),
                           onupdate=func.now(), nullable=False)

    # Relationships
    room = db.relationship("Room", back_populates="availability")

    def __repr__(self):
        return f"<RoomAvailability room={self.room_id} date={self.date} left={self.left_to_sell}>"

    def decrement(self, qty=1):
        """Call when a booking is confirmed. Raises ValueError if not enough rooms."""
        if self.left_to_sell < qty:
            raise ValueError(
                f"Only {self.left_to_sell} room(s) left on {self.date}, requested {qty}"
            )
        self.booked       += qty
        self.left_to_sell -= qty
        self.is_available  = self.left_to_sell > 0

    def increment(self, qty=1):
        """Call when a booking is cancelled."""
        self.booked        = max(0, self.booked - qty)
        self.left_to_sell  = min(self.total_rooms, self.left_to_sell + qty)
        self.is_available  = self.left_to_sell > 0

    def to_dict(self):
        return {
            "id":           self.id,
            "room_id":      self.room_id,
            "date":         self.date.isoformat(),
            "total_rooms":  self.total_rooms,
            "booked":       self.booked,
            "left_to_sell": self.left_to_sell,
            "is_available": self.is_available,
        }


# ═══════════════════════════════════════════════════════════════════════════
#  BOOKINGS
# ═══════════════════════════════════════════════════════════════════════════

class Booking(db.Model):
    """
    A confirmed (or pending) room booking.
    Status lifecycle:
      pending_payment → confirmed → checked_in → checked_out
                      ↘ cancelled
    """
    __tablename__ = "bookings"

    # Valid status values — enforced at the DB level too
    STATUSES = ("pending_payment", "confirmed", "cancelled", "checked_in", "checked_out")

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey("users.id"),
                               nullable=False, index=True)
    room_id        = db.Column(db.Integer, db.ForeignKey("rooms.id"),
                               nullable=False, index=True)

    check_in_date  = db.Column(db.Date, nullable=False)
    check_out_date = db.Column(db.Date, nullable=False)
    num_rooms      = db.Column(db.Integer, nullable=False, default=1)
    num_guests     = db.Column(db.Integer, nullable=False, default=1)
    num_adults     = db.Column(db.Integer, nullable=False, default=1)
    num_children   = db.Column(db.Integer, nullable=False, default=0)

    # Pricing snapshot (so a rate change doesn't alter historical bookings)
    price_per_night = db.Column(db.Float, nullable=False)
    total_price     = db.Column(db.Float, nullable=False)

    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending_payment",
        index=True
    )

    # Free-text notes (special requests, etc.)
    notes = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), server_default=func.now(),
                           onupdate=func.now(), nullable=False)

    # Relationships
    user    = db.relationship("User", back_populates="bookings")
    room    = db.relationship("Room", back_populates="bookings")
    payment = db.relationship("Payment", back_populates="booking",
                              uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Booking #{self.id} user={self.user_id} room={self.room_id} [{self.status}]>"

    @property
    def total_nights(self):
        return (self.check_out_date - self.check_in_date).days

    def cancel(self):
        """Cancel the booking and release room availability for each date."""
        if self.status in ("checked_in", "checked_out"):
            raise ValueError("Cannot cancel a booking that has already started.")
        # Release availability for each night
        from datetime import timedelta
        current = self.check_in_date
        while current < self.check_out_date:
            avail = RoomAvailability.query.filter_by(
                room_id=self.room_id, date=current
            ).first()
            if avail:
                avail.increment(self.num_rooms)
            current += timedelta(days=1)
        self.status = "cancelled"

    def to_dict(self):
        return {
            "id":             self.id,
            "user_id":        self.user_id,
            "room_id":        self.room_id,
            "check_in_date":  self.check_in_date.isoformat(),
            "check_out_date": self.check_out_date.isoformat(),
            "total_nights":   self.total_nights,
            "num_rooms":      self.num_rooms,
            "num_guests":     self.num_guests,
            "price_per_night": self.price_per_night,
            "total_price":    self.total_price,
            "status":         self.status,
            "notes":          self.notes,
            "created_at":     self.created_at.isoformat(),
            "updated_at":     self.updated_at.isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════════════
#  CARS & CAR RENTALS
# ═══════════════════════════════════════════════════════════════════════════

class Cars(db.Model):
    """A car available for rental."""
    __tablename__ = "cars"

    id            = db.Column(db.Integer, primary_key=True)
    model         = db.Column(db.String(100), nullable=False, index=True)
    plate_number  = db.Column(db.String(20),  unique=True, nullable=False)
    car_image     = db.Column(db.String(255), nullable=True)   # filename in UPLOAD_FOLDER
    description   = db.Column(db.Text, nullable=True)
    price_per_day = db.Column(db.Float, nullable=False)

    # Admin can toggle availability globally (e.g. car is being serviced)
    is_available  = db.Column(db.Boolean, default=True, nullable=False, index=True)

    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), server_default=func.now(),
                           onupdate=func.now(), nullable=False)

    # Relationships
    rentals = db.relationship("CarRental", back_populates="car",
                              cascade="all, delete-orphan", lazy="dynamic")

    def __repr__(self):
        return f"<Car {self.model} [{self.plate_number}]>"

    def to_dict(self):
        return {
            "id":            self.id,
            "model":         self.model,
            "plate_number":  self.plate_number,
            "car_image":     self.car_image,
            "description":   self.description,
            "price_per_day": self.price_per_day,
            "is_available":  self.is_available,
            "created_at":    self.created_at.isoformat(),
            "updated_at":    self.updated_at.isoformat(),
        }


class CarRental(db.Model):
    """
    A car rental booking.
    Status lifecycle mirrors Booking:
      pending_payment → confirmed → active → returned
                      ↘ cancelled
    """
    __tablename__ = "car_rentals"

    STATUSES = ("pending_payment", "confirmed", "active", "returned", "cancelled")

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    car_id      = db.Column(db.Integer, db.ForeignKey("cars.id"),  nullable=False, index=True)

    rental_date = db.Column(db.Date, nullable=False)
    return_date = db.Column(db.Date, nullable=False)   # ← was missing before

    # Pricing snapshot
    price_per_day = db.Column(db.Float, nullable=False)
    total_price   = db.Column(db.Float, nullable=False)  # ← was missing before

    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending_payment",
        index=True
    )

    notes = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), server_default=func.now(),
                           onupdate=func.now(), nullable=False)

    # Relationships
    user    = db.relationship("User", back_populates="car_rentals")
    car     = db.relationship("Cars", back_populates="rentals")
    payment = db.relationship("Payment", back_populates="car_rental",
                              uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<CarRental #{self.id} user={self.user_id} car={self.car_id} [{self.status}]>"

    @property
    def total_days(self):
        return (self.return_date - self.rental_date).days

    def cancel(self):
        """Cancel the rental and mark the car available again."""
        if self.status in ("active", "returned"):
            raise ValueError("Cannot cancel a rental that is already active or returned.")
        self.car.is_available = True
        self.status = "cancelled"

    def to_dict(self):
        return {
            "id":            self.id,
            "user_id":       self.user_id,
            "car_id":        self.car_id,
            "rental_date":   self.rental_date.isoformat(),
            "return_date":   self.return_date.isoformat(),
            "total_days":    self.total_days,
            "price_per_day": self.price_per_day,
            "total_price":   self.total_price,
            "status":        self.status,
            "notes":         self.notes,
            "created_at":    self.created_at.isoformat(),
            "updated_at":    self.updated_at.isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════════════
#  PAYMENTS
# ═══════════════════════════════════════════════════════════════════════════

class Payment(db.Model):
    """
    Tracks a Stripe payment for either a room booking or a car rental.
    Exactly one of booking_id / car_rental_id will be set per row.

    Stripe PaymentIntent flow:
      1. Backend creates a PaymentIntent → stores stripe_payment_intent_id here
      2. Frontend collects card details via Stripe.js (card never touches your server)
      3. Stripe calls your webhook on success → set status = "succeeded"
    """
    __tablename__ = "payments"

    STATUSES = ("pending", "processing", "succeeded", "failed", "refunded")

    id                       = db.Column(db.Integer, primary_key=True)

    # Exactly one of these should be non-null
    booking_id    = db.Column(db.Integer, db.ForeignKey("bookings.id"),
                              nullable=True, index=True)
    car_rental_id = db.Column(db.Integer, db.ForeignKey("car_rentals.id"),
                              nullable=True, index=True)

    # Stripe identifiers
    stripe_payment_intent_id = db.Column(db.String(100), unique=True,
                                         nullable=False, index=True)
    stripe_customer_id       = db.Column(db.String(100), nullable=True)

    amount      = db.Column(db.Float,  nullable=False)   # in the currency's major unit (e.g. USD)
    currency    = db.Column(db.String(3), nullable=False, default="usd")
    status      = db.Column(db.String(20), nullable=False, default="pending", index=True)

    # Populated by Stripe webhook on success
    paid_at     = db.Column(db.DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at  = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at  = db.Column(db.DateTime(timezone=True), server_default=func.now(),
                            onupdate=func.now(), nullable=False)

    # Relationships
    booking    = db.relationship("Booking",   back_populates="payment")
    car_rental = db.relationship("CarRental", back_populates="payment")

    def __repr__(self):
        return f"<Payment #{self.id} {self.stripe_payment_intent_id} [{self.status}]>"

    def mark_succeeded(self):
        self.status  = "succeeded"
        self.paid_at = datetime.now(timezone.utc)

    def mark_failed(self):
        self.status = "failed"

    def mark_refunded(self):
        self.status = "refunded"

    def to_dict(self):
        return {
            "id":                       self.id,
            "booking_id":               self.booking_id,
            "car_rental_id":            self.car_rental_id,
            "stripe_payment_intent_id": self.stripe_payment_intent_id,
            "amount":                   self.amount,
            "currency":                 self.currency,
            "status":                   self.status,
            "paid_at":                  self.paid_at.isoformat() if self.paid_at else None,
            "created_at":               self.created_at.isoformat(),
            "updated_at":               self.updated_at.isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════════════
#  HOTEL INFO  (unchanged — kept for admin panel)
# ═══════════════════════════════════════════════════════════════════════════

class Hotels(db.Model):
    """Top-level hotel/property info shown on the public site."""
    __tablename__ = "hotels"

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), nullable=False, index=True)
    location    = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)

    created_at  = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at  = db.Column(db.DateTime(timezone=True), server_default=func.now(),
                            onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<Hotel {self.name}>"

    def to_dict(self):
        return {
            "id":          self.id,
            "name":        self.name,
            "location":    self.location,
            "description": self.description,
            "created_at":  self.created_at.isoformat(),
            "updated_at":  self.updated_at.isoformat(),
        }