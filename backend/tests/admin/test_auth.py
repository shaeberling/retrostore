from datetime import UTC, datetime, timedelta

import pytest

import retrostore.admin.auth as authentication

NOW = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)


class FakeRoleResolver:
    def __init__(self, assignment):
        self.assignment = assignment
        self.uids = []

    def role_for(self, uid):
        self.uids.append(uid)
        return self.assignment


def _claims(**overrides):
    claims = {
        "sub": "firebase-user",
        "email": "admin@example.test",
        "email_verified": True,
        "role": "administrator",
        "auth_time": NOW.timestamp(),
    }
    claims.update(overrides)
    return claims


def test_firebase_exchange_requires_recent_verified_authorized_identity(monkeypatch) -> None:
    observed = {}
    monkeypatch.setattr(authentication.auth, "verify_id_token", lambda *args, **kwargs: _claims())

    def create_cookie(*args, **kwargs):
        observed.update(kwargs)
        return "session-cookie"

    monkeypatch.setattr(authentication.auth, "create_session_cookie", create_cookie)
    authenticator = authentication.FirebaseAdminAuthenticator("trs-80", app=object())

    session = authenticator.exchange_id_token("id-token", now=NOW)

    assert session.value == "session-cookie"
    assert session.identity.uid == "firebase-user"
    assert session.identity.is_administrator is True
    assert observed["expires_in"] == timedelta(days=5)


@pytest.mark.parametrize(
    ("claims", "error"),
    (
        (_claims(auth_time=(NOW - timedelta(minutes=6)).timestamp()), "recent"),
        (_claims(email_verified=False), "verified email"),
        (_claims(role=None), "administration role"),
    ),
)
def test_firebase_exchange_rejects_stale_or_unauthorized_claims(monkeypatch, claims, error) -> None:
    monkeypatch.setattr(authentication.auth, "verify_id_token", lambda *args, **kwargs: claims)
    monkeypatch.setattr(authentication.auth, "create_session_cookie", pytest.fail)
    authenticator = authentication.FirebaseAdminAuthenticator("trs-80", app=object())

    with pytest.raises(
        (authentication.AuthenticationError, authentication.AuthorizationError), match=error
    ):
        authenticator.exchange_id_token("id-token", now=NOW)


def test_firebase_session_verification_checks_revocation_and_supports_admin_claim(
    monkeypatch,
) -> None:
    observed = {}

    def verify(cookie, **kwargs):
        observed.update(kwargs)
        assert cookie == "session-cookie"
        return _claims(role=None, admin=True)

    monkeypatch.setattr(authentication.auth, "verify_session_cookie", verify)
    authenticator = authentication.FirebaseAdminAuthenticator("trs-80", app=object())

    identity = authenticator.verify_session_cookie("session-cookie")

    assert identity.role == "administrator"
    assert observed["check_revoked"] is True


def test_stored_role_overrides_firebase_claim_on_every_session_check(monkeypatch) -> None:
    monkeypatch.setattr(
        authentication.auth,
        "verify_session_cookie",
        lambda *args, **kwargs: _claims(role="administrator"),
    )
    resolver = FakeRoleResolver(authentication.RoleAssignment(configured=True, role="publisher"))
    authenticator = authentication.FirebaseAdminAuthenticator(
        "trs-80", app=object(), role_resolver=resolver
    )

    identity = authenticator.verify_session_cookie("session-cookie")

    assert identity.role == "publisher"
    assert resolver.uids == ["firebase-user"]


def test_explicit_stored_no_access_overrides_bootstrap_claim(monkeypatch) -> None:
    monkeypatch.setattr(
        authentication.auth,
        "verify_session_cookie",
        lambda *args, **kwargs: _claims(role="administrator"),
    )
    resolver = FakeRoleResolver(authentication.RoleAssignment(configured=True, role=None))
    authenticator = authentication.FirebaseAdminAuthenticator(
        "trs-80", app=object(), role_resolver=resolver
    )

    with pytest.raises(authentication.AuthorizationError, match="administration role"):
        authenticator.verify_session_cookie("session-cookie")


def test_authentication_clock_must_be_timezone_aware(monkeypatch) -> None:
    monkeypatch.setattr(authentication.auth, "verify_id_token", pytest.fail)
    authenticator = authentication.FirebaseAdminAuthenticator("trs-80", app=object())

    with pytest.raises(ValueError, match="timezone-aware"):
        authenticator.exchange_id_token("id-token", now=datetime(2026, 8, 7))


@pytest.mark.parametrize(
    ("claims", "expected"),
    (
        ({"role": "administrator"}, "administrator"),
        ({"role": "publisher"}, "publisher"),
        ({"admin": True}, "administrator"),
        ({"publisher": True}, "publisher"),
        ({"role": "unknown"}, None),
        ({}, None),
    ),
)
def test_admin_role_from_claims_normalizes_current_and_legacy_claims(claims, expected) -> None:
    assert authentication.admin_role_from_claims(claims) == expected
