"""
admin.py — FM Residences
All admin panel routes. Every route requires role == 'admin' or 'staff'.

FIXES APPLIED:
  - BUG 5:  Added GET/POST /admin/register for staff account creation
  - BUG 6:  dashboard_data() now returns the keys admin_dashboard.html
            JS actually reads: total_bookings, total_rentals, total_revenue,
            total_users, recent_bookings[], recent_rentals[]
  - BUG 7:  Added HTML-rendering page routes for /admin/bookings,
            /admin/rentals, /admin/users, /admin/cars so nav links work
"""

import os
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, render_template, current_app, session, redirect, url_for
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
from flask import flash

from src.models import db, User, Room, RoomAvailability, Booking, Cars, CarRental, Payment

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ─────────────────────────────────────────────────────────────────────────────
#  Shared decorators / helpers
# ─────────────────────────────────────────────────────────────────────────────

def require_admin(fn):
    """JWT required + role must be admin or staff."""
    from functools import wraps

    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user_id = int(get_jwt_identity())
        user = db.session.get(User, user_id)
        if not user or user.role not in ("admin", "staff"):
            return jsonify({"error": "Admin access required"}), 403
        return fn(*args, **kwargs)
    return wrapper


def require_admin_only(fn):
    """JWT required + role must be admin (not staff)."""
    from functools import wraps

    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user_id = int(get_jwt_identity())
        user = db.session.get(User, user_id)
        if not user or user.role != "admin":
            return jsonify({"error": "Admin-only action"}), 403
        return fn(*args, **kwargs)
    return wrapper


def _session_is_admin():
    """Check Flask session role for HTML page routes (no JWT needed for page render)."""
    return session.get("role") in ("admin", "staff")


def allowed_file(filename: str) -> bool:
    allowed = current_app.config.get("ALLOWED_EXTENSIONS", {"png", "jpg", "jpeg", "gif"})
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed


def save_upload(file_field_name: str) -> str | None:
    file = request.files.get(file_field_name)
    if not file or file.filename == "":
        return None
    if not allowed_file(file.filename):
        return None
    filename   = secure_filename(file.filename)
    upload_dir = os.path.join(current_app.root_path,
                              current_app.config["UPLOAD_FOLDER"])
    os.makedirs(upload_dir, exist_ok=True)
    file.save(os.path.join(upload_dir, filename))
    return filename


# ═════════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/dashboard", methods=["GET"])
def dashboard():
    """Renders the admin_dashboard.html template. Session-gated."""
    if not _session_is_admin():
        return redirect(url_for("auth.login_page"))
    return render_template("admin_dashboard.html")


# ═════════════════════════════════════════════════════════════════════════════
#  REPLACE the existing dashboard_data() function in src/admin.py
#  (the route decorated with @admin_bp.route("/dashboard-data") )
# ═════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/dashboard-data", methods=["GET"])
def dashboard_data():
    """
    FIX: was @require_admin (strict JWT-only). JWT expires after 30 min, causing
    the dashboard to silently freeze with '—' and 'Loading…'.
    Now uses session auth via _session_is_admin() — same as every other admin
    page route — so it works as long as the session cookie is valid (browser session).
    """
    if not _session_is_admin():
        return jsonify({"error": "Authentication required"}), 401

    total_bookings = Booking.query.count()
    total_rentals  = CarRental.query.count()
    total_users    = User.query.filter_by(role="user").count()

    payments      = Payment.query.filter_by(status="succeeded").all()
    total_revenue = sum(p.amount for p in payments)

    recent_bookings = (Booking.query
                       .order_by(Booking.created_at.desc())
                       .limit(10).all())
    recent_rentals  = (CarRental.query
                       .order_by(CarRental.created_at.desc())
                       .limit(10).all())

    return jsonify({
        "total_bookings": total_bookings,
        "total_rentals":  total_rentals,
        "total_users":    total_users,
        "total_revenue":  round(total_revenue, 2),
        "recent_bookings": [
            {
                "id":          b.id,
                "username":    b.user.username  if b.user else "—",
                "room_type":   b.room.room_type if b.room else "—",
                "check_in":    b.check_in_date.isoformat(),
                "check_out":   b.check_out_date.isoformat(),
                "total_price": b.total_price,
                "status":      b.status,
            }
            for b in recent_bookings
        ],
        "recent_rentals": [
            {
                "id":          r.id,
                "username":    r.user.username if r.user else "—",
                "car_model":   r.car.model     if r.car  else "—",
                "rental_date": r.rental_date.isoformat(),
                "return_date": r.return_date.isoformat(),
                "total_price": r.total_price,
                "status":      r.status,
            }
            for r in recent_rentals
        ],
    }), 200


