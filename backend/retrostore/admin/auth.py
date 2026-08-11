"""Firebase session-cookie authentication for the server-rendered admin."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import firebase_admin
from firebase_admin import auth, exceptions

SESSION_DURATION = timedelta(days=5)
RECENT_SIGN_IN_WINDOW = timedelta(minutes=5)
_ALLOWED_ROLES = frozenset({"administrator", "publisher"})


class AuthenticationError(Exception):
    """The supplied Firebase credential is missing, invalid, expired, or revoked."""


class AuthorizationError(Exception):
    """The authenticated Firebase identity cannot access administration routes."""


@dataclass(frozen=True, slots=True)
class AdminIdentity:
    uid: str
    email: str
    role: str

    @property
    def is_administrator(self) -> bool:
        return self.role == "administrator"


@dataclass(frozen=True, slots=True)
class SessionCookie:
    value: str
    identity: AdminIdentity


class AdminAuthenticator(Protocol):
    def exchange_id_token(self, id_token: str, *, now: datetime | None = None) -> SessionCookie: ...

    def verify_session_cookie(self, session_cookie: str) -> AdminIdentity: ...


@dataclass(frozen=True, slots=True)
class RoleAssignment:
    configured: bool
    role: str | None


class AdminRoleResolver(Protocol):
    def role_for(self, uid: str) -> RoleAssignment: ...


class FirebaseAdminAuthenticator:
    """Verify Firebase claims and exchange recent sign-ins for server cookies."""

    def __init__(
        self,
        project: str,
        *,
        app: firebase_admin.App | None = None,
        role_resolver: AdminRoleResolver | None = None,
    ) -> None:
        if not project:
            raise ValueError("Firebase project must be explicit")
        self._app = app or firebase_app(project)
        self._role_resolver = role_resolver

    def exchange_id_token(self, id_token: str, *, now: datetime | None = None) -> SessionCookie:
        if not id_token:
            raise AuthenticationError("Firebase ID token is missing")
        current = now or datetime.now(UTC)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("Authentication clock must be timezone-aware")
        try:
            claims = auth.verify_id_token(id_token, check_revoked=True, app=self._app)
            identity = _identity_from_claims(claims, self._role_resolver)
            auth_time = _numeric_date(claims, "auth_time")
            age = current.timestamp() - auth_time
            if age < -60 or age > RECENT_SIGN_IN_WINDOW.total_seconds():
                raise AuthenticationError("A recent Firebase sign-in is required")
            value = auth.create_session_cookie(
                id_token,
                expires_in=SESSION_DURATION,
                app=self._app,
            )
        except AuthorizationError:
            raise
        except AuthenticationError:
            raise
        except (exceptions.FirebaseError, ValueError, KeyError, TypeError) as error:
            raise AuthenticationError("Firebase ID token could not be verified") from error
        return SessionCookie(value=value, identity=identity)

    def verify_session_cookie(self, session_cookie: str) -> AdminIdentity:
        if not session_cookie:
            raise AuthenticationError("Firebase session cookie is missing")
        try:
            claims = auth.verify_session_cookie(
                session_cookie,
                check_revoked=True,
                app=self._app,
            )
            return _identity_from_claims(claims, self._role_resolver)
        except AuthorizationError:
            raise
        except (exceptions.FirebaseError, ValueError, KeyError, TypeError) as error:
            raise AuthenticationError("Firebase session cookie could not be verified") from error


def _identity_from_claims(
    claims: Mapping[str, Any], role_resolver: AdminRoleResolver | None = None
) -> AdminIdentity:
    uid = claims.get("uid", claims.get("sub"))
    email = claims.get("email")
    if not isinstance(uid, str) or not uid:
        raise AuthenticationError("Firebase credential has no user ID")
    if not isinstance(email, str) or not email:
        raise AuthorizationError("An email address is required for administration")
    if claims.get("email_verified") is not True:
        raise AuthorizationError("A verified email address is required for administration")

    role = admin_role_from_claims(claims)
    if role_resolver is not None:
        assignment = role_resolver.role_for(uid)
        if assignment.configured:
            role = assignment.role
    if role is None:
        raise AuthorizationError("The Firebase user has no RetroStore administration role")
    return AdminIdentity(uid=uid, email=email, role=role)


def admin_role_from_claims(claims: Mapping[str, Any]) -> str | None:
    """Normalize current and legacy Firebase role claims."""

    role = claims.get("role")
    if claims.get("admin") is True:
        role = "administrator"
    elif claims.get("publisher") is True and role is None:
        role = "publisher"
    return role if isinstance(role, str) and role in _ALLOWED_ROLES else None


def _numeric_date(claims: Mapping[str, Any], name: str) -> float:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AuthenticationError(f"Firebase credential has no valid {name}")
    return float(value)


def firebase_app(project: str) -> firebase_admin.App:
    name = f"retrostore-admin-{project}"
    try:
        return firebase_admin.get_app(name)
    except ValueError:
        return firebase_admin.initialize_app(options={"projectId": project}, name=name)
