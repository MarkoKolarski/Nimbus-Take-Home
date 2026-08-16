import inspect

import jwt
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import ACCESS_TOKEN_COOKIE_NAME
from app.main import app
from app.seed import DEMO_PASSWORD


def test_login_success_sets_httponly_cookie():
    client = TestClient(app)
    resp = client.post("/auth/login", json={"email": "alice@nimbus.dev", "password": DEMO_PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["email"] == "alice@nimbus.dev"
    set_cookie = resp.headers.get("set-cookie", "")
    assert ACCESS_TOKEN_COOKIE_NAME in set_cookie
    assert "httponly" in set_cookie.lower()


def test_login_wrong_password_rejected():
    client = TestClient(app)
    resp = client.post("/auth/login", json={"email": "alice@nimbus.dev", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_email_rejected_same_as_wrong_password():
    client = TestClient(app)
    resp_unknown = client.post("/auth/login", json={"email": "nobody@nimbus.dev", "password": DEMO_PASSWORD})
    resp_wrong = client.post("/auth/login", json={"email": "alice@nimbus.dev", "password": "wrong"})
    assert resp_unknown.status_code == resp_wrong.status_code == 401
    assert resp_unknown.json() == resp_wrong.json()


def test_me_requires_auth():
    client = TestClient(app)
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_returns_correct_distinct_identity_per_user():
    alice = TestClient(app)
    alice.post("/auth/login", json={"email": "alice@nimbus.dev", "password": DEMO_PASSWORD})
    bob = TestClient(app)
    bob.post("/auth/login", json={"email": "bob@nimbus.dev", "password": DEMO_PASSWORD})

    alice_me = alice.get("/auth/me").json()
    bob_me = bob.get("/auth/me").json()

    assert alice_me["email"] == "alice@nimbus.dev"
    assert bob_me["email"] == "bob@nimbus.dev"
    assert alice_me["id"] != bob_me["id"]


def test_forged_token_rejected():
    client = TestClient(app)
    client.post("/auth/login", json={"email": "alice@nimbus.dev", "password": DEMO_PASSWORD})
    real_token = client.cookies.get(ACCESS_TOKEN_COOKIE_NAME)
    payload = jwt.decode(real_token, options={"verify_signature": False})

    forged = jwt.encode(payload, "not-the-real-secret", algorithm=settings.jwt_algorithm)
    client.cookies.set(ACCESS_TOKEN_COOKIE_NAME, forged)

    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_logout_clears_cookie():
    client = TestClient(app)
    client.post("/auth/login", json={"email": "bob@nimbus.dev", "password": DEMO_PASSWORD})
    assert client.get("/auth/me").status_code == 200

    client.post("/auth/logout")
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_no_route_accepts_user_id_as_path_query_or_body_param():
    """CLAUDE.md invariant: get_current_user is the only source of identity."""
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        for name, param in inspect.signature(endpoint).parameters.items():
            assert name != "user_id", f"{route.path} accepts user_id directly"
            annotation = param.annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                assert "user_id" not in annotation.model_fields, f"{route.path} body model accepts user_id"