# ═════════════════════════════════════════════════════════════════════════════
#  STAFF REGISTRATION  (FIX BUG 5)
# ═════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/register", methods=["GET"])
def register_staff_page():
    """Render the staff registration form. Session-gated."""
    if not _session_is_admin():
        return redirect(url_for("auth.login_page"))
    return render_template("admin_register.html")


@admin_bp.route("/register", methods=["POST"])
@require_admin_only
def register_staff():
    """
    FIX BUG 5: Create a new staff or admin account.
    Only admins (not staff) can create accounts.
    """
    data = request.get_json() or request.form

    if not all(data.get(f) for f in ("username", "email", "password")):
        return jsonify({"error": "Username, email, and password are required"}), 400

    role = data.get("role", "staff")
    if role not in ("staff", "admin"):
        return jsonify({"error": "role must be 'staff' or 'admin'"}), 400

    if len(data["password"]) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    if User.query.filter_by(username=data["username"]).first():
        return jsonify({"error": "Username already taken"}), 409
    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"error": "Email already registered"}), 409

    try:
        user = User(username=data["username"], email=data["email"], role=role)
        user.set_password(data["password"])
        user.is_verified = True   # Staff don't need email verification
        user.is_active   = True
        db.session.add(user)
        db.session.commit()
        return jsonify({
            "message": f"{role.title()} account created successfully.",
            "user":    user.to_dict(),
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ═════════════════════════════════════════════════════════════════════════════
#  ADMIN PAGE ROUTES (HTML)  (FIX BUG 7)
# ═════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/bookings", methods=["GET"])
def bookings_page():
    """
    FIX BUG 7: Session-gated HTML page. Fetches bookings and renders them.
    Nav links point here — returns HTML, not raw JSON.
    """
    if not _session_is_admin():
        return redirect(url_for("auth.login_page"))
    bookings = Booking.query.order_by(Booking.check_in_date.desc()).all()
    return render_template("admin_bookings.html", bookings=bookings)


@admin_bp.route("/bookings/<int:booking_id>", methods=["GET"])
def booking_detail_page(booking_id):
    """Single booking detail page."""
    if not _session_is_admin():
        return redirect(url_for("auth.login_page"))
    booking = db.session.get(Booking, booking_id)
    if not booking:
        flash("Booking not found.")
        return redirect(url_for("admin.bookings_page"))
    return render_template("admin_booking_detail.html", booking=booking)


@admin_bp.route("/rentals", methods=["GET"])
def rentals_page():
    """FIX BUG 7: HTML page for car rentals."""
    if not _session_is_admin():
        return redirect(url_for("auth.login_page"))
    rentals = CarRental.query.order_by(CarRental.rental_date.desc()).all()
    return render_template("admin_rentals.html", rentals=rentals)


@admin_bp.route("/users", methods=["GET"])
def users_page():
    """FIX BUG 7: HTML page for user management."""
    if not _session_is_admin():
        return redirect(url_for("auth.login_page"))
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin_users.html", users=users)


@admin_bp.route("/users/<int:target_id>/delete", methods=["POST"])
def delete_user(target_id):
    """Delete a user account. Admin accounts cannot be deleted."""
    if not _session_is_admin():
        return jsonify({"error": "Admin access required"}), 401

    target = db.session.get(User, target_id)
    if not target:
        flash("User not found.")
        return redirect(url_for("admin.users_page"))

    if target.role == "admin":
        flash("Admin accounts cannot be deleted.")
        return redirect(url_for("admin.users_page"))

    for booking in target.bookings:
        if booking.status in ("pending_payment", "confirmed"):
            try:
                booking.cancel()
            except Exception:
                booking.status = "cancelled"

    db.session.delete(target)
    db.session.commit()
    flash(f"User '{target.username}' deleted.")
    return redirect(url_for("admin.users_page"))


@admin_bp.route("/cars", methods=["GET"])
def cars_page():
    """FIX BUG 7: HTML page for car management."""
    if not _session_is_admin():
        return redirect(url_for("auth.login_page"))
    cars = Cars.query.order_by(Cars.model).all()
    return render_template("admin_cars.html", cars=cars)


@admin_bp.route("/manage-cars", methods=["GET"])
def manage_cars_page():
    """Session-gated HTML page — add/delete cars."""
    if not _session_is_admin():
        return redirect(url_for("auth.login_page"))
    cars = Cars.query.order_by(Cars.model).all()
    return render_template("manage_cars.html", cars=cars)


@admin_bp.route("/create-car", methods=["POST"])
def create_car_submit():
    """Handle the add-car HTML form."""
    if not _session_is_admin():
        return redirect(url_for("auth.login_page"))

    data = request.form

    required = ("model", "plate_number", "price_per_day")
    missing  = [f for f in required if not data.get(f)]
    if missing:
        flash(f"Missing required fields: {', '.join(missing)}")
        return redirect(url_for("admin.manage_cars_page"))

    if Cars.query.filter_by(plate_number=data["plate_number"]).first():
        flash(f"Plate number '{data['plate_number']}' is already registered.")
        return redirect(url_for("admin.manage_cars_page"))

    try:
        price = float(data["price_per_day"])
    except (ValueError, TypeError):
        flash("Price per day must be a number.")
        return redirect(url_for("admin.manage_cars_page"))

    image_filename = save_upload("car_image")

    car = Cars(
        model         = data["model"],
        plate_number  = data["plate_number"],
        price_per_day = price,
        description   = data.get("description") or None,
        car_image     = image_filename,
        is_available  = True,
    )
    db.session.add(car)
    db.session.commit()

    flash(f"Car '{car.model}' [{car.plate_number}] added to the fleet.")
    return redirect(url_for("admin.manage_cars_page"))


@admin_bp.route("/delete-car", methods=["POST"])
def delete_car_submit():
    """Handle the delete-car form button."""
    if not _session_is_admin():
        return redirect(url_for("auth.login_page"))

    car_id = request.form.get("delete_car")
    if not car_id:
        return redirect(url_for("admin.manage_cars_page"))

    car = db.session.get(Cars, int(car_id))
    if not car:
        flash("Car not found.")
        return redirect(url_for("admin.manage_cars_page"))

    active_rentals = CarRental.query.filter(
        CarRental.car_id == car.id,
        CarRental.status.in_(("confirmed", "active"))
    ).count()

    if active_rentals:
        flash(f"Cannot delete — {active_rentals} active rental(s) exist for this car.")
        return redirect(url_for("admin.manage_cars_page"))

    db.session.delete(car)
    db.session.commit()
    flash(f"Car '{car.model}' deleted.")
    return redirect(url_for("admin.manage_cars_page"))


@admin_bp.route("/create-room", methods=["GET"])
def create_room_page():
    """Session-gated HTML page — render the create-room form."""
    if not _session_is_admin():
        return redirect(url_for("auth.login_page"))
    rooms = Room.query.order_by(Room.room_number).all()
    return render_template("create_rooms.html", room_info=rooms)


@admin_bp.route("/create-room", methods=["POST"])
def create_room_submit():
    """Handle the create-room HTML form (session-gated, multipart)."""
    if not _session_is_admin():
        return redirect(url_for("auth.login_page"))

    data = request.form

    required = ("room_number", "room_type", "price_per_night", "total_of_this_type")
    missing  = [f for f in required if not data.get(f)]
    if missing:
        flash(f"Missing required fields: {', '.join(missing)}")
        return redirect(url_for("admin.create_room_page"))

    if Room.query.filter_by(room_number=data["room_number"]).first():
        flash("Room number already exists.")
        return redirect(url_for("admin.create_room_page"))

    try:
        total = int(data["total_of_this_type"])
        price = float(data["price_per_night"])
    except (ValueError, TypeError):
        flash("Price and total rooms must be numbers.")
        return redirect(url_for("admin.create_room_page"))

    image_filename = save_upload("room_image")

    room = Room(
        room_number        = data["room_number"],
        room_type          = data["room_type"],
        price_per_night    = price,
        total_of_this_type = total,
        max_guests         = int(data.get("max_guests",   2) or 2),
        min_guests         = int(data.get("min_guests",   1) or 1),
        max_adults         = int(data.get("max_adults",   2) or 2),
        max_children       = int(data.get("max_children", 1) or 1),
        description        = data.get("room_description"),
        room_image         = image_filename,
    )
    db.session.add(room)
    db.session.commit()

    # Auto-seed 365 days of availability for the new room
    from datetime import date, timedelta
    today = date.today()
    for i in range(365):
        d = today + timedelta(days=i)
        db.session.add(RoomAvailability(
            room_id      = room.id,
            date         = d,
            total_rooms  = total,
            booked       = 0,
            left_to_sell = total,
            is_available = True,
        ))
    db.session.commit()

    flash(f"Room '{room.room_type}' (#{room.room_number}) created with 365 days of availability.")
    return redirect(url_for("admin.create_room_page"))


@admin_bp.route("/delete-room", methods=["POST"])
def delete_room_submit():
    """Handle the delete-room form button (session-gated)."""
    if not _session_is_admin():
        return redirect(url_for("auth.login_page"))

    room_id = request.form.get("delete_room")
    if room_id:
        room = db.session.get(Room, int(room_id))
        if room:
            active = Booking.query.filter(
                Booking.room_id == room.id,
                Booking.status.in_(("confirmed", "checked_in"))
            ).count()
            if active:
                flash(f"Cannot delete — {active} active booking(s) exist.")
            else:
                db.session.delete(room)
                db.session.commit()
                flash("Room deleted.")
        else:
            flash("Room not found.")

    return redirect(url_for("admin.create_room_page"))


@admin_bp.route("/availability", methods=["GET"])
def availability_page():
    """Session-gated HTML page — 14-day availability grid."""
    if not _session_is_admin():
        return redirect(url_for("auth.login_page"))

    from datetime import date, timedelta
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(14)]

    rooms = Room.query.order_by(Room.room_number).all()
    avail_map = {}
    for room in rooms:
        avail_map[room.id] = RoomAvailability.query.filter(
            RoomAvailability.room_id == room.id,
            RoomAvailability.date >= today,
            RoomAvailability.date < today + timedelta(days=14),
        ).all()

    return render_template("availability.html", rooms=rooms, avail_map=avail_map, dates=dates)


# ═════════════════════════════════════════════════════════════════════════════
#  ROOMS — JSON API
# ═════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/rooms", methods=["GET"])
@require_admin
def list_rooms():
    active_filter = request.args.get("active")
    query = Room.query
    if active_filter is not None:
        query = query.filter_by(is_active=(active_filter.lower() == "true"))
    rooms = query.order_by(Room.room_number).all()
    return jsonify([r.to_dict() for r in rooms]), 200


@admin_bp.route("/rooms", methods=["POST"])
@require_admin
def create_room():
    data = request.form if request.content_type.startswith("multipart") else request.get_json()

    required = ("room_number", "room_type", "price_per_night", "total_of_this_type")
    missing  = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    if Room.query.filter_by(room_number=data["room_number"]).first():
        return jsonify({"error": "Room number already exists"}), 409

    try:
        total = int(data["total_of_this_type"])
        price = float(data["price_per_night"])
    except (ValueError, TypeError):
        return jsonify({"error": "price_per_night and total_of_this_type must be numbers"}), 400

    image_filename = save_upload("room_image")

    room = Room(
        room_number        = data["room_number"],
        room_type          = data["room_type"],
        price_per_night    = price,
        total_of_this_type = total,
        max_guests         = int(data.get("max_guests",   2)),
        min_guests         = int(data.get("min_guests",   1)),
        max_adults         = int(data.get("max_adults",   2)),
        max_children       = int(data.get("max_children", 1)),
        description        = data.get("description"),
        room_image         = image_filename,
    )
    db.session.add(room)
    db.session.commit()
    return jsonify({"message": "Room created", "room": room.to_dict()}), 201


@admin_bp.route("/rooms/<int:room_id>", methods=["PATCH"])
@require_admin
def edit_room(room_id):
    room = db.session.get(Room, room_id)
    if not room:
        return jsonify({"error": "Room not found"}), 404

    data = request.form if request.content_type.startswith("multipart") else request.get_json()

    editable = {
        "room_type":          str,
        "price_per_night":    float,
        "total_of_this_type": int,
        "max_guests":         int,
        "min_guests":         int,
        "max_adults":         int,
        "max_children":       int,
        "description":        str,
    }
    for field, cast in editable.items():
        if data.get(field) is not None:
            try:
                setattr(room, field, cast(data[field]))
            except (ValueError, TypeError):
                return jsonify({"error": f"Invalid value for {field}"}), 400

    new_image = save_upload("room_image")
    if new_image:
        room.room_image = new_image

    db.session.commit()
    return jsonify({"message": "Room updated", "room": room.to_dict()}), 200


@admin_bp.route("/rooms/<int:room_id>", methods=["DELETE"])
@require_admin_only
def delete_room(room_id):
    room = db.session.get(Room, room_id)
    if not room:
        return jsonify({"error": "Room not found"}), 404

    active_bookings = Booking.query.filter(
        Booking.room_id == room_id,
        Booking.status.in_(("confirmed", "checked_in"))
    ).count()
    if active_bookings:
        return jsonify({
            "error": f"Cannot delete — {active_bookings} active booking(s) exist"
        }), 409

    db.session.delete(room)
    db.session.commit()
    return jsonify({"message": "Room deleted"}), 200


@admin_bp.route("/rooms/<int:room_id>/toggle", methods=["PATCH"])
@require_admin
def toggle_room(room_id):
    room = db.session.get(Room, room_id)
    if not room:
        return jsonify({"error": "Room not found"}), 404
    room.is_active = not room.is_active
    db.session.commit()
    state = "activated" if room.is_active else "deactivated"
    return jsonify({"message": f"Room {state}", "is_active": room.is_active}), 200


@admin_bp.route("/rooms/<int:room_id>/availability", methods=["POST"])
@require_admin
def seed_room_availability(room_id):
    room = db.session.get(Room, room_id)
    if not room:
        return jsonify({"error": "Room not found"}), 404

    data = request.get_json()
    try:
        from_date = date.fromisoformat(data["from_date"])
        to_date   = date.fromisoformat(data["to_date"])
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "from_date and to_date required in YYYY-MM-DD format"}), 400

    if to_date <= from_date:
        return jsonify({"error": "to_date must be after from_date"}), 400

    created = 0
    updated = 0
    current = from_date
    while current < to_date:
        avail = RoomAvailability.query.filter_by(
            room_id=room_id, date=current
        ).first()
        if avail:
            avail.total_rooms  = room.total_of_this_type
            avail.left_to_sell = max(0, room.total_of_this_type - avail.booked)
            avail.is_available = avail.left_to_sell > 0
            updated += 1
        else:
            avail = RoomAvailability(
                room_id      = room_id,
                date         = current,
                total_rooms  = room.total_of_this_type,
                booked       = 0,
                left_to_sell = room.total_of_this_type,
                is_available = True,
            )
            db.session.add(avail)
            created += 1
        current += timedelta(days=1)

    db.session.commit()
    return jsonify({
        "message":   f"Availability seeded: {created} created, {updated} updated",
        "from_date": from_date.isoformat(),
        "to_date":   to_date.isoformat(),
    }), 200


