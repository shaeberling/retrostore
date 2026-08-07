"""Firebase identity inventory and Firestore-backed RetroStore roles."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol

import firebase_admin
from firebase_admin import auth
from google.cloud import firestore

from retrostore.admin.auth import (
    RoleAssignment,
    admin_role_from_claims,
    firebase_app,
)

_ASSIGNABLE_ROLES = frozenset({"administrator", "publisher"})
_AUDIT_COLLECTION = "auditEvents"
_USERS_COLLECTION = "users"


class UserRoleChangeError(ValueError):
    """A requested role mutation violates an administration invariant."""


@dataclass(frozen=True, slots=True)
class AdminUser:
    uid: str
    email: str
    email_verified: bool
    disabled: bool
    role: str | None
    providers: tuple[str, ...]


class AdminUserDirectory(Protocol):
    def list_users(self) -> tuple[AdminUser, ...]: ...

    def get_user(self, uid: str) -> AdminUser: ...


class AdminRoleStore(Protocol):
    def role_for(self, uid: str) -> RoleAssignment: ...

    def roles_by_uid(self) -> Mapping[str, RoleAssignment]: ...

    def change_role(
        self,
        *,
        actor_uid: str,
        target: AdminUser,
        expected_role: str | None,
        requested_role: str | None,
    ) -> None: ...


class AdminUserRoleManager:
    """Validate a role change before committing role and audit data atomically."""

    def __init__(self, directory: AdminUserDirectory, role_store: AdminRoleStore) -> None:
        self._directory = directory
        self._role_store = role_store

    def change_role(
        self,
        *,
        actor_uid: str,
        target_uid: str,
        requested_role: str,
    ) -> AdminUser:
        role = _normalize_requested_role(requested_role)
        if actor_uid == target_uid:
            raise UserRoleChangeError("You cannot change your own administrator role")

        user = self._directory.get_user(target_uid)
        if role is not None and not user.email_verified:
            raise UserRoleChangeError("A verified email is required before granting access")
        if user.role == role:
            return user

        self._role_store.change_role(
            actor_uid=actor_uid,
            target=user,
            expected_role=user.role,
            requested_role=role,
        )
        return replace(user, role=role)


class FirestoreAdminRoleStore:
    """Resolve roles and atomically record each change in the durable database."""

    def __init__(self, client: firestore.Client) -> None:
        self._client = client

    def role_for(self, uid: str) -> RoleAssignment:
        snapshot = self._client.collection(_USERS_COLLECTION).document(uid).get()
        if not snapshot.exists:
            return RoleAssignment(configured=False, role=None)
        return RoleAssignment(configured=True, role=_stored_role(_document_data(snapshot)))

    def roles_by_uid(self) -> Mapping[str, RoleAssignment]:
        return {
            snapshot.id: RoleAssignment(
                configured=True,
                role=_stored_role(_document_data(snapshot)),
            )
            for snapshot in self._client.collection(_USERS_COLLECTION).stream()
        }

    def change_role(
        self,
        *,
        actor_uid: str,
        target: AdminUser,
        expected_role: str | None,
        requested_role: str | None,
    ) -> None:
        user_reference = self._client.collection(_USERS_COLLECTION).document(target.uid)
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()

        @firestore.transactional
        def commit_role_change(transaction: Any) -> None:
            snapshot = user_reference.get(transaction=transaction)
            current_role = (
                _stored_role(_document_data(snapshot)) if snapshot.exists else expected_role
            )
            if current_role != expected_role:
                raise UserRoleChangeError(
                    "The user's role changed concurrently; reload before trying again"
                )
            transaction.set(
                user_reference,
                {
                    "schemaVersion": 1,
                    "email": target.email,
                    "emailVerified": target.email_verified,
                    "role": requested_role,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                    "updatedBy": actor_uid,
                },
                merge=True,
            )
            transaction.create(
                audit_reference,
                {
                    "schemaVersion": 1,
                    "eventType": "USER_ROLE_CHANGE",
                    "status": "SUCCEEDED",
                    "actorUid": actor_uid,
                    "targetUid": target.uid,
                    "previousRole": expected_role,
                    "requestedRole": requested_role,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                },
            )

        commit_role_change(transaction)


class FirebaseAdminUserDirectory:
    """Read Firebase identities and merge server-side RetroStore role profiles."""

    def __init__(
        self,
        project: str,
        *,
        app: firebase_admin.App | None = None,
        role_store: AdminRoleStore | None = None,
    ) -> None:
        if not project:
            raise ValueError("Firebase project must be explicit")
        self._app = app or firebase_app(project)
        self._role_store = role_store

    def list_users(self) -> tuple[AdminUser, ...]:
        records: Iterable[auth.UserRecord] = auth.list_users(app=self._app).iterate_all()
        assignments = self._role_store.roles_by_uid() if self._role_store else {}
        users = tuple(
            _admin_user(record, assignments.get(record.uid)) for record in records
        )
        return tuple(sorted(users, key=lambda user: (user.email.casefold(), user.uid)))

    def get_user(self, uid: str) -> AdminUser:
        assignment = self._role_store.role_for(uid) if self._role_store else None
        return _admin_user(auth.get_user(uid, app=self._app), assignment)


def _admin_user(
    record: auth.UserRecord,
    assignment: RoleAssignment | None = None,
) -> AdminUser:
    claims = record.custom_claims or {}
    providers = tuple(
        sorted(
            {
                provider.provider_id
                for provider in record.provider_data
                if provider.provider_id
            }
        )
    )
    role = admin_role_from_claims(claims)
    if assignment is not None and assignment.configured:
        role = assignment.role
    return AdminUser(
        uid=record.uid,
        email=record.email or "",
        email_verified=bool(record.email_verified),
        disabled=bool(record.disabled),
        role=role,
        providers=providers,
    )


def _normalize_requested_role(value: str) -> str | None:
    if value == "none":
        return None
    if value not in _ASSIGNABLE_ROLES:
        raise UserRoleChangeError("Role must be administrator, publisher, or no access")
    return value


def _stored_role(value: Mapping[str, Any]) -> str | None:
    role = value.get("role")
    if role is None:
        return None
    if not isinstance(role, str) or role not in _ASSIGNABLE_ROLES:
        raise ValueError("Stored administrator role is invalid")
    return role


def _document_data(snapshot: Any) -> Mapping[str, Any]:
    value = snapshot.to_dict()
    if not isinstance(value, dict):
        raise ValueError("Stored administrator profile is malformed")
    return value
