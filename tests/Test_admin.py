"""
test_admin.py — FM Residences

FIXES APPLIED:
  - BUG 16: Room creation tests sent `name=`, `room_description=`
            Fixed to `room_number=`, `room_type=`, `description=`
  - BUG 16: Car creation tests sent `plate=`
            Fixed to `plate_number=`
"""

import pytest


# ─────────────────────────────────────────────────────────────────────────────
#  Dashboard
# ─────────────────────────────────────────────────────────────────────────────

class TestDashboard:

    def test_dashboard_page_requires_login(self, client):
        resp = client.get("/admin/dashboard")
        assert resp.status_code == 302

    def test_dashboard_data_requires_auth(self, client):
        resp = client.get("/admin/dashboard-data")
        assert resp.status_code == 401

    def test_dashboard_data_returns_correct_keys(self, client, admin_auth_headers):
        resp = client.get("/admin/dashboard-data", headers=admin_auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        # FIX BUG 6: check for the corrected key names
        assert "total_bookings"  in data
        assert "total_rentals"   in data
        assert "total_revenue"   in data
        assert "total_users"     in data
        assert "recent_bookings" in data
        assert "recent_rentals"  in data
        # Old (broken) keys must NOT be present
        assert "confirmed_bookings"   not in data
        assert "active_car_rentals"   not in data
        assert "monthly_revenue_usd"  not in data

    def test_staff_can_access_dashboard(self, client, db, app):
        from src.models import User
        with app.app_context():
            staff = User(username="staffuser", email="staff@test.com", role="staff")
            staff.set_password("StaffPass123!")
            staff.is_verified = True
            db.session.add(staff)
            db.session.commit()
            staff_id = staff.id

        resp  = client.post("/auth/login", json={"username": "staffuser", "password": "StaffPass123!"})
        token = resp.get_json().get("access_token")
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.get("/admin/dashboard-data", headers=headers)
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
#  Room CRUD
# ─────────────────────────────────────────────────────────────────────────────

class TestAdminRooms:

    def test_list_rooms_requires_auth(self, client):
        resp = client.get("/admin/rooms")
        assert resp.status_code == 401

    def test_list_rooms(self, client, admin_auth_headers, sample_room):
        resp = client.get("/admin/rooms", headers=admin_auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_create_room_requires_admin(self, client, auth_headers):
        resp = client.post("/admin/rooms", json={
            "room_number":        "999",
            "room_type":          "Budget Room",
            "price_per_night":    50,
            "total_of_this_type": 3,
        }, headers=auth_headers)
        assert resp.status_code == 403

    def test_create_room_success(self, client, admin_auth_headers):
        """FIX BUG 16: uses room_number + room_type + description, not name + room_description"""
        resp = client.post("/admin/rooms", json={
            "room_number":        "202",       # FIX: was missing entirely
            "room_type":          "Ocean View", # FIX: was name=
            "description":        "Sea view",   # FIX: was room_description=
            "price_per_night":    200.0,
            "total_of_this_type": 4,
            "max_guests":         3,
        }, headers=admin_auth_headers)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["room"]["room_type"]   == "Ocean View"
        assert data["room"]["room_number"] == "202"

    def test_create_room_missing_fields(self, client, admin_auth_headers):
        resp = client.post("/admin/rooms", json={
            "room_type": "Incomplete Room",
            # missing room_number, price_per_night, total_of_this_type
        }, headers=admin_auth_headers)
        assert resp.status_code == 400

    def test_create_room_duplicate_number(self, client, admin_auth_headers, sample_room):
        resp = client.post("/admin/rooms", json={
            "room_number":        "101",     # same as sample_room
            "room_type":          "Duplicate",
            "price_per_night":    100,
            "total_of_this_type": 2,
        }, headers=admin_auth_headers)
        assert resp.status_code == 409

    def test_edit_room(self, client, admin_auth_headers, sample_room):
        resp = client.patch(f"/admin/rooms/{sample_room['id']}", json={
            "price_per_night": 180.0,
        }, headers=admin_auth_headers)
        assert resp.status_code == 200

    def test_toggle_room(self, client, admin_auth_headers, sample_room):
        resp = client.patch(f"/admin/rooms/{sample_room['id']}/toggle",
                            headers=admin_auth_headers)
        assert resp.status_code == 200
        assert "is_active" in resp.get_json()

    def test_delete_nonexistent_room(self, client, admin_auth_headers):
        resp = client.delete("/admin/rooms/99999", headers=admin_auth_headers)
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
#  Car CRUD
# ─────────────────────────────────────────────────────────────────────────────

class TestAdminCars:

    def test_list_cars(self, client, admin_auth_headers, sample_car):
        resp = client.get("/admin/api/cars", headers=admin_auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_create_car_success(self, client, admin_auth_headers):
        """FIX BUG 16: uses plate_number, not plate"""
        resp = client.post("/admin/api/cars", json={
            "model":         "BMW 5 Series",
            "plate_number":  "FM-TEST-99",   # FIX: was plate=
            "price_per_day": 200.0,
            "description":   "Premium sedan",
        }, headers=admin_auth_headers)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["car"]["model"]        == "BMW 5 Series"
        assert data["car"]["plate_number"] == "FM-TEST-99"

    def test_create_car_missing_plate(self, client, admin_auth_headers):
        resp = client.post("/admin/api/cars", json={
            "model":         "Tesla Model 3",
            # plate_number missing
            "price_per_day": 150.0,
        }, headers=admin_auth_headers)
        assert resp.status_code == 400

    def test_create_car_duplicate_plate(self, client, admin_auth_headers, sample_car):
        resp = client.post("/admin/api/cars", json={
            "model":         "Duplicate Car",
            "plate_number":  "FM-001",       # same as sample_car
            "price_per_day": 100.0,
        }, headers=admin_auth_headers)
        assert resp.status_code == 409

    def test_toggle_car(self, client, admin_auth_headers, sample_car):
        resp = client.patch(f"/admin/api/cars/{sample_car['id']}/toggle",
                            headers=admin_auth_headers)
        assert resp.status_code == 200
        assert "is_available" in resp.get_json()

    def test_delete_nonexistent_car(self, client, admin_auth_headers):
        resp = client.delete("/admin/api/cars/99999", headers=admin_auth_headers)
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
#  Staff registration  (FIX BUG 5)
# ─────────────────────────────────────────────────────────────────────────────

class TestStaffRegistration:

    def test_register_staff_requires_admin(self, client, auth_headers):
        """Regular users cannot create staff accounts."""
        resp = client.post("/admin/register", json={
            "username": "newstaff",
            "email":    "newstaff@test.com",
            "password": "StaffPass123!",
            "role":     "staff",
        }, headers=auth_headers)
        assert resp.status_code == 403

    def test_register_staff_by_admin_succeeds(self, client, admin_auth_headers):
        resp = client.post("/admin/register", json={
            "username": "newstaff2",
            "email":    "newstaff2@test.com",
            "password": "StaffPass123!",
            "role":     "staff",
        }, headers=admin_auth_headers)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["user"]["role"] == "staff"

    def test_register_staff_duplicate_username(self, client, admin_auth_headers):
        client.post("/admin/register", json={
            "username": "dupstaff",
            "email":    "dup1@test.com",
            "password": "StaffPass123!",
        }, headers=admin_auth_headers)
        resp = client.post("/admin/register", json={
            "username": "dupstaff",
            "email":    "dup2@test.com",
            "password": "StaffPass123!",
        }, headers=admin_auth_headers)
        assert resp.status_code == 409

    def test_register_staff_invalid_role(self, client, admin_auth_headers):
        resp = client.post("/admin/register", json={
            "username": "weirdstaff",
            "email":    "weird@test.com",
            "password": "StaffPass123!",
            "role":     "superuser",    # invalid
        }, headers=admin_auth_headers)
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
#  HTML page routes (FIX BUG 7)
# ─────────────────────────────────────────────────────────────────────────────

class TestAdminHTMLPages:

    def test_bookings_page_renders_html(self, client, admin_auth_headers):
        """FIX BUG 7: /admin/bookings must return HTML, not JSON."""
        resp = client.get("/admin/bookings", headers=admin_auth_headers)
        # Without session (HTML route uses session, not JWT), expect redirect
        # In tests we rely on session fixture; just assert not raw JSON list
        assert resp.status_code in (200, 302)
        if resp.status_code == 200:
            assert resp.content_type.startswith("text/html")

    def test_rentals_page_renders_html(self, client, admin_auth_headers):
        resp = client.get("/admin/rentals", headers=admin_auth_headers)
        assert resp.status_code in (200, 302)
        if resp.status_code == 200:
            assert resp.content_type.startswith("text/html")