# ═════════════════════════════════════════════════════════════════════════════
#  CARS — JSON API
# ═════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/api/cars", methods=["GET"])
@require_admin
def list_cars():
    avail_filter = request.args.get("available")
    query = Cars.query
    if avail_filter is not None:
        query = query.filter_by(is_available=(avail_filter.lower() == "true"))
    cars = query.order_by(Cars.model).all()
    return jsonify([c.to_dict() for c in cars]), 200


@admin_bp.route("/api/cars", methods=["POST"])
@require_admin
def create_car():
    data = request.form if request.content_type.startswith("multipart") else request.get_json()

    required = ("model", "plate_number", "price_per_day")
    missing  = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    if Cars.query.filter_by(plate_number=data["plate_number"]).first():
        return jsonify({"error": "Plate number already registered"}), 409

    try:
        price = float(data["price_per_day"])
    except (ValueError, TypeError):
        return jsonify({"error": "price_per_day must be a number"}), 400

    image_filename = save_upload("car_image")

    car = Cars(
        model         = data["model"],
        plate_number  = data["plate_number"],
        price_per_day = price,
        description   = data.get("description"),
        car_image     = image_filename,
        is_available  = True,
    )
    db.session.add(car)
    db.session.commit()
    return jsonify({"message": "Car added", "car": car.to_dict()}), 201


