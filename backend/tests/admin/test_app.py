from dataclasses import dataclass, field, replace
from io import BytesIO

from retrostore.admin.assets import ValidatedAssetUpload
from retrostore.admin.auth import (
    AdminIdentity,
    AuthenticationError,
    AuthorizationError,
    SessionCookie,
)
from retrostore.admin.catalog import AdminCatalogDetail
from retrostore.admin.staging import StagedApp, StagedAppDetail, StagedAppDraft
from retrostore.admin.users import AdminUser
from retrostore.mirror import NormalizedApp
from services.admin.app import create_app

FIREBASE_WEB_CONFIG = {
    "apiKey": "public-browser-key",
    "authDomain": "trs-80.firebaseapp.com",
    "projectId": "trs-80",
    "appId": "1:123:web:abc",
}


def _app(app_id: str = "app-1", name: str = "Armored Patrol") -> NormalizedApp:
    return NormalizedApp(
        id=app_id,
        name=name,
        version="1.0",
        description="Tank game",
        release_year=1981,
        platform="TRS80",
        model="MODEL_I",
        categories=("GAME",),
        author_id="42",
        author_name="Jane Doe",
        publisher_email="publisher@example.test",
        first_published_at_ms=1_500_000_000_000,
        updated_at_ms=1_600_000_000_000,
        disk_media_ids=(None, None, None, None),
        cassette_media_id=None,
        command_media_id=None,
        basic_media_id=None,
        screenshot_ids=(),
    )


@dataclass
class FakeCatalog:
    apps: tuple[NormalizedApp, ...] = (_app(),)

    def list_apps(self) -> tuple[NormalizedApp, ...]:
        return self.apps

    def get_app(self, app_id: str) -> AdminCatalogDetail | None:
        app = next((item for item in self.apps if item.id == app_id), None)
        return None if app is None else AdminCatalogDetail(app, (), ())


@dataclass
class FakeStagingCatalog:
    apps: tuple[StagedApp, ...] = (
        StagedApp(
            id="11111111-1111-4111-8111-111111111111",
            name="Staged Game",
            version="0.1",
            description="Not public",
            release_year=1982,
            model="MODEL_I",
            category="GAME",
            author_id="new-author",
            author_name="Test Author",
            publisher_uid="user-1",
            publisher_email="admin@example.test",
            revision=1,
        ),
    )
    creations: list[tuple[AdminIdentity, str, StagedAppDraft]] = field(
        default_factory=list
    )
    updates: list[tuple[AdminIdentity, str, int, StagedAppDraft]] = field(
        default_factory=list
    )
    deletions: list[tuple[AdminIdentity, str, int]] = field(default_factory=list)
    media_uploads: list[
        tuple[AdminIdentity, str, int, str, ValidatedAssetUpload]
    ] = field(default_factory=list)
    screenshot_uploads: list[
        tuple[AdminIdentity, str, int, ValidatedAssetUpload]
    ] = field(default_factory=list)

    def list_apps(self, identity):
        return self.apps

    def create_app(self, *, identity, request_id, draft):
        self.creations.append((identity, request_id, draft))
        return self.apps[0]

    def get_app(self, identity, app_id):
        return next((app for app in self.apps if app.id == app_id), None)

    def get_app_detail(self, identity, app_id):
        app = self.get_app(identity, app_id)
        return None if app is None else StagedAppDetail(app, (), ())

    def update_app(self, *, identity, app_id, expected_revision, draft):
        self.updates.append((identity, app_id, expected_revision, draft))
        return replace(
            self.apps[0],
            name=draft.name,
            version=draft.version,
            description=draft.description,
            release_year=draft.release_year,
            model=draft.model,
            category=draft.category,
            author_name=draft.author_name,
            revision=expected_revision + 1,
        )

    def delete_app(self, *, identity, app_id, expected_revision):
        self.deletions.append((identity, app_id, expected_revision))

    def upload_media(
        self, *, identity, app_id, expected_revision, slot, upload
    ):
        self.media_uploads.append(
            (identity, app_id, expected_revision, slot, upload)
        )
        return replace(self.apps[0], revision=expected_revision + 1)

    def upload_screenshot(self, *, identity, app_id, expected_revision, upload):
        self.screenshot_uploads.append(
            (identity, app_id, expected_revision, upload)
        )
        return replace(self.apps[0], revision=expected_revision + 1)


