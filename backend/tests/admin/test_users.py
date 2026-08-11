from types import SimpleNamespace

import pytest

import retrostore.admin.users as users
from retrostore.admin.auth import RoleAssignment


class FakePage:
    def __init__(self, records):
        self.records = records

    def iterate_all(self):
        return iter(self.records)


def _record(
    uid,
    email,
    *,
    claims=None,
    verified=True,
    disabled=False,
    providers=("google.com",),
):
    return SimpleNamespace(
        uid=uid,
        email=email,
        email_verified=verified,
        disabled=disabled,
        custom_claims=claims,
        provider_data=tuple(SimpleNamespace(provider_id=provider) for provider in providers),
    )


class FakeRoleStore:
    def __init__(self, assignments=None):
        self.assignments = assignments or {}
        self.changes = []

    def role_for(self, uid):
        return self.assignments.get(uid, RoleAssignment(configured=False, role=None))

    def roles_by_uid(self):
        return self.assignments

    def change_role(self, **change):
        self.changes.append(change)


def test_firebase_user_directory_normalizes_sorts_and_merges_stored_roles(
    monkeypatch,
) -> None:
    records = (
        _record(
            "publisher-1",
            "z@example.test",
            claims={"publisher": True},
            disabled=True,
        ),
        _record(
            "admin-1",
            "A@example.test",
            claims={"role": "administrator"},
            providers=("password", "google.com", "google.com"),
        ),
        _record("user-1", None, verified=False, claims={"role": "unknown"}),
    )
    role_store = FakeRoleStore(
        {
            "admin-1": RoleAssignment(configured=True, role="publisher"),
            "publisher-1": RoleAssignment(configured=True, role=None),
        }
    )
    observed = {}

    def list_users(**kwargs):
        observed.update(kwargs)
        return FakePage(records)

    monkeypatch.setattr(users.auth, "list_users", list_users)
    directory = users.FirebaseAdminUserDirectory("trs-80", app=object(), role_store=role_store)

    result = directory.list_users()

    assert [user.uid for user in result] == ["user-1", "admin-1", "publisher-1"]
    assert result[0].role is None
    assert result[1].role == "publisher"
    assert result[1].providers == ("google.com", "password")
    assert result[2].role is None
    assert result[2].disabled is True
    assert observed["app"] is directory._app


class FakeDirectory:
    def __init__(self, user):
        self.user = user

    def list_users(self):
        return (self.user,)

    def get_user(self, uid):
        assert uid == self.user.uid
        return self.user


def _admin_user(*, verified=True, role=None):
    return users.AdminUser(
        uid="target-user",
        email="target@example.test",
        email_verified=verified,
        disabled=False,
        role=role,
        providers=("google.com",),
    )


def test_role_manager_commits_validated_change_to_atomic_store() -> None:
    user = _admin_user()
    directory = FakeDirectory(user)
    role_store = FakeRoleStore()
    manager = users.AdminUserRoleManager(directory, role_store)

    updated = manager.change_role(
        actor_uid="admin-user",
        target_uid="target-user",
        requested_role="publisher",
    )

    assert updated.role == "publisher"
    assert role_store.changes == [
        {
            "actor_uid": "admin-user",
            "target": user,
            "expected_role": None,
            "requested_role": "publisher",
        }
    ]


@pytest.mark.parametrize(
    ("actor_uid", "verified", "requested_role", "message"),
    (
        ("target-user", True, "publisher", "own administrator role"),
        ("admin-user", False, "administrator", "verified email"),
        ("admin-user", True, "owner", "Role must be"),
    ),
)
def test_role_manager_rejects_unsafe_changes_before_storage(
    actor_uid, verified, requested_role, message
) -> None:
    directory = FakeDirectory(_admin_user(verified=verified))
    role_store = FakeRoleStore()
    manager = users.AdminUserRoleManager(directory, role_store)

    with pytest.raises(users.UserRoleChangeError, match=message):
        manager.change_role(
            actor_uid=actor_uid,
            target_uid="target-user",
            requested_role=requested_role,
        )

    assert role_store.changes == []