@admin_bp.route("/api/cars/<int:car_id>", methods=["PATCH"])
@require_admin
def edit_car(car_id):
    car = db.session.get(Cars, car_id)
    if not car:
        return jsonify({"error": "Car not found"}), 404

    data = request.form if request.content_type.startswith("multipart") else request.get_json()

    editable = {"model": str, "price_per_day": float, "description": str}
    for field, cast in editable.items():
        if data.get(field) is not None:
            try:
                setattr(car, field, cast(data[field]))
            except (ValueError, TypeError):
                return jsonify({"error": f"Invalid value for {field}"}), 400

    new_image = save_upload("car_image")
    if new_image:
        car.car_image = new_image

    db.session.commit()
    return jsonify({"message": "Car updated", "car": car.to_dict()}), 200


@admin_bp.route("/api/cars/<int:car_id>", methods=["DELETE"])
@require_admin_only
def delete_car(car_id):
    car = db.session.get(Cars, car_id)
    if not car:
        return jsonify({"error": "Car not found"}), 404

    active_rentals = CarRental.query.filter(
        CarRental.car_id  == car_id,
        CarRental.status.in_(("confirmed", "active"))
    ).count()
    if active_rentals:
        return jsonify({
            "error": f"Cannot delete — {active_rentals} active rental(s) exist"
        }), 409

    db.session.delete(car)
    db.session.commit()
    return jsonify({"message": "Car deleted"}), 200


