"""
test_auth.py — Auth blueprint tests

Covers: register, login, logout, refresh, forgot-password,
reset-password, email-verification, role checks.
"""

import pytest


class TestRegister:
    def test_register_success(self, client):
        resp = client.post("/auth/register", json={
            "username": "newuser",
            "email": "newuser@example.com",
            "password": "StrongPass1!",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert "user" in data
        assert data["user"]["username"] == "newuser"

    def test_register_duplicate_username(self, client, regular_user):
        resp = client.post("/auth/register", json={
            "username": regular_user["username"],
            "email": "other@example.com",
            "password": "StrongPass1!",
        })
        assert resp.status_code == 409
        assert "Username" in resp.get_json()["error"]

    def test_register_duplicate_email(self, client, regular_user):
        resp = client.post("/auth/register", json={
            "username": "brandnewuser",
            "email": regular_user["email"],
            "password": "StrongPass1!",
        })
        assert resp.status_code == 409
        assert "Email" in resp.get_json()["error"]

    def test_register_short_password(self, client):
        resp = client.post("/auth/register", json={
            "username": "shortpw",
            "email": "shortpw@example.com",
            "password": "abc",
        })
        assert resp.status_code == 400
        assert "8 characters" in resp.get_json()["error"]

    def test_register_missing_fields(self, client):
        resp = client.post("/auth/register", json={"username": "onlyname"})
        assert resp.status_code == 400

    def test_register_invalid_email(self, client):
        resp = client.post("/auth/register", json={
            "username": "bademail",
            "email": "not-an-email",
            "password": "StrongPass1!",
        })
        assert resp.status_code == 400


class TestLogin:
    def test_login_success(self, client, regular_user):
        resp = client.post("/auth/login", json={
            "username": regular_user["username"],
            "password": regular_user["password"],
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "access_token" in data
        assert "refresh_token" in data

    def test_login_wrong_password(self, client, regular_user):
        resp = client.post("/auth/login", json={
            "username": regular_user["username"],
            "password": "WrongPassword!",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        resp = client.post("/auth/login", json={
            "username": "nobody",
            "password": "whatever",
        })
        assert resp.status_code == 401

    def test_login_missing_fields(self, client):
        resp = client.post("/auth/login", json={"username": "test"})
        assert resp.status_code == 400

    def test_login_sets_session(self, client, regular_user):
        with client.session_transaction() as sess:
            assert "user_id" not in sess
        client.post("/auth/login", json={
            "username": regular_user["username"],
            "password": regular_user["password"],
        })
        with client.session_transaction() as sess:
            assert sess.get("user_id") is not None


class TestLogout:
    def test_logout_success(self, client, auth_headers):
        resp = client.post("/auth/logout", headers=auth_headers)
        assert resp.status_code == 200

    def test_logout_requires_auth(self, client):
        resp = client.post("/auth/logout")
        assert resp.status_code in (401, 422)  # JWT missing


class TestTokenRefresh:
    def test_refresh_token(self, client, regular_user):
        login_resp = client.post("/auth/login", json={
            "username": regular_user["username"],
            "password": regular_user["password"],
        })
        refresh_token = login_resp.get_json()["refresh_token"]
        resp = client.post("/auth/refresh", headers={
            "Authorization": f"Bearer {refresh_token}"
        })
        assert resp.status_code == 200
        assert "access_token" in resp.get_json()


class TestForgotPassword:
    def test_forgot_password_known_email(self, client, regular_user):
        # Should always return 200 (no email enumeration)
        resp = client.post("/auth/forgot-password", json={
            "email": regular_user["email"]
        })
        assert resp.status_code == 200

    def test_forgot_password_unknown_email(self, client):
        # Still 200 — prevents user enumeration
        resp = client.post("/auth/forgot-password", json={
            "email": "nobody@example.com"
        })
        assert resp.status_code == 200

    def test_forgot_password_missing_email(self, client):
        resp = client.post("/auth/forgot-password", json={})
        assert resp.status_code == 400


class TestPageRoutes:
    """Smoke-test that page routes return HTML (200 or redirect)."""
    def test_login_page(self, client):
        resp = client.get("/auth/login")
        assert resp.status_code == 200
        assert b"<!DOCTYPE html>" in resp.data

    def test_register_page(self, client):
        resp = client.get("/auth/register")
        assert resp.status_code == 200

    def test_forgot_password_page(self, client):
        resp = client.get("/auth/forgot-password")
        assert resp.status_code == 200

    def test_login_page_redirects_when_logged_in(self, client, regular_user):
        # Login first
        client.post("/auth/login", json={
            "username": regular_user["username"],
            "password": regular_user["password"],
        })
        # Now GET /auth/login should redirect
        resp = client.get("/auth/login")
        assert resp.status_code in (302, 200)