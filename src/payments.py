"""
payments.py — FM Residences
Stripe payment integration.

FIXES APPLIED:
  - BUG 10: When a PaymentIntent already exists, the old code returned
            stripe_payment_intent_id ("pi_xxx") as the client_secret.
            That is wrong — the client_secret is "pi_xxx_secret_yyy".
            Fix: re-retrieve the intent from Stripe to get the current
            client_secret.
  - BUG (checkout): create_booking_intent and create_rental_intent used
            @jwt_required() strictly, so an expired or missing token
            returned {"msg": "..."} (not {"error": "..."}) causing the
            checkout JS to display "Could not initialise payment." instead
            of a real error.  Fixed by using the same hybrid
            session + JWT auth that bookings.py already uses.
"""

import stripe

from flask import Blueprint, request, jsonify, current_app, session
from flask_jwt_extended import (
    jwt_required, get_jwt_identity,
    verify_jwt_in_request,
)

from src.models import db, Booking, CarRental, Payment, User

payments_bp = Blueprint("payments", __name__, url_prefix="/payments")


def get_stripe():
    """Lazy-init Stripe with the secret key from config."""
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
    return stripe


def to_cents(amount: float) -> int:
    """Convert a dollar amount to integer cents for Stripe."""
    return int(round(amount * 100))


def _get_current_user_id():
    """
    Return user_id from JWT header OR Flask session — whichever is present.
    Mirrors the same helper in bookings.py so checkout works even when the
    JWT has expired but the session cookie is still valid.
    """
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity:
            return int(identity)
    except Exception:
        pass
    return session.get("user_id")


# ─────────────────────────────────────────────────────────────────────────────
#  CREATE PAYMENT INTENT — room booking
# ─────────────────────────────────────────────────────────────────────────────

@payments_bp.route("/create-intent/booking/<int:booking_id>", methods=["POST"])
def create_booking_intent(booking_id):
    """
    Create a Stripe PaymentIntent for a room booking.
    FIX: uses hybrid auth (JWT header OR session cookie) so the checkout
    page doesn't silently fail after the 30-minute JWT window.
    """
    user_id = _get_current_user_id()
    if not user_id:
        return jsonify({"error": "Login required"}), 401

    booking = db.session.get(Booking, booking_id)

    if not booking:
        return jsonify({"error": "Booking not found"}), 404
    if booking.user_id != user_id:
        return jsonify({"error": "Unauthorised"}), 403
    if booking.status != "pending_payment":
        return jsonify({"error": f"Booking is already '{booking.status}' — cannot re-pay"}), 400

    stripe_client = get_stripe()

    # FIX BUG 10: Re-retrieve the PaymentIntent from Stripe to get the
    # current client_secret rather than returning the intent ID.
    if booking.payment:
        existing = booking.payment
        try:
            intent = stripe_client.PaymentIntent.retrieve(
                existing.stripe_payment_intent_id
            )
            client_secret = intent.client_secret
        except stripe.error.StripeError as e:
            return jsonify({"error": str(e.user_message)}), 502

        return jsonify({
            "client_secret":   client_secret,
            "publishable_key": current_app.config["STRIPE_PUBLISHABLE_KEY"],
            "amount":          existing.amount,
            "currency":        existing.currency,
            "payment_id":      existing.id,
        }), 200

    user = db.session.get(User, user_id)

    try:
        intent = stripe_client.PaymentIntent.create(
            amount      = to_cents(booking.total_price),
            currency    = "usd",
            metadata    = {
                "booking_id": booking.id,
                "user_id":    user_id,
                "type":       "room_booking",
            },
            description   = (
                f"FM Residences — Room {booking.room_id} "
                f"{booking.check_in_date} to {booking.check_out_date}"
            ),
            receipt_email = user.email if user else None,
        )
    except stripe.error.StripeError as e:
        return jsonify({"error": str(e.user_message)}), 502

    payment = Payment(
        booking_id               = booking.id,
        stripe_payment_intent_id = intent.id,
        amount                   = booking.total_price,
        currency                 = "usd",
        status                   = "pending",
    )
    db.session.add(payment)
    db.session.commit()

    return jsonify({
        "client_secret":   intent.client_secret,
        "publishable_key": current_app.config["STRIPE_PUBLISHABLE_KEY"],
        "amount":          booking.total_price,
        "currency":        "usd",
        "payment_id":      payment.id,
    }), 201


# ─────────────────────────────────────────────────────────────────────────────
#  CREATE PAYMENT INTENT — car rental
# ─────────────────────────────────────────────────────────────────────────────