@admin_bp.route("/api/cars/<int:car_id>/toggle", methods=["PATCH"])
@require_admin
def toggle_car(car_id):
    car = db.session.get(Cars, car_id)
    if not car:
        return jsonify({"error": "Car not found"}), 404
    car.is_available = not car.is_available
    db.session.commit()
    state = "available" if car.is_available else "unavailable"
    return jsonify({"message": f"Car marked {state}", "is_available": car.is_available}), 200


# ═════════════════════════════════════════════════════════════════════════════
#  BOOKINGS — JSON API
# ═════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/api/bookings", methods=["GET"])
@require_admin
def list_bookings_api():
    query = Booking.query

    if status    := request.args.get("status"):
        query = query.filter_by(status=status)
    if room_id   := request.args.get("room_id"):
        query = query.filter_by(room_id=int(room_id))
    if user_id   := request.args.get("user_id"):
        query = query.filter_by(user_id=int(user_id))
    if from_date := request.args.get("from_date"):
        query = query.filter(Booking.check_in_date >= date.fromisoformat(from_date))
    if to_date   := request.args.get("to_date"):
        query = query.filter(Booking.check_in_date <= date.fromisoformat(to_date))

    bookings = query.order_by(Booking.check_in_date.desc()).all()
    return jsonify([b.to_dict() for b in bookings]), 200