class FakeAuthenticator:
    identity = AdminIdentity("user-1", "admin@example.test", "administrator")

    def exchange_id_token(self, id_token: str, *, now=None) -> SessionCookie:
        if id_token == "forbidden":
            raise AuthorizationError
        if id_token != "valid-id-token":
            raise AuthenticationError
        return SessionCookie("valid-session", self.identity)

    def verify_session_cookie(self, session_cookie: str) -> AdminIdentity:
        if session_cookie != "valid-session":
            raise AuthenticationError
        return self.identity


class PublisherAuthenticator(FakeAuthenticator):
    identity = AdminIdentity("publisher-1", "publisher@example.test", "publisher")


@dataclass
class FakeUserDirectory:
    users: tuple[AdminUser, ...] = (
        AdminUser(
            uid="user-1",
            email="admin@example.test",
            email_verified=True,
            disabled=False,
            role="administrator",
            providers=("google.com",),
        ),
        AdminUser(
            uid="user-2",
            email="new-user@example.test",
            email_verified=True,
            disabled=False,
            role=None,
            providers=("google.com",),
        ),
    )

    def list_users(self) -> tuple[AdminUser, ...]:
        return self.users


@dataclass
class FakeUserRoleManager:
    changes: list[tuple[str, str, str]] = field(default_factory=list)

    def change_role(self, *, actor_uid, target_uid, requested_role):
        self.changes.append((actor_uid, target_uid, requested_role))
        return FakeUserDirectory().users[1]


_DEFAULT_MANAGER = object()


def _configured_app(
    *, authenticator=None, role_manager=_DEFAULT_MANAGER, staging_catalog=None
):
    if role_manager is _DEFAULT_MANAGER:
        role_manager = FakeUserRoleManager()
    return create_app(
        {
            "TESTING": True,
            "ADMIN_AUTHENTICATOR": authenticator or FakeAuthenticator(),
            "ADMIN_CATALOG": FakeCatalog(),
            "ADMIN_FIREBASE_WEB_CONFIG": FIREBASE_WEB_CONFIG,
            "ADMIN_SESSION_COOKIE_SECURE": False,
            "ADMIN_STAGING_CATALOG": staging_catalog or FakeStagingCatalog(),
            "ADMIN_USER_DIRECTORY": FakeUserDirectory(),
            "ADMIN_USER_ROLE_MANAGER": role_manager,
        }
    )


def _csrf_token(client) -> str:
    client.get("/admin/login")
    cookie = client.get_cookie("retrostore_admin_csrf", path="/admin")
    assert cookie is not None
    return cookie.value


def test_health_is_public_but_admin_redirects_to_login() -> None:
    client = _configured_app().test_client()

    assert client.get("/health").status_code == 200
    response = client.get("/admin")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/login")


def test_admin_is_not_ready_until_auth_persistence_and_web_config_exist() -> None:
    client = create_app({"TESTING": True}).test_client()

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.get_json() == {
        "ready": False,
        "checks": {
            "authentication": False,
            "firebase_web": False,
            "persistence": False,
            "staging_catalog": False,
            "user_directory": False,
            "user_role_management": False,
        },
    }
    assert client.get("/admin/login").status_code == 503