@payments_bp.route("/create-intent/car-rental/<int:rental_id>", methods=["POST"])
def create_rental_intent(rental_id):
    """
    Create a Stripe PaymentIntent for a car rental.
    FIX: same hybrid auth fix as create_booking_intent.
    """
    user_id = _get_current_user_id()
    if not user_id:
        return jsonify({"error": "Login required"}), 401

    rental = db.session.get(CarRental, rental_id)

    if not rental:
        return jsonify({"error": "Car rental not found"}), 404
    if rental.user_id != user_id:
        return jsonify({"error": "Unauthorised"}), 403
    if rental.status != "pending_payment":
        return jsonify({"error": f"Rental is already '{rental.status}' — cannot re-pay"}), 400

    stripe_client = get_stripe()

    # FIX BUG 10: Re-retrieve from Stripe on duplicate, same as booking intent
    if rental.payment:
        existing = rental.payment
        try:
            intent = stripe_client.PaymentIntent.retrieve(
                existing.stripe_payment_intent_id
            )
            client_secret = intent.client_secret
        except stripe.error.StripeError as e:
            return jsonify({"error": str(e.user_message)}), 502

        return jsonify({
            "client_secret":   client_secret,
            "publishable_key": current_app.config["STRIPE_PUBLISHABLE_KEY"],
            "amount":          existing.amount,
            "currency":        existing.currency,
            "payment_id":      existing.id,
        }), 200

    user = db.session.get(User, user_id)

    try:
        intent = stripe_client.PaymentIntent.create(
            amount      = to_cents(rental.total_price),
            currency    = "usd",
            metadata    = {
                "car_rental_id": rental.id,
                "user_id":       user_id,
                "type":          "car_rental",
            },
            description   = (
                f"FM Residences — Car {rental.car_id} "
                f"{rental.rental_date} to {rental.return_date}"
            ),
            receipt_email = user.email if user else None,
        )
    except stripe.error.StripeError as e:
        return jsonify({"error": str(e.user_message)}), 502

    payment = Payment(
        car_rental_id            = rental.id,
        stripe_payment_intent_id = intent.id,
        amount                   = rental.total_price,
        currency                 = "usd",
        status                   = "pending",
    )
    db.session.add(payment)
    db.session.commit()

    return jsonify({
        "client_secret":   intent.client_secret,
        "publishable_key": current_app.config["STRIPE_PUBLISHABLE_KEY"],
        "amount":          rental.total_price,
        "currency":        "usd",
        "payment_id":      payment.id,
    }), 201


@payments_bp.route("/confirm-payment", methods=["POST"])
def confirm_payment():
    """
    Called by checkout.html immediately after stripe.confirmCardPayment()
    returns status='succeeded'.

    Verifies the PaymentIntent status directly with Stripe, then marks
    the Payment + Booking/CarRental as confirmed in the DB.

    Body (JSON): { "payment_intent_id": "pi_xxx" }
    """
    user_id = _get_current_user_id()
    if not user_id:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json() or {}
    pi_id = data.get("payment_intent_id")
    if not pi_id:
        return jsonify({"error": "payment_intent_id is required"}), 400

    stripe_client = get_stripe()

    # Verify directly with Stripe — never trust client-only claims
    try:
        intent = stripe_client.PaymentIntent.retrieve(pi_id)
    except stripe.error.StripeError as e:
        return jsonify({"error": str(e.user_message)}), 502

    if intent.status != "succeeded":
        return jsonify({"error": f"Payment not yet succeeded (status: {intent.status})"}), 400

    # Find the Payment record by Stripe intent ID
    payment = Payment.query.filter_by(stripe_payment_intent_id=pi_id).first()
    if not payment:
        return jsonify({"error": "Payment record not found"}), 404

    # Security: ensure this payment belongs to the requesting user
    owner_id = None
    if payment.booking and payment.booking.user_id:
        owner_id = payment.booking.user_id
    elif payment.car_rental and payment.car_rental.user_id:
        owner_id = payment.car_rental.user_id

    if owner_id != user_id:
        return jsonify({"error": "Unauthorised"}), 403

    # Idempotent — if already confirmed, just return success
    if payment.status == "succeeded":
        return jsonify({"message": "Already confirmed"}), 200

    # Mark payment succeeded
    payment.mark_succeeded()

    # Confirm the booking
    if payment.booking_id:
        booking = db.session.get(Booking, payment.booking_id)
        if booking and booking.status == "pending_payment":
            booking.status = "confirmed"

    # Confirm the rental
    if payment.car_rental_id:
        rental = db.session.get(CarRental, payment.car_rental_id)
        if rental and rental.status == "pending_payment":
            rental.status = "confirmed"
            if rental.car:
                rental.car.is_available = False

    db.session.commit()
    return jsonify({"message": "Payment confirmed"}), 200


# ─────────────────────────────────────────────────────────────────────────────
#  STRIPE WEBHOOK
# ─────────────────────────────────────────────────────────────────────────────

@payments_bp.route("/webhook", methods=["POST"])
def stripe_webhook():
    """
    Stripe sends events here after payment succeeds, fails, etc.
    CSRF is exempted for this blueprint in __init__.py.
    """
    get_stripe()  # sets stripe.api_key

    payload        = request.get_data()
    sig_header     = request.headers.get("Stripe-Signature")
    webhook_secret = current_app.config.get("STRIPE_WEBHOOK_SECRET", "")

    if not webhook_secret:
        return jsonify({"error": "Webhook secret not configured"}), 500

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        return jsonify({"error": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Invalid signature"}), 400

    event_type  = event["type"]
    data_object = event["data"]["object"]

    if event_type == "payment_intent.succeeded":
        _handle_payment_succeeded(data_object)
    elif event_type == "payment_intent.payment_failed":
        _handle_payment_failed(data_object)
    elif event_type == "charge.refunded":
        _handle_charge_refunded(data_object)

    return jsonify({"status": "ok"}), 200


def _handle_payment_succeeded(intent):
    payment = Payment.query.filter_by(
        stripe_payment_intent_id=intent["id"]
    ).first()
    if not payment:
        return

    payment.mark_succeeded()

    if payment.booking_id:
        booking = db.session.get(Booking, payment.booking_id)
        if booking and booking.status == "pending_payment":
            booking.status = "confirmed"

    if payment.car_rental_id:
        rental = db.session.get(CarRental, payment.car_rental_id)
        if rental and rental.status == "pending_payment":
            rental.status = "confirmed"
            if rental.car:
                rental.car.is_available = False

    db.session.commit()


def _handle_payment_failed(intent):
    payment = Payment.query.filter_by(
        stripe_payment_intent_id=intent["id"]
    ).first()
    if not payment:
        return
    payment.mark_failed()
    db.session.commit()


def _handle_charge_refunded(charge):
    payment_intent_id = charge.get("payment_intent")
    if not payment_intent_id:
        return

    payment = Payment.query.filter_by(
        stripe_payment_intent_id=payment_intent_id
    ).first()
    if not payment:
        return

    payment.mark_refunded()

    if payment.booking_id:
        booking = db.session.get(Booking, payment.booking_id)
        if booking:
            try:
                booking.cancel()
            except ValueError:
                pass

    if payment.car_rental_id:
        rental = db.session.get(CarRental, payment.car_rental_id)
        if rental:
            try:
                rental.cancel()
            except ValueError:
                pass

    db.session.commit()


# ─────────────────────────────────────────────────────────────────────────────
#  REFUND  (admin-initiated)
# ─────────────────────────────────────────────────────────────────────────────

@payments_bp.route("/refund/<int:payment_id>", methods=["POST"])
@jwt_required()
def refund_payment(payment_id):
    """Issue a full refund via Stripe. Admin/staff only."""
    user_id = int(get_jwt_identity())
    user    = db.session.get(User, user_id)

    if not user or user.role not in ("admin", "staff"):
        return jsonify({"error": "Admin access required"}), 403

    payment = db.session.get(Payment, payment_id)
    if not payment:
        return jsonify({"error": "Payment not found"}), 404
    if payment.status != "succeeded":
        return jsonify({"error": f"Cannot refund a payment with status '{payment.status}'"}), 400

    stripe_client = get_stripe()
    try:
        stripe_client.Refund.create(payment_intent=payment.stripe_payment_intent_id)
    except stripe.error.StripeError as e:
        return jsonify({"error": str(e.user_message)}), 502

    return jsonify({"message": "Refund initiated — status will update via webhook"}), 200


# ─────────────────────────────────────────────────────────────────────────────
#  GET PAYMENT STATUS
# ─────────────────────────────────────────────────────────────────────────────

@payments_bp.route("/status/<int:payment_id>", methods=["GET"])
@jwt_required()
def payment_status(payment_id):
    """Returns the current status of a payment."""
    user_id = int(get_jwt_identity())
    payment = db.session.get(Payment, payment_id)

    if not payment:
        return jsonify({"error": "Payment not found"}), 404

    user     = db.session.get(User, user_id)
    is_owner = (
        (payment.booking_id    and payment.booking    and payment.booking.user_id    == user_id) or
        (payment.car_rental_id and payment.car_rental and payment.car_rental.user_id == user_id)
    )
    if not is_owner and user.role not in ("admin", "staff"):
        return jsonify({"error": "Unauthorised"}), 403

    return jsonify(payment.to_dict()), 200