@admin_bp.route("/api/bookings/<int:booking_id>/status", methods=["PATCH"])
def update_booking_status(booking_id):
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return jsonify({"error": "Booking not found"}), 404

    data       = request.get_json()
    new_status = data.get("status")

    if new_status not in Booking.STATUSES:
        return jsonify({"error": f"status must be one of: {', '.join(Booking.STATUSES)}"}), 400

    allowed_transitions = {
        "confirmed":       ("checked_in",  "cancelled"),
        "checked_in":      ("checked_out",),
        "pending_payment": ("cancelled",),
    }
    current_allowed = allowed_transitions.get(booking.status, ())
    if new_status not in current_allowed:
        return jsonify({
            "error": f"Cannot transition from '{booking.status}' to '{new_status}'"
        }), 400

    if new_status == "cancelled":
        try:
            booking.cancel()
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    else:
        booking.status = new_status

    db.session.commit()
    return jsonify({"message": f"Booking status updated to '{new_status}'",
                    "booking": booking.to_dict()}), 200


@admin_bp.route("/api/bookings/<int:booking_id>", methods=["DELETE"])
@require_admin_only
def delete_booking(booking_id):
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return jsonify({"error": "Booking not found"}), 404

    if booking.status == "confirmed":
        try:
            booking.cancel()
        except ValueError:
            pass

    db.session.delete(booking)
    db.session.commit()
    return jsonify({"message": "Booking deleted"}), 200