def test_role_manager_treats_unchanged_role_as_idempotent() -> None:
    directory = FakeDirectory(_admin_user(role="publisher"))
    role_store = FakeRoleStore()
    manager = users.AdminUserRoleManager(directory, role_store)

    result = manager.change_role(
        actor_uid="admin-user",
        target_uid="target-user",
        requested_role="publisher",
    )

    assert result.role == "publisher"
    assert role_store.changes == []


class FakeSnapshot:
    def __init__(self, document_id, value=None):
        self.id = document_id
        self.value = value
        self.exists = value is not None

    def to_dict(self):
        return self.value


class FakeDocument:
    def __init__(self, document_id, snapshot=None):
        self.id = document_id
        self.snapshot = snapshot or FakeSnapshot(document_id)

    def get(self, *, transaction=None):
        return self.snapshot


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = documents or {}

    def document(self, document_id=None):
        document_id = document_id or "event-1"
        return self.documents.setdefault(document_id, FakeDocument(document_id))

    def stream(self):
        return (
            document.snapshot for document in self.documents.values() if document.snapshot.exists
        )


class FakeTransaction:
    def __init__(self):
        self.sets = []
        self.creates = []

    def set(self, reference, value, *, merge=False):
        self.sets.append((reference.id, value, merge))

    def create(self, reference, value):
        self.creates.append((reference.id, value))


class FakeFirestore:
    def __init__(self, user_snapshots=None):
        user_documents = {
            snapshot.id: FakeDocument(snapshot.id, snapshot) for snapshot in (user_snapshots or ())
        }
        self.collections = {
            "users": FakeCollection(user_documents),
            "auditEvents": FakeCollection(),
        }
        self.transaction_value = FakeTransaction()

    def collection(self, name):
        return self.collections[name]

    def transaction(self):
        return self.transaction_value


def test_firestore_role_store_distinguishes_missing_and_explicit_no_access() -> None:
    client = FakeFirestore(
        (
            FakeSnapshot("publisher", {"role": "publisher"}),
            FakeSnapshot("denied", {"role": None}),
        )
    )
    store = users.FirestoreAdminRoleStore(client)

    assert store.role_for("missing") == RoleAssignment(configured=False, role=None)
    assert store.role_for("publisher") == RoleAssignment(configured=True, role="publisher")
    assert store.role_for("denied") == RoleAssignment(configured=True, role=None)
    assert store.roles_by_uid() == {
        "publisher": RoleAssignment(configured=True, role="publisher"),
        "denied": RoleAssignment(configured=True, role=None),
    }


def test_firestore_role_and_audit_event_are_written_in_one_transaction(
    monkeypatch,
) -> None:
    monkeypatch.setattr(users.firestore, "transactional", lambda function: function)
    client = FakeFirestore()
    store = users.FirestoreAdminRoleStore(client)
    target = _admin_user()

    store.change_role(
        actor_uid="admin-user",
        target=target,
        expected_role=None,
        requested_role="administrator",
    )

    transaction = client.transaction_value
    assert len(transaction.sets) == 1
    user_id, profile, merge = transaction.sets[0]
    assert user_id == "target-user"
    assert profile["role"] == "administrator"
    assert profile["updatedBy"] == "admin-user"
    assert merge is True
    assert len(transaction.creates) == 1
    event_id, event = transaction.creates[0]
    assert event_id == "event-1"
    assert event["eventType"] == "USER_ROLE_CHANGE"
    assert event["status"] == "SUCCEEDED"
    assert event["previousRole"] is None
    assert event["requestedRole"] == "administrator"


def test_firestore_role_store_rejects_concurrent_change(monkeypatch) -> None:
    monkeypatch.setattr(users.firestore, "transactional", lambda function: function)
    client = FakeFirestore((FakeSnapshot("target-user", {"role": "publisher"}),))
    store = users.FirestoreAdminRoleStore(client)

    with pytest.raises(users.UserRoleChangeError, match="concurrently"):
        store.change_role(
            actor_uid="admin-user",
            target=_admin_user(),
            expected_role=None,
            requested_role="administrator",
        )

    assert client.transaction_value.sets == []
    assert client.transaction_value.creates == []