def test_login_page_sets_hardened_csrf_and_response_headers() -> None:
    client = _configured_app().test_client()

    response = client.get("/admin/login")

    assert response.status_code == 200
    assert b"Continue with Google" in response.data
    assert b"public-browser-key" in response.data
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "SameSite=Strict" in response.headers["Set-Cookie"]
    assert response.headers["Cache-Control"] == "no-store"
    csp = response.headers["Content-Security-Policy"]
    assert "script-src 'self' https://www.gstatic.com https://apis.google.com" in csp
    assert "https://identitytoolkit.googleapis.com" in csp
    assert "https://securetoken.googleapis.com" in csp
    assert "https://www.googleapis.com" in csp
    assert "https://www.gstatic.com" in csp
    assert "frame-src https://trs-80.firebaseapp.com" in csp
    assert "frame-ancestors 'none'" in csp


def test_malformed_firebase_auth_domain_is_not_trusted_by_login_or_csp() -> None:
    config = dict(FIREBASE_WEB_CONFIG)
    config["authDomain"] = "trs-80.firebaseapp.com; script-src *"
    app = create_app(
        {
            "TESTING": True,
            "ADMIN_AUTHENTICATOR": FakeAuthenticator(),
            "ADMIN_CATALOG": FakeCatalog(),
            "ADMIN_FIREBASE_WEB_CONFIG": config,
            "ADMIN_SESSION_COOKIE_SECURE": False,
        }
    )

    response = app.test_client().get("/admin/login")

    assert response.status_code == 503
    assert "frame-src 'none'" in response.headers["Content-Security-Policy"]
    assert "script-src *" not in response.headers["Content-Security-Policy"]


def test_session_exchange_requires_csrf_and_sets_secure_server_cookie() -> None:
    client = _configured_app().test_client()
    csrf_token = _csrf_token(client)

    rejected = client.post(
        "/admin/session",
        json={"id_token": "valid-id-token", "csrf_token": "wrong"},
    )
    accepted = client.post(
        "/admin/session",
        json={"id_token": "valid-id-token", "csrf_token": csrf_token},
    )

    assert rejected.status_code == 403
    assert accepted.status_code == 200
    assert accepted.get_json() == {"redirect": "/admin/apps", "status": "success"}
    session_header = accepted.headers["Set-Cookie"]
    assert "retrostore_admin_session=valid-session" in session_header
    assert "HttpOnly" in session_header
    assert "SameSite=Lax" in session_header
    assert "Path=/admin" in session_header


def test_session_exchange_rejects_invalid_or_unauthorized_identities() -> None:
    client = _configured_app().test_client()
    csrf_token = _csrf_token(client)

    invalid = client.post(
        "/admin/session",
        json={"id_token": "invalid", "csrf_token": csrf_token},
    )
    forbidden = client.post(
        "/admin/session",
        json={"id_token": "forbidden", "csrf_token": csrf_token},
    )

    assert invalid.status_code == 401
    assert forbidden.status_code == 403


def test_authenticated_catalog_list_search_detail_and_logout() -> None:
    client = _configured_app().test_client()
    csrf_token = _csrf_token(client)
    client.post(
        "/admin/session",
        json={"id_token": "valid-id-token", "csrf_token": csrf_token},
    )

    listing = client.get("/admin/apps")
    search = client.get("/admin/apps?q=jane")
    empty = client.get("/admin/apps?q=missing")
    detail = client.get("/admin/apps/app-1")
    missing = client.get("/admin/apps/no-such-app")
    logout = client.post("/admin/logout", data={"csrf_token": csrf_token})

    assert listing.status_code == 200
    assert b"Armored Patrol" in listing.data
    assert b"admin@example.test" in listing.data
    assert b"Armored Patrol" in search.data
    assert b"No applications match this search" in empty.data
    assert detail.status_code == 200
    assert b"Tank game" in detail.data
    assert missing.status_code == 404
    assert logout.status_code == 302
    assert "retrostore_admin_session=;" in logout.headers["Set-Cookie"]


def test_staging_list_form_validation_and_atomic_create_boundary() -> None:
    catalog = FakeStagingCatalog()
    client = _configured_app(staging_catalog=catalog).test_client()
    csrf_token = _csrf_token(client)
    client.post(
        "/admin/session",
        json={"id_token": "valid-id-token", "csrf_token": csrf_token},
    )

    listing = client.get("/admin/staging/apps")
    form = client.get("/admin/staging/apps/new")
    rejected = client.post(
        "/admin/staging/apps",
        data={"csrf_token": csrf_token, "request_id": "bad", "name": "Kept"},
    )
    accepted = client.post(
        "/admin/staging/apps",
        data={
            "csrf_token": csrf_token,
            "request_id": "22222222-2222-4222-8222-222222222222",
            "name": "  New Game  ",
            "version": "  1.0  ",
            "description": "  A staged application.  ",
            "release_year": "1983",
            "model": "MODEL_III",
            "category": "GAME_ARCADE",
            "author_name": "  Jane   Doe  ",
        },
    )

    assert listing.status_code == 200
    assert b"Staged Game" in listing.data
    assert b"cannot appear in the public API" in listing.data
    assert form.status_code == 200
    assert b"New staged application" in form.data
    assert rejected.status_code == 400
    assert b"Kept" in rejected.data
    assert b"request identifier is invalid" in rejected.data
    assert accepted.status_code == 302
    assert accepted.headers["Location"].endswith(
        "/admin/staging/apps?app_created=1"
    )
    assert len(catalog.creations) == 1
    identity, request_id, draft = catalog.creations[0]
    assert identity.uid == "user-1"
    assert request_id == "22222222-2222-4222-8222-222222222222"
    assert draft.name == "New Game"
    assert draft.author_name == "Jane Doe"


def test_staging_detail_edit_and_confirmed_delete_lifecycle() -> None:
    catalog = FakeStagingCatalog()
    app_id = catalog.apps[0].id
    client = _configured_app(staging_catalog=catalog).test_client()
    csrf_token = _csrf_token(client)
    client.post(
        "/admin/session",
        json={"id_token": "valid-id-token", "csrf_token": csrf_token},
    )

    detail = client.get(f"/admin/staging/apps/{app_id}")
    edit = client.get(f"/admin/staging/apps/{app_id}/edit")
    update = client.post(
        f"/admin/staging/apps/{app_id}",
        data={
            "csrf_token": csrf_token,
            "request_id": app_id,
            "revision": "1",
            "name": "Updated Game",
            "version": "1.1",
            "description": "Updated staged application.",
            "release_year": "1984",
            "model": "MODEL_4",
            "category": "OTHER",
            "author_name": "New Author",
        },
    )
    unconfirmed_delete = client.post(
        f"/admin/staging/apps/{app_id}/delete",
        data={
            "csrf_token": csrf_token,
            "revision": "1",
            "confirm_name": "wrong",
        },
    )
    confirmed_delete = client.post(
        f"/admin/staging/apps/{app_id}/delete",
        data={
            "csrf_token": csrf_token,
            "revision": "1",
            "confirm_name": "Staged Game",
        },
    )

    assert detail.status_code == 200
    assert b"revision 1" in detail.data
    assert b"Enter the exact app name" in detail.data
    assert edit.status_code == 200
    assert b"Edit Staged Game" in edit.data
    assert update.status_code == 302
    assert update.headers["Location"].endswith(f"/admin/staging/apps/{app_id}")
    assert catalog.updates[0][2] == 1
    assert catalog.updates[0][3].name == "Updated Game"
    assert unconfirmed_delete.status_code == 400
    assert catalog.deletions == [
        (FakeAuthenticator.identity, app_id, 1),
    ]
    assert confirmed_delete.status_code == 302
    assert confirmed_delete.headers["Location"].endswith(
        "/admin/staging/apps?app_deleted=1"
    )


def test_staging_media_and_screenshot_upload_routes_validate_and_delegate() -> None:
    catalog = FakeStagingCatalog()
    app_id = catalog.apps[0].id
    client = _configured_app(staging_catalog=catalog).test_client()
    csrf_token = _csrf_token(client)
    client.post(
        "/admin/session",
        json={"id_token": "valid-id-token", "csrf_token": csrf_token},
    )

    media = client.post(
        f"/admin/staging/apps/{app_id}/media",
        data={
            "csrf_token": csrf_token,
            "revision": "1",
            "slot": "disk-2",
            "description": "Boot disk",
            "file": (BytesIO(b"disk image"), "C:\\uploads\\game.dmk"),
        },
        content_type="multipart/form-data",
    )
    invalid_screenshot = client.post(
        f"/admin/staging/apps/{app_id}/screenshots",
        data={
            "csrf_token": csrf_token,
            "revision": "1",
            "file": (BytesIO(b"not an image"), "screen.txt"),
        },
        content_type="multipart/form-data",
    )
    screenshot = client.post(
        f"/admin/staging/apps/{app_id}/screenshots",
        data={
            "csrf_token": csrf_token,
            "revision": "1",
            "file": (BytesIO(b"\x89PNG\r\n\x1a\ncontent"), "screen.png"),
        },
        content_type="multipart/form-data",
    )

    assert media.status_code == 302
    assert media.headers["Location"].endswith(f"/{app_id}?media_updated=1")
    assert catalog.media_uploads[0][2:4] == (1, "disk-2")
    assert catalog.media_uploads[0][4].filename == "game.dmk"
    assert catalog.media_uploads[0][4].description == "Boot disk"
    assert invalid_screenshot.status_code == 400
    assert b"valid PNG, JPEG, GIF, or WebP" in invalid_screenshot.data
    assert screenshot.status_code == 302
    assert catalog.screenshot_uploads[0][3].content_type == "image/png"


def test_administrator_can_view_user_inventory() -> None:
    client = _configured_app().test_client()
    csrf_token = _csrf_token(client)
    client.post(
        "/admin/session",
        json={"id_token": "valid-id-token", "csrf_token": csrf_token},
    )

    response = client.get("/admin/users")

    assert response.status_code == 200
    assert b"admin@example.test" in response.data
    assert b"new-user@example.test" in response.data
    assert b"administrator" in response.data
    assert b"google.com" in response.data
    assert b"Changes are audited" in response.data
    assert b"cannot change your own role" in response.data


def test_administrator_role_change_requires_csrf_and_redirects_after_audit() -> None:
    manager = FakeUserRoleManager()
    client = _configured_app(role_manager=manager).test_client()
    csrf_token = _csrf_token(client)
    client.post(
        "/admin/session",
        json={"id_token": "valid-id-token", "csrf_token": csrf_token},
    )

    rejected = client.post(
        "/admin/users/user-2/role",
        data={"csrf_token": "wrong", "role": "publisher"},
    )
    accepted = client.post(
        "/admin/users/user-2/role",
        data={"csrf_token": csrf_token, "role": "publisher"},
    )

    assert rejected.status_code == 403
    assert accepted.status_code == 302
    assert accepted.headers["Location"].endswith("/admin/users?role_updated=1")
    assert manager.changes == [("user-1", "user-2", "publisher")]


def test_publisher_cannot_view_user_inventory() -> None:
    manager = FakeUserRoleManager()
    client = _configured_app(
        authenticator=PublisherAuthenticator(), role_manager=manager
    ).test_client()
    csrf_token = _csrf_token(client)
    client.post(
        "/admin/session",
        json={"id_token": "valid-id-token", "csrf_token": csrf_token},
    )

    response = client.get("/admin/users")
    mutation = client.post(
        "/admin/users/user-1/role",
        data={"csrf_token": csrf_token, "role": "none"},
    )

    assert response.status_code == 403
    assert mutation.status_code == 403
    assert manager.changes == []


def test_invalid_session_is_cleared_before_redirect() -> None:
    client = _configured_app().test_client()
    client.set_cookie("retrostore_admin_session", "invalid", path="/admin")

    response = client.get("/admin/apps")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/login")
    assert "retrostore_admin_session=;" in response.headers["Set-Cookie"]