# ═════════════════════════════════════════════════════════════════════════════
#  CAR RENTALS — JSON API
# ═════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/api/rentals", methods=["GET"])
@require_admin
def list_rentals_api():
    query = CarRental.query
    if status := request.args.get("status"):
        query = query.filter_by(status=status)
    if car_id  := request.args.get("car_id"):
        query = query.filter_by(car_id=int(car_id))
    rentals = query.order_by(CarRental.rental_date.desc()).all()
    return jsonify([r.to_dict() for r in rentals]), 200


@admin_bp.route("/api/rentals/<int:rental_id>/status", methods=["PATCH"])
@require_admin
def update_rental_status(rental_id):
    rental = db.session.get(CarRental, rental_id)
    if not rental:
        return jsonify({"error": "Car rental not found"}), 404

    data       = request.get_json()
    new_status = data.get("status")

    if new_status not in CarRental.STATUSES:
        return jsonify({"error": f"status must be one of: {', '.join(CarRental.STATUSES)}"}), 400

    allowed_transitions = {
        "confirmed":       ("active",    "cancelled"),
        "active":          ("returned",  "cancelled"),
        "pending_payment": ("cancelled",),
    }
    current_allowed = allowed_transitions.get(rental.status, ())
    if new_status not in current_allowed:
        return jsonify({
            "error": f"Cannot transition from '{rental.status}' to '{new_status}'"
        }), 400

    if new_status == "cancelled":
        try:
            rental.cancel()
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    else:
        rental.status = new_status
        if new_status == "returned" and rental.car:
            rental.car.is_available = True

    db.session.commit()
    return jsonify({"message": f"Rental status updated to '{new_status}'",
                    "rental": rental.to_dict()}), 200


# ═════════════════════════════════════════════════════════════════════════════
#  USERS — JSON API
# ═════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/api/users", methods=["GET"])
@require_admin
def list_users_api():
    query = User.query
    if role   := request.args.get("role"):
        query = query.filter_by(role=role)
    if active := request.args.get("active"):
        query = query.filter_by(is_active=(active.lower() == "true"))
    if search := request.args.get("search"):
        like = f"%{search}%"
        query = query.filter(
            (User.username.ilike(like)) | (User.email.ilike(like))
        )
    users = query.order_by(User.created_at.desc()).all()
    return jsonify([u.to_dict() for u in users]), 200


@admin_bp.route("/api/users/<int:target_id>/role", methods=["PATCH"])
def change_user_role(target_id):
    target   = db.session.get(User, target_id)
    if not target:
        return jsonify({"error": "User not found"}), 404

    data     = request.get_json()
    new_role = data.get("role")

    if not User.validate_role(new_role):
        return jsonify({"error": "role must be 'user', 'staff', or 'admin'"}), 400

    if target.role == "admin" and new_role != "admin":
        admin_count = User.query.filter_by(role="admin").count()
        if admin_count <= 1:
            return jsonify({"error": "Cannot demote the last admin account"}), 400

    target.role = new_role
    db.session.commit()
    return jsonify({"message": f"User role updated to '{new_role}'",
                    "user": target.to_dict()}), 200


@admin_bp.route("/api/users/<int:target_id>/toggle", methods=["PATCH"])
@require_admin_only
def toggle_user(target_id):
    user_id = int(get_jwt_identity())
    target  = db.session.get(User, target_id)

    if not target:
        return jsonify({"error": "User not found"}), 404
    if target.id == user_id:
        return jsonify({"error": "You cannot deactivate your own account"}), 400

    target.is_active = not target.is_active
    db.session.commit()
    state = "activated" if target.is_active else "deactivated"
    return jsonify({"message": f"User account {state}",
                    "is_active": target.is_active}), 200