"""
bookings.py — FM Residences
User-facing booking and car rental routes.

FIXES APPLIED:
  - BUG 2:  search() now passes `rooms=` (not `bookable_rooms=`) + all
            context vars the template needs (checkin, checkout, nights,
            rooms_needed, num_guests)
  - BUG 2:  room dicts are enriched with template-expected keys
            (price_per_night, description, room_number, etc.)
  - BUG 8:  create_booking() no longer requires `total_guests` in POST
            body — computes it from total_adults + total_children
  - BUG 11: redirects to auth.login_page (GET) not auth.login (POST)
"""

from datetime import date, timedelta

from flask import (Blueprint, request, jsonify, render_template,
                   redirect, url_for, flash, session, current_app)
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from src.models import db, Booking, CarRental, Cars, Room, RoomAvailability
from src.room_search import search_available_rooms

bookings_bp = Blueprint("bookings", __name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Helper: parse dates sent by Bootstrap Datepicker (dd-mm-yyyy OR yyyy-mm-dd)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_date(value: str) -> date:
    """
    Accept dd-mm-yyyy (datepicker default) OR yyyy-mm-dd (ISO).
    Raises ValueError if neither format matches.
    """
    value = value.strip().replace("/", "-").replace(".", "-")
    parts = value.split("-")
    if len(parts) != 3:
        raise ValueError(f"Cannot parse date: {value!r}")
    # dd-mm-yyyy: first part is 2 digits and <= 31
    if len(parts[0]) == 2 and int(parts[0]) <= 31:
        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
    else:
        # yyyy-mm-dd
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    return date(y, m, d)


# ─────────────────────────────────────────────────────────────────────────────
#  Helper: get current user from JWT header OR Flask session (hybrid auth)
# ─────────────────────────────────────────────────────────────────────────────

def get_current_user_id():
    """Return user_id from JWT header or Flask session, whichever is present."""
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity:
            return int(identity)
    except Exception:
        pass
    return session.get("user_id")


# ─────────────────────────────────────────────────────────────────────────────
#  Helper: enrich room search dict with template-expected field names
# ─────────────────────────────────────────────────────────────────────────────

def _enrich_room_dict(room_dict: dict) -> dict:
    """
    FIX BUG 2: room_search.py returns keys like price_per_day, room_info.
    offer_rooms.html (and Cars.html / checkout.html) expect:
      room.price_per_night, room.description, room.room_number,
      room.max_adults, room.bed_type, room.room_image, room.room_type, room.id
    Add aliases so the template works without changes.
    """
    room_dict.setdefault("price_per_night", room_dict.get("price_per_day", 0))
    room_dict.setdefault("description",     room_dict.get("room_info", ""))
    room_dict.setdefault("room_number",     "—")
    room_dict.setdefault("max_adults",      room_dict.get("max_guests", 2))
    room_dict.setdefault("bed_type",        None)
    room_dict.setdefault("id",              room_dict.get("room_id"))
    return room_dict


# ═════════════════════════════════════════════════════════════════════════════
#  SEARCH  (the index form POSTs here via 307 redirect from /)
# ═════════════════════════════════════════════════════════════════════════════

@bookings_bp.route("/search", methods=["POST"])
def search():
    """
    Receives the search form from index.html.
    Parses dd-mm-yyyy dates from Bootstrap Datepicker.
    Runs availability check and renders offer_rooms.html with results.
    """
    form = request.form

    try:
        checkin  = _parse_date(form.get("checkin",  ""))
        checkout = _parse_date(form.get("checkout", ""))
    except (ValueError, IndexError):
        flash("Invalid dates. Please select dates using the calendar.")
        return redirect(url_for("index"))

    if checkout <= checkin:
        flash("Check-out must be after check-in.")
        return redirect(url_for("index"))

    if checkin < date.today():
        flash("Check-in date cannot be in the past.")
        return redirect(url_for("index"))

    rooms_requested = int(form.get("rooms",   1) or 1)
    adults          = int(form.get("adults",  1) or 1)
    children_opt    = form.get("children", "none")
    first_child     = form.get("first_child",  "")
    second_child    = form.get("second_child", "")

    total_children = 0
    if children_opt == "one":
        total_children = 1
        second_child   = ""
    elif children_opt == "two":
        total_children = 2

    total_guests = adults + total_children
    total_days   = (checkout - checkin).days

    bookable_rooms = search_available_rooms(
        checkin         = checkin,
        checkout        = checkout,
        rooms_requested = rooms_requested,
        adults          = adults,
        total_children  = total_children,
        first_child     = first_child,
        second_child    = second_child,
        total_days      = total_days,
        total_guests    = total_guests,
    )

    if not bookable_rooms:
        flash("No rooms available for the selected dates and guests. Try different dates.")
        return redirect(url_for("index"))

    # FIX BUG 2: enrich dicts and pass correct variable name `rooms`
    enriched = [_enrich_room_dict(r) for r in bookable_rooms]

    return render_template(
        "offer_rooms.html",
        rooms        = enriched,
        checkin      = checkin.strftime("%d-%m-%Y"),
        checkout     = checkout.strftime("%d-%m-%Y"),
        nights       = total_days,
        rooms_needed = rooms_requested,
        num_guests   = total_guests,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  ROOM BOOKINGS
# ═════════════════════════════════════════════════════════════════════════════

@bookings_bp.route("/bookings", methods=["POST"])
def create_booking():
    """
    Create a booking from the offer_rooms.html SELECT button.
    Decrements RoomAvailability for each night.
    Redirects to the Stripe checkout page on success.
    """
    user_id = get_current_user_id()
    if not user_id:
        flash("Please log in to make a booking.")
        # FIX BUG 11: login_page is the GET page, login is the POST JSON endpoint
        return redirect(url_for("auth.login_page"))

    data = request.form if request.form else request.get_json()

    # FIX BUG 8: removed `total_guests` from required — computed below instead
    required = ("room_type", "from_date", "to_date", "total_rooms",
                "total_adults", "total_price", "room_price_per_day")
    missing = [f for f in required if not data.get(f)]
    if missing:
        flash(f"Missing booking data: {', '.join(missing)}")
        return redirect(url_for("index"))

    try:
        check_in  = _parse_date(data["from_date"])
        check_out = _parse_date(data["to_date"])
    except (ValueError, IndexError):
        flash("Invalid date format in booking request.")
        return redirect(url_for("index"))

    num_rooms    = int(data.get("total_rooms",    1) or 1)
    num_adults   = int(data.get("total_adults",   1) or 1)
    num_children = int(data.get("total_children", 0) or 0)
    # FIX BUG 8: compute total_guests from its parts instead of requiring it in form
    num_guests   = num_adults + num_children
    price_per_night = float(data.get("room_price_per_day", 0) or 0)
    total_price     = float(data.get("total_price",        0) or 0)
    notes           = data.get("notes", "")

    room_type = data.get("room_type", "").strip()
    room = Room.query.filter_by(room_type=room_type, is_active=True).first()
    if not room:
        flash(f"Room type '{room_type}' not found.")
        return redirect(url_for("index"))

    avail_rows = []
    current = check_in
    while current < check_out:
        avail = RoomAvailability.query.filter_by(
            room_id=room.id, date=current
        ).with_for_update().first()

        if not avail or avail.left_to_sell < num_rooms:
            db.session.rollback()
            flash(f"Sorry — {room_type} is no longer available on {current.strftime('%d %B')}.")
            return redirect(url_for("index"))

        avail_rows.append(avail)
        current += timedelta(days=1)

    for avail in avail_rows:
        avail.decrement(num_rooms)

    booking = Booking(
        user_id         = user_id,
        room_id         = room.id,
        check_in_date   = check_in,
        check_out_date  = check_out,
        num_rooms       = num_rooms,
        num_guests      = num_guests,
        num_adults      = num_adults,
        num_children    = num_children,
        price_per_night = price_per_night,
        total_price     = total_price,
        status          = "pending_payment",
        notes           = notes,
    )
    db.session.add(booking)
    db.session.commit()

    return redirect(url_for("bookings.checkout", booking_id=booking.id))


@bookings_bp.route("/bookings/my", methods=["GET"])
def my_bookings():
    """Render the logged-in user's booking and rental history page."""
    user_id = get_current_user_id()
    if not user_id:
        flash("Please log in to view your bookings.")
        return redirect(url_for("auth.login_page"))  # FIX BUG 11

    bookings = (Booking.query
                .filter_by(user_id=user_id)
                .order_by(Booking.check_in_date.desc())
                .all())

    rentals = (CarRental.query
               .filter_by(user_id=user_id)
               .order_by(CarRental.rental_date.desc())
               .all())

    return render_template("My_bookings.html", bookings=bookings, rentals=rentals)


@bookings_bp.route("/bookings/<int:booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    """User cancels their own booking."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Login required"}), 401

    booking = db.session.get(Booking, booking_id)
    if not booking:
        return jsonify({"error": "Booking not found"}), 404
    if booking.user_id != user_id:
        return jsonify({"error": "Unauthorised"}), 403

    try:
        booking.cancel()
        db.session.commit()
        flash("Booking cancelled successfully.")
    except ValueError as e:
        db.session.rollback()
        flash(str(e))

    return redirect(url_for("bookings.my_bookings"))


# ═════════════════════════════════════════════════════════════════════════════
#  CAR RENTALS
# ═════════════════════════════════════════════════════════════════════════════

@bookings_bp.route("/cars", methods=["GET"])
def available_cars():
    """Show all available cars for rental."""
    cars = Cars.query.filter_by(is_available=True).order_by(Cars.model).all()
    today = date.today().isoformat()
    return render_template("Cars.html", cars=cars, today=today)


@bookings_bp.route("/car-rentals", methods=["POST"])
def create_car_rental():
    """
    Create a car rental booking.
    Marks the car as unavailable immediately (one rental at a time per car).
    """
    user_id = get_current_user_id()
    if not user_id:
        flash("Please log in to rent a car.")
        return redirect(url_for("auth.login_page"))  # FIX BUG 11

    data = request.form if request.form else request.get_json()

    required = ("car_id", "rental_date", "return_date")
    missing = [f for f in required if not data.get(f)]
    if missing:
        flash(f"Missing rental data: {', '.join(missing)}")
        return redirect(url_for("bookings.available_cars"))

    try:
        rental_date = _parse_date(data["rental_date"])
        return_date = _parse_date(data["return_date"])
    except (ValueError, IndexError):
        flash("Invalid rental dates.")
        return redirect(url_for("bookings.available_cars"))

    if return_date <= rental_date:
        flash("Return date must be after rental date.")
        return redirect(url_for("bookings.available_cars"))

    if rental_date < date.today():
        flash("Rental date cannot be in the past.")
        return redirect(url_for("bookings.available_cars"))

    car = db.session.get(Cars, int(data["car_id"]))
    if not car:
        flash("Car not found.")
        return redirect(url_for("bookings.available_cars"))

    if not car.is_available:
        flash(f"Sorry — {car.model} is no longer available for those dates.")
        return redirect(url_for("bookings.available_cars"))

    total_days  = (return_date - rental_date).days
    total_price = car.price_per_day * total_days

    car.is_available = False

    rental = CarRental(
        user_id       = user_id,
        car_id        = car.id,
        rental_date   = rental_date,
        return_date   = return_date,
        price_per_day = car.price_per_day,
        total_price   = total_price,
        status        = "pending_payment",
        notes         = data.get("notes", ""),
    )
    db.session.add(rental)
    db.session.commit()

    return redirect(url_for("bookings.checkout", rental_id=rental.id))


@bookings_bp.route("/car-rentals/<int:rental_id>/cancel", methods=["POST"])
def cancel_rental(rental_id):
    """User cancels their own car rental."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Login required"}), 401

    rental = db.session.get(CarRental, rental_id)
    if not rental:
        return jsonify({"error": "Rental not found"}), 404
    if rental.user_id != user_id:
        return jsonify({"error": "Unauthorised"}), 403

    try:
        rental.cancel()
        db.session.commit()
        flash("Car rental cancelled.")
    except ValueError as e:
        db.session.rollback()
        flash(str(e))

    return redirect(url_for("bookings.my_bookings"))


# ═════════════════════════════════════════════════════════════════════════════
#  CHECKOUT  (serves the Stripe payment form)
# ═════════════════════════════════════════════════════════════════════════════

@bookings_bp.route("/checkout")
def checkout():
    """
    Render the Stripe checkout page.
    Accepts ?booking_id=X or ?rental_id=X
    """
    user_id = get_current_user_id()
    if not user_id:
        flash("Please log in to complete your booking.")
        return redirect(url_for("auth.login_page"))  # FIX BUG 11

    booking_id = request.args.get("booking_id", type=int)
    rental_id  = request.args.get("rental_id",  type=int)

    booking = None
    rental  = None

    if booking_id:
        booking = db.session.get(Booking, booking_id)
        if not booking or booking.user_id != user_id:
            flash("Booking not found.")
            return redirect(url_for("index"))
        if booking.status != "pending_payment":
            flash(f"This booking is already '{booking.status}'.")
            return redirect(url_for("bookings.my_bookings"))

    elif rental_id:
        rental = db.session.get(CarRental, rental_id)
        if not rental or rental.user_id != user_id:
            flash("Rental not found.")
            return redirect(url_for("bookings.available_cars"))
        if rental.status != "pending_payment":
            flash(f"This rental is already '{rental.status}'.")
            return redirect(url_for("bookings.my_bookings"))
    else:
        return redirect(url_for("index"))

    publishable_key = current_app.config.get("STRIPE_PUBLISHABLE_KEY", "")
    return render_template("checkout.html",
                           booking=booking,
                           rental=rental,
                           publishable_key=publishable_key)


# ═════════════════════════════════════════════════════════════════════════════
#  CONFIRMATION PAGE
# ═════════════════════════════════════════════════════════════════════════════

@bookings_bp.route("/confirmation")
def confirmation():
    """Shown after Stripe.js redirects back on payment success."""
    user_id = get_current_user_id()
    if not user_id:
        return redirect(url_for("auth.login_page"))

    booking_id = request.args.get("booking_id", type=int)
    rental_id  = request.args.get("rental_id",  type=int)

    booking = None
    rental  = None

    if booking_id:
        booking = db.session.get(Booking, booking_id)
        if not booking or booking.user_id != user_id:
            return redirect(url_for("index"))

    elif rental_id:
        rental = db.session.get(CarRental, rental_id)
        if not rental or rental.user_id != user_id:
            return redirect(url_for("bookings.available_cars"))

    return render_template("confirmation.html", booking=booking, rental=rental)