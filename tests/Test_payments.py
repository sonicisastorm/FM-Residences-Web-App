"""
test_payments.py — FM Residences

FIXES APPLIED:
  - BUG 17: Tests called POST /payments/create-intent with booking_id in JSON body.
            Actual route: POST /payments/create-intent/booking/<id>  (URL parameter)
            Fixed: booking_id now goes in the URL, not the request body.
  - BUG 17: Same for car rental intent: was /payments/create-intent with rental_id
            Fixed: POST /payments/create-intent/car-rental/<id>
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers: create seeded booking / rental in DB
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def pending_booking(db, app, regular_user, sample_room):
    from src.models import Booking
    from datetime import date, timedelta
    with app.app_context():
        b = Booking(
            user_id         = regular_user["id"],
            room_id         = sample_room["id"],
            check_in_date   = date.today() + timedelta(days=5),
            check_out_date  = date.today() + timedelta(days=7),
            num_rooms       = 1,
            num_guests      = 2,
            num_adults      = 2,
            num_children    = 0,
            price_per_night = 150.0,
            total_price     = 300.0,
            status          = "pending_payment",
        )
        db.session.add(b)
        db.session.commit()
        return {"id": b.id, "total_price": b.total_price}


@pytest.fixture
def pending_rental(db, app, regular_user, sample_car):
    from src.models import CarRental
    from datetime import date, timedelta
    with app.app_context():
        r = CarRental(
            user_id       = regular_user["id"],
            car_id        = sample_car["id"],
            rental_date   = date.today() + timedelta(days=3),
            return_date   = date.today() + timedelta(days=5),
            price_per_day = 150.0,
            total_price   = 300.0,
            status        = "pending_payment",
        )
        db.session.add(r)
        db.session.commit()
        return {"id": r.id, "total_price": r.total_price}


# ─────────────────────────────────────────────────────────────────────────────
#  Booking payment intent
# ─────────────────────────────────────────────────────────────────────────────

class TestBookingPaymentIntent:

    def test_create_intent_requires_auth(self, client, pending_booking):
        # FIX BUG 17: booking_id in URL, not body
        resp = client.post(f"/payments/create-intent/booking/{pending_booking['id']}")
        assert resp.status_code == 401

    def test_create_intent_wrong_user(self, client, db, app, pending_booking):
        """A different user cannot pay for someone else's booking."""
        from src.models import User
        with app.app_context():
            other = User(username="other", email="other@test.com", role="user")
            other.set_password("OtherPass123!")
            other.is_verified = True
            db.session.add(other)
            db.session.commit()

        resp  = client.post("/auth/login", json={"username": "other", "password": "OtherPass123!"})
        token = resp.get_json().get("access_token")
        headers = {"Authorization": f"Bearer {token}"}

        # FIX BUG 17: booking_id in URL
        resp = client.post(
            f"/payments/create-intent/booking/{pending_booking['id']}",
            headers=headers
        )
        assert resp.status_code == 403

    @patch("src.payments.get_stripe")
    def test_create_intent_returns_client_secret(self, mock_get_stripe,
                                                  client, auth_headers, pending_booking, app):
        """
        FIX BUG 10: The response must include a real client_secret (pi_xxx_secret_yyy),
        not just the intent ID (pi_xxx). Here we mock Stripe to return a recognisable
        client_secret and assert the response exposes it.
        """
        mock_intent = MagicMock()
        mock_intent.id            = "pi_test123"
        mock_intent.client_secret = "pi_test123_secret_abc"   # FIX: must be the secret, not the ID

        mock_stripe = MagicMock()
        mock_stripe.PaymentIntent.create.return_value = mock_intent
        mock_get_stripe.return_value = mock_stripe

        with app.app_context():
            app.config["STRIPE_SECRET_KEY"]     = "sk_test_fake"
            app.config["STRIPE_PUBLISHABLE_KEY"] = "pk_test_fake"

        # FIX BUG 17: booking_id in URL, not body
        resp = client.post(
            f"/payments/create-intent/booking/{pending_booking['id']}",
            headers=auth_headers
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert "client_secret"   in data
        assert "publishable_key" in data
        assert "payment_id"      in data
        # The client_secret must be the full secret, not just the intent ID
        assert data["client_secret"] == "pi_test123_secret_abc"
        assert data["client_secret"] != "pi_test123"   # NOT the bare intent ID

    def test_create_intent_nonexistent_booking(self, client, auth_headers):
        # FIX BUG 17: booking_id in URL
        resp = client.post("/payments/create-intent/booking/99999",
                           headers=auth_headers)
        assert resp.status_code == 404

    @patch("src.payments.get_stripe")
    def test_duplicate_intent_retrieves_from_stripe(self, mock_get_stripe,
                                                     client, auth_headers, pending_booking,
                                                     db, app):
        """
        FIX BUG 10: On a second call (payment record already exists), the route
        must re-retrieve the intent from Stripe and return its client_secret,
        not return the stored intent ID as-is.
        """
        from src.models import Payment

        mock_intent = MagicMock()
        mock_intent.id            = "pi_existing"
        mock_intent.client_secret = "pi_existing_secret_xyz"

        mock_stripe = MagicMock()
        mock_stripe.PaymentIntent.create.return_value   = mock_intent
        mock_stripe.PaymentIntent.retrieve.return_value = mock_intent
        mock_get_stripe.return_value = mock_stripe

        with app.app_context():
            app.config["STRIPE_SECRET_KEY"]      = "sk_test_fake"
            app.config["STRIPE_PUBLISHABLE_KEY"]  = "pk_test_fake"

            # Pre-create payment record to simulate duplicate call
            payment = Payment(
                booking_id               = pending_booking["id"],
                stripe_payment_intent_id = "pi_existing",
                amount                   = 300.0,
                currency                 = "usd",
                status                   = "pending",
            )
            db.session.add(payment)
            db.session.commit()

        # FIX BUG 17: booking_id in URL
        resp = client.post(
            f"/payments/create-intent/booking/{pending_booking['id']}",
            headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.get_json()
        # Must have retrieved the client_secret from Stripe, not returned "pi_existing"
        assert data["client_secret"] == "pi_existing_secret_xyz"
        assert mock_stripe.PaymentIntent.retrieve.called


# ─────────────────────────────────────────────────────────────────────────────
#  Car rental payment intent
# ─────────────────────────────────────────────────────────────────────────────

class TestCarRentalPaymentIntent:

    def test_create_rental_intent_requires_auth(self, client, pending_rental):
        # FIX BUG 17: rental_id in URL
        resp = client.post(f"/payments/create-intent/car-rental/{pending_rental['id']}")
        assert resp.status_code == 401

    @patch("src.payments.get_stripe")
    def test_create_rental_intent_returns_client_secret(self, mock_get_stripe,
                                                         client, auth_headers,
                                                         pending_rental, app):
        mock_intent = MagicMock()
        mock_intent.id            = "pi_car_test"
        mock_intent.client_secret = "pi_car_test_secret_def"

        mock_stripe = MagicMock()
        mock_stripe.PaymentIntent.create.return_value = mock_intent
        mock_get_stripe.return_value = mock_stripe

        with app.app_context():
            app.config["STRIPE_SECRET_KEY"]      = "sk_test_fake"
            app.config["STRIPE_PUBLISHABLE_KEY"]  = "pk_test_fake"

        # FIX BUG 17: rental_id in URL, not body
        resp = client.post(
            f"/payments/create-intent/car-rental/{pending_rental['id']}",
            headers=auth_headers
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["client_secret"] == "pi_car_test_secret_def"


# ─────────────────────────────────────────────────────────────────────────────
#  Webhook
# ─────────────────────────────────────────────────────────────────────────────

class TestWebhook:

    def test_webhook_rejects_bad_signature(self, client, app):
        with app.app_context():
            app.config["STRIPE_WEBHOOK_SECRET"] = "whsec_test"

        resp = client.post(
            "/payments/webhook",
            data=b'{"type":"payment_intent.succeeded"}',
            content_type="application/json",
            headers={"Stripe-Signature": "bad_sig"},
        )
        assert resp.status_code == 400

    def test_webhook_missing_secret_config(self, client, app):
        with app.app_context():
            app.config["STRIPE_WEBHOOK_SECRET"] = ""

        resp = client.post(
            "/payments/webhook",
            data=b'{}',
            content_type="application/json",
        )
        assert resp.status_code == 500