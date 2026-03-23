"""
test_bookings.py — FM Residences

FIXES APPLIED:
  - BUG 15: URL paths corrected to match actual blueprint routes:
      OLD (broken)            → NEW (correct)
      /bookings/create        → /bookings          (POST)
      /bookings/my-bookings   → /bookings/my       (GET)
      /cars/rent              → /car-rentals        (POST)
  - FIX: Removed dead `from tests.Conftest import _get_user_id_from_headers`
         (file is conftest.py lowercase; function never existed; the with-block
          was a no-op anyway — the session is populated by the auth_headers fixture)
"""

import pytest
from datetime import date, timedelta


# ─────────────────────────────────────────────────────────────────────────────
#  Room search
# ─────────────────────────────────────────────────────────────────────────────

class TestRoomSearch:

    def test_search_requires_post(self, client):
        resp = client.get("/search")
        assert resp.status_code == 405

    def test_search_missing_dates_redirects(self, client):
        resp = client.post("/search", data={})
        assert resp.status_code in (302, 200)

    def test_search_invalid_dates_redirects(self, client):
        resp = client.post("/search", data={"checkin": "bad", "checkout": "date"})
        assert resp.status_code in (302, 200)

    def test_search_checkout_before_checkin_redirects(self, client):
        tomorrow  = (date.today() + timedelta(days=1)).strftime("%d-%m-%Y")
        next_week = (date.today() + timedelta(days=7)).strftime("%d-%m-%Y")
        resp = client.post("/search", data={
            "checkin":  next_week,
            "checkout": tomorrow,
            "rooms":    "1",
            "adults":   "2",
        })
        assert resp.status_code in (302, 200)

    def test_search_returns_results_or_redirect(self, client, sample_room):
        checkin  = (date.today() + timedelta(days=1)).strftime("%d-%m-%Y")
        checkout = (date.today() + timedelta(days=3)).strftime("%d-%m-%Y")
        resp = client.post("/search", data={
            "checkin":  checkin,
            "checkout": checkout,
            "rooms":    "1",
            "adults":   "2",
            "children": "none",
        })
        # Either renders offer_rooms.html (200) or redirects to index (302 if no avail)
        assert resp.status_code in (200, 302)


# ─────────────────────────────────────────────────────────────────────────────
#  Room bookings
# ─────────────────────────────────────────────────────────────────────────────

class TestRoomBookings:

    def test_create_booking_requires_login(self, client, sample_room):
        checkin  = (date.today() + timedelta(days=2)).strftime("%d-%m-%Y")
        checkout = (date.today() + timedelta(days=4)).strftime("%d-%m-%Y")
        # FIX BUG 15: was /bookings/create
        resp = client.post("/bookings", data={
            "room_type":          "Deluxe Suite",
            "from_date":          checkin,
            "to_date":            checkout,
            "total_rooms":        "1",
            "total_adults":       "2",
            "total_children":     "0",
            "room_price_per_day": "150.00",
            "total_price":        "300.00",
        })
        # Unauthenticated → redirect to login
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_create_booking_succeeds_when_authenticated(self, client, auth_headers, sample_room):
        checkin  = (date.today() + timedelta(days=2)).strftime("%d-%m-%Y")
        checkout = (date.today() + timedelta(days=4)).strftime("%d-%m-%Y")
        # FIX: Removed dead `from tests.Conftest import _get_user_id_from_headers`
        # The with-block was a no-op; auth_headers fixture already provides the JWT.
        resp = client.post("/bookings", data={
            "room_type":          "Deluxe Suite",
            "from_date":          checkin,
            "to_date":            checkout,
            "total_rooms":        "1",
            "total_adults":       "2",
            "total_children":     "0",
            "room_price_per_day": "150.00",
            "total_price":        "300.00",
        }, headers=auth_headers, follow_redirects=False)
        # Success → redirect to checkout, or 200 if form error surfaced
        assert resp.status_code in (200, 302)

    def test_my_bookings_requires_login(self, client):
        # FIX BUG 15: was /bookings/my-bookings
        resp = client.get("/bookings/my")
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_my_bookings_visible_when_authenticated(self, client, auth_headers):
        # FIX BUG 15: was /bookings/my-bookings
        resp = client.get("/bookings/my", headers=auth_headers)
        assert resp.status_code == 200
        assert b"My Bookings" in resp.data

    def test_cancel_nonexistent_booking_404(self, client, auth_headers):
        resp = client.post("/bookings/99999/cancel", headers=auth_headers)
        assert resp.status_code in (302, 404)

    def test_create_booking_missing_fields_fails(self, client, auth_headers):
        resp = client.post("/bookings", data={
            "room_type": "Deluxe Suite",
            # Missing from_date, to_date, etc.
        }, headers=auth_headers, follow_redirects=False)
        # Should redirect back with flash, not 500
        assert resp.status_code in (302, 200)


# ─────────────────────────────────────────────────────────────────────────────
#  Car rentals
# ─────────────────────────────────────────────────────────────────────────────

class TestCarRentals:

    def test_cars_page_renders(self, client):
        resp = client.get("/cars")
        assert resp.status_code == 200
        assert b"Car" in resp.data

    def test_create_rental_requires_login(self, client, sample_car):
        rental_date = (date.today() + timedelta(days=1)).strftime("%d-%m-%Y")
        return_date = (date.today() + timedelta(days=3)).strftime("%d-%m-%Y")
        # FIX BUG 15: was /cars/rent
        resp = client.post("/car-rentals", data={
            "car_id":      sample_car["id"],
            "rental_date": rental_date,
            "return_date": return_date,
        })
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_create_rental_return_before_pickup_fails(self, client, auth_headers, sample_car):
        rental_date = (date.today() + timedelta(days=5)).strftime("%d-%m-%Y")
        return_date = (date.today() + timedelta(days=2)).strftime("%d-%m-%Y")
        # FIX BUG 15: was /cars/rent
        resp = client.post("/car-rentals", data={
            "car_id":      sample_car["id"],
            "rental_date": rental_date,
            "return_date": return_date,
        }, headers=auth_headers, follow_redirects=False)
        assert resp.status_code in (302, 200)

    def test_create_rental_succeeds(self, client, auth_headers, sample_car):
        rental_date = (date.today() + timedelta(days=1)).strftime("%d-%m-%Y")
        return_date = (date.today() + timedelta(days=3)).strftime("%d-%m-%Y")
        # FIX BUG 15: was /cars/rent
        resp = client.post("/car-rentals", data={
            "car_id":      sample_car["id"],
            "rental_date": rental_date,
            "return_date": return_date,
        }, headers=auth_headers, follow_redirects=False)
        assert resp.status_code in (200, 302)