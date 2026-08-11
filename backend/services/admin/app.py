"""Flask entry point for the server-rendered administration candidate."""

import json
import os
import re
import secrets
from collections.abc import Mapping
from io import BytesIO
from typing import Any

from flask import (
    Flask,
    Response,
    abort,
    current_app,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from retrostore.admin.assets import (
    MEDIA_MAX_BYTES,
    SCREENSHOT_MAX_BYTES,
    STAGED_MEDIA_SLOTS,
    CloudStagingObjectStore,
    StagingAssetValidationError,
    validate_media_slot,
    validate_media_upload,
    validate_screenshot_upload,
)
from retrostore.admin.auth import (
    SESSION_DURATION,
    AdminAuthenticator,
    AdminIdentity,
    AuthenticationError,
    AuthorizationError,
    FirebaseAdminAuthenticator,
)
from retrostore.admin.catalog import AdminCatalog, FirestoreAdminCatalog
from retrostore.admin.drafts import (
    AdminPublishedAppDrafts,
)
from retrostore.admin.rpk import RPK_MAX_BYTES, RpkValidationError, ValidatedRpk, validate_rpk
from retrostore.admin.staging import (
    STAGED_APP_CATEGORIES,
    STAGED_APP_MODELS,
    AdminStagingCatalog,
    FirestoreAdminStagingCatalog,
    StagedApp,
    StagedAppDetail,
    StagingAuthorizationError,
    StagingConflictError,
    StagingNotFoundError,
    new_staged_app_request_id,
    validate_staged_app_form,
)
from retrostore.admin.users import (
    AdminUserDirectory,
    AdminUserRoleManager,
    FirebaseAdminUserDirectory,
    FirestoreAdminRoleStore,
    UserRoleChangeError,
)
from retrostore.observability import register_request_observability

_SESSION_COOKIE = "retrostore_admin_session"
_CSRF_COOKIE = "retrostore_admin_csrf"
_MAX_ID_TOKEN_BYTES = 16 * 1024
_FIREBASE_WEB_CONFIG_FIELDS = frozenset({"apiKey", "authDomain", "projectId", "appId"})
_DNS_NAME = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
    re.IGNORECASE,
)


def create_app(config: Mapping[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        ADMIN_AUTHENTICATOR=None,
        ADMIN_CATALOG=None,
        ADMIN_PUBLISHED_APP_DRAFTS=None,
        ADMIN_FIREBASE_WEB_CONFIG=None,
        ADMIN_SESSION_COOKIE_SECURE=True,
        ADMIN_STAGING_CATALOG=None,
        ADMIN_USER_DIRECTORY=None,
        ADMIN_USER_ROLE_MANAGER=None,
        MAX_CONTENT_LENGTH=RPK_MAX_BYTES + 1024 * 1024,
        RETROSTORE_PROJECT=os.environ.get("RETROSTORE_PROJECT"),
        RETROSTORE_REQUEST_LOGGING=True,
    )
    if config:
        app.config.from_mapping(config)

    register_request_observability(app, service="retrostore-admin")

    @app.before_request
    def authenticate_admin() -> Response | None:
        if not request.path.startswith("/admin"):
            return None
        if request.endpoint in {"admin_login", "admin_session"}:
            return None

        authenticator: AdminAuthenticator | None = app.config["ADMIN_AUTHENTICATOR"]
        catalog: AdminCatalog | None = app.config["ADMIN_CATALOG"]
        if authenticator is None or catalog is None:
            abort(503, "Administration authentication or persistence is not configured")

        session_cookie = request.cookies.get(_SESSION_COOKIE, "")
        if not session_cookie:
            return redirect(url_for("admin_login"))
        try:
            g.admin_identity = authenticator.verify_session_cookie(session_cookie)
        except AuthorizationError:
            abort(403)
        except AuthenticationError:
            response = make_response(redirect(url_for("admin_login")))
            _clear_session_cookie(response)
            return response

        g.admin_csrf_token = request.cookies.get(_CSRF_COOKIE) or _new_csrf_token()
        g.set_admin_csrf_cookie = _CSRF_COOKIE not in request.cookies
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not _tokens_match(g.admin_csrf_token, supplied):
                abort(403, "CSRF validation failed")
        return None

    @app.after_request
    def secure_admin_response(response: Response) -> Response:
        if request.path.startswith("/admin"):
            firebase_auth_origin = _firebase_auth_origin(
                app.config["ADMIN_FIREBASE_WEB_CONFIG"]
            )
            auth_frame_source = firebase_auth_origin or "'none'"
            response.headers["Cache-Control"] = "no-store"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' https://www.gstatic.com https://apis.google.com; "
                "style-src 'self'; "
                "img-src 'self' data:; "
                "connect-src 'self' https://identitytoolkit.googleapis.com "
                "https://securetoken.googleapis.com https://www.googleapis.com "
                "https://www.gstatic.com; "
                f"frame-src {auth_frame_source}; "
                "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
            )
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            if getattr(g, "set_admin_csrf_cookie", False):
                _set_csrf_cookie(
                    response,
                    g.admin_csrf_token,
                    secure=bool(app.config["ADMIN_SESSION_COOKIE_SECURE"]),
                )
        return response

    @app.context_processor
    def admin_template_context() -> dict[str, object]:
        return {
            "admin_identity": getattr(g, "admin_identity", None),
            "admin_csrf_token": getattr(g, "admin_csrf_token", None),
        }

    @app.get("/healthz")
    @app.get("/health")
    def health() -> tuple[dict[str, str], int]:
        return {"service": "retrostore-admin", "status": "alive"}, 200

    @app.get("/readyz")
    @app.get("/ready")
    def readiness() -> tuple[dict[str, object], int]:
        checks = {
            "authentication": app.config["ADMIN_AUTHENTICATOR"] is not None,
            "persistence": app.config["ADMIN_CATALOG"] is not None,
            "staging_catalog": app.config["ADMIN_STAGING_CATALOG"] is not None,
            "user_directory": app.config["ADMIN_USER_DIRECTORY"] is not None,
            "user_role_management": app.config["ADMIN_USER_ROLE_MANAGER"] is not None,
            "firebase_web": _valid_firebase_web_config(
                app.config["ADMIN_FIREBASE_WEB_CONFIG"]
            ),
        }
        ready = all(checks.values())
        return {"ready": ready, "checks": checks}, 200 if ready else 503

    @app.get("/admin/login")
    def admin_login() -> tuple[str, int] | str:
        firebase_config = app.config["ADMIN_FIREBASE_WEB_CONFIG"]
        configured = (
            app.config["ADMIN_AUTHENTICATOR"] is not None
            and _valid_firebase_web_config(firebase_config)
        )
        csrf_token = request.cookies.get(_CSRF_COOKIE) or _new_csrf_token()
        g.admin_csrf_token = csrf_token
        g.set_admin_csrf_cookie = _CSRF_COOKIE not in request.cookies
        page = render_template(
            "admin/login.html",
            firebase_config=firebase_config if configured else None,
            login_configured=configured,
            csrf_token=csrf_token,
        )
        return page if configured else (page, 503)

    @app.post("/admin/session")
    def admin_session() -> Response:
        authenticator: AdminAuthenticator | None = app.config["ADMIN_AUTHENTICATOR"]
        if authenticator is None:
            abort(503, "Administration authentication is not configured")
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400, "Expected a JSON login request")
        csrf_cookie = request.cookies.get(_CSRF_COOKIE)
        csrf_token = payload.get("csrf_token")
        if not _tokens_match(csrf_cookie, csrf_token):
            abort(403, "CSRF validation failed")
        id_token = payload.get("id_token")
        if (
            not isinstance(id_token, str)
            or not id_token
            or len(id_token.encode()) > _MAX_ID_TOKEN_BYTES
        ):
            abort(400, "Firebase ID token is missing or invalid")
        try:
            session = authenticator.exchange_id_token(id_token)
        except AuthorizationError:
            abort(403)
        except AuthenticationError:
            abort(401)

        response = jsonify({"status": "success", "redirect": url_for("admin_apps")})
        response.set_cookie(
            _SESSION_COOKIE,
            session.value,
            max_age=int(SESSION_DURATION.total_seconds()),
            secure=bool(app.config["ADMIN_SESSION_COOKIE_SECURE"]),
            httponly=True,
            samesite="Lax",
            path="/admin",
        )
        return response

    @app.get("/admin")
    def admin_index() -> Response:
        return redirect(url_for("admin_apps"))

    @app.get("/admin/apps")
    def admin_apps() -> str:
        catalog: AdminCatalog = app.config["ADMIN_CATALOG"]
        query = request.args.get("q", "").strip()
        apps = catalog.list_apps()
        if query:
            needle = query.casefold()
            apps = tuple(
                item
                for item in apps
                if any(
                    needle in value.casefold()
                    for value in (
                        item.id,
                        item.name,
                        item.author_name,
                        item.publisher_email,
                    )
                )
            )
        return render_template("admin/apps.html", apps=apps, query=query)

    @app.get("/admin/apps/<app_id>")
    def admin_app_detail(app_id: str) -> str:
        catalog: AdminCatalog = app.config["ADMIN_CATALOG"]
        detail = catalog.get_app(app_id)
        if detail is None:
            abort(404)
        return render_template("admin/app_detail.html", detail=detail)

    @app.get("/admin/staging/apps")
    def admin_staging_apps() -> str:
        catalog: AdminStagingCatalog | None = app.config["ADMIN_STAGING_CATALOG"]
        if catalog is None:
            abort(503, "Staging catalog is not configured")
        return render_template(
            "admin/staging_apps.html",
            apps=catalog.list_apps(g.admin_identity),
            app_created=request.args.get("app_created") == "1",
            app_deleted=request.args.get("app_deleted") == "1",
        )

    @app.get("/admin/staging/apps/new")
    def admin_staging_app_new() -> str:
        if app.config["ADMIN_STAGING_CATALOG"] is None:
            abort(503, "Staging catalog is not configured")
        return _render_staging_app_form(
            values={
                "request_id": new_staged_app_request_id(),
                "name": "",
                "version": "",
                "description": "",
                "release_year": "",
                "model": "MODEL_I",
                "category": "GAME",
                "author_name": "",
            },
            errors={},
            form_action=url_for("admin_staging_app_create"),
            heading="New application",
            submit_label="Create draft app",
        )

    @app.get("/admin/staging/import")
    def admin_staging_rpk_import() -> str:
        if app.config["ADMIN_STAGING_CATALOG"] is None:
            abort(503, "Staging catalog is not configured")
        return _render_rpk_import()

    @app.post("/admin/staging/import/preview")
    def admin_staging_rpk_preview() -> tuple[str, int] | str:
        try:
            package = _uploaded_rpk()
        except RpkValidationError as error:
            return _render_rpk_import(error=str(error)), 400
        return _render_rpk_import(package=package)

    @app.post("/admin/staging/import/apply")
    def admin_staging_rpk_apply() -> Response | tuple[str, int]:
        catalog = _staging_catalog_or_error()
        try:
            package = _uploaded_rpk()
        except RpkValidationError as error:
            return _render_rpk_import(error=str(error)), 400
        expected_sha256 = request.form.get("expected_sha256", "")
        if expected_sha256 != package.package_sha256:
            return (
                _render_rpk_import(
                    package=package,
                    error=(
                        "The re-uploaded file does not match the preview. "
                        "Preview this exact package before importing it."
                    ),
                ),
                400,
            )
        try:
            imported = catalog.import_rpk(identity=g.admin_identity, package=package)
        except StagingConflictError as error:
            return _render_rpk_import(package=package, error=str(error)), 409
        return redirect(
            url_for("admin_staging_app_detail", app_id=imported.id, rpk_imported="1")
        )

    @app.post("/admin/staging/apps")
    def admin_staging_app_create() -> Response | tuple[str, int]:
        catalog: AdminStagingCatalog | None = app.config["ADMIN_STAGING_CATALOG"]
        if catalog is None:
            abort(503, "Staging catalog is not configured")
        form = validate_staged_app_form(request.form)
        if form.draft is None:
            return (
                _render_staging_app_form(
                    values=form.values,
                    errors=form.errors,
                    form_action=url_for("admin_staging_app_create"),
                    heading="New application",
                    submit_label="Create draft app",
                ),
                400,
            )
        catalog.create_app(
            identity=g.admin_identity,
            request_id=form.values["request_id"],
            draft=form.draft,
        )
        return redirect(url_for("admin_staging_apps", app_created="1"))

    @app.get("/admin/staging/apps/<app_id>")
    def admin_staging_app_detail(app_id: str) -> str:
        return _render_staged_app_detail(app_id)

    @app.post("/admin/staging/apps/<app_id>/draft/create")
    def admin_published_app_draft_create(app_id: str) -> Response:
        try:
            draft = _draft_catalog_or_error().create(
                identity=g.admin_identity, app_id=app_id
            )
        except StagingAuthorizationError:
            abort(403)
        except StagingNotFoundError:
            abort(404)
        except StagingConflictError as error:
            abort(409, str(error))
        return redirect(
            url_for(
                "admin_published_app_draft_edit",
                app_id=draft.id,
                draft_created="1",
            )
        )

    @app.get("/admin/staging/apps/<app_id>/draft/edit")
    def admin_published_app_draft_edit(app_id: str) -> str:
        draft = _published_app_draft_or_error(app_id)
        return _render_staging_app_form(
            values=_staged_app_form_values(draft),
            errors={},
            form_action=url_for("admin_published_app_draft_update", app_id=app_id),
            heading=f"Draft changes to {draft.name}",
            submit_label="Save draft",
            back_url=url_for("admin_published_app_draft_detail", app_id=app_id),
            cancel_url=url_for("admin_published_app_draft_detail", app_id=app_id),
            eyebrow="Copy-on-write published draft",
            intro=(
                "This editable overlay leaves the published baseline and active "
                "public snapshot unchanged."
            ),
            discard_action=url_for(
                "admin_published_app_draft_discard", app_id=app_id
            ),
            discard_name=draft.name,
            draft_created=request.args.get("draft_created") == "1",
        )

    @app.get("/admin/staging/apps/<app_id>/draft")
    def admin_published_app_draft_detail(app_id: str) -> str:
        return _render_published_app_draft_detail(app_id)

    @app.post("/admin/staging/apps/<app_id>/draft")
    def admin_published_app_draft_update(app_id: str) -> Response | tuple[str, int]:
        form = validate_staged_app_form(request.form, allow_existing_id=True)
        errors = dict(form.errors)
        if form.values["request_id"] != app_id:
            errors["request_id"] = "The form does not match this draft; reload it."
        try:
            expected_revision = _positive_revision(request.form.get("revision"))
        except ValueError as error:
            errors["revision"] = str(error)
            expected_revision = 0
        if form.draft is None or errors:
            return (
                _render_staging_app_form(
                    values={**form.values, "revision": request.form.get("revision", "")},
                    errors=errors,
                    form_action=url_for(
                        "admin_published_app_draft_update", app_id=app_id
                    ),
                    heading="Edit published app draft",
                    submit_label="Save draft",
                    back_url=url_for(
                        "admin_published_app_draft_detail", app_id=app_id
                    ),
                    cancel_url=url_for(
                        "admin_published_app_draft_detail", app_id=app_id
                    ),
                    eyebrow="Copy-on-write published draft",
                    intro=(
                        "This editable overlay leaves the published baseline and "
                        "active public snapshot unchanged."
                    ),
                ),
                400,
            )
        try:
            updated = _draft_catalog_or_error().update(
                identity=g.admin_identity,
                app_id=app_id,
                expected_revision=expected_revision,
                draft=form.draft,
            )
        except StagingAuthorizationError:
            abort(403)
        except StagingNotFoundError:
            abort(404)
        except StagingConflictError as error:
            abort(409, str(error))
        return redirect(
            url_for(
                "admin_published_app_draft_edit",
                app_id=updated.id,
                draft_updated="1",
            )
        )

    @app.post("/admin/staging/apps/<app_id>/draft/discard")
    def admin_published_app_draft_discard(app_id: str) -> Response:
        draft = _published_app_draft_or_error(app_id)
        try:
            expected_revision = _positive_revision(request.form.get("revision"))
        except ValueError as error:
            abort(400, str(error))
        if request.form.get("confirm_name") != draft.name:
            abort(400, "Enter the exact draft app name to confirm discard")
        try:
            _draft_catalog_or_error().discard(
                identity=g.admin_identity,
                app_id=app_id,
                expected_revision=expected_revision,
            )
        except StagingAuthorizationError:
            abort(403)
        except StagingNotFoundError:
            abort(404)
        except StagingConflictError as error:
            abort(409, str(error))
        return redirect(
            url_for("admin_staging_app_detail", app_id=app_id, draft_discarded="1")
        )

    @app.post("/admin/staging/apps/<app_id>/draft/media")
    def admin_published_app_draft_media_upload(
        app_id: str,
    ) -> Response | tuple[str, int]:
        catalog = _draft_catalog_or_error()
        _published_app_draft_or_error(app_id)
        try:
            expected_revision = _positive_revision(request.form.get("revision"))
            slot = request.form.get("slot", "")
            validate_media_slot(slot)
            uploaded_file = request.files.get("file")
            if uploaded_file is None:
                raise StagingAssetValidationError("Choose a media image to upload.")
            body = uploaded_file.stream.read(MEDIA_MAX_BYTES + 1)
            upload = validate_media_upload(
                filename=uploaded_file.filename or "",
                body=body,
                description=request.form.get("description", ""),
            )
        except (StagingAssetValidationError, ValueError) as error:
            return (
                _render_published_app_draft_detail(
                    app_id, asset_error=str(error)
                ),
                400,
            )
        try:
            catalog.upload_media(
                identity=g.admin_identity,
                app_id=app_id,
                expected_revision=expected_revision,
                slot=slot,
                upload=upload,
            )
        except StagingAuthorizationError:
            abort(403)
        except StagingNotFoundError:
            abort(404)
        except StagingConflictError as error:
            abort(409, str(error))
        return redirect(
            url_for(
                "admin_published_app_draft_detail",
                app_id=app_id,
                media_updated="1",
            )
        )

    @app.post("/admin/staging/apps/<app_id>/draft/media/<media_id>/delete")
    def admin_published_app_draft_media_delete(
        app_id: str, media_id: str
    ) -> Response:
        try:
            _draft_catalog_or_error().delete_media(
                identity=g.admin_identity,
                app_id=app_id,
                media_id=media_id,
                expected_revision=_positive_revision(request.form.get("revision")),
            )
        except StagingAuthorizationError:
            abort(403)
        except StagingNotFoundError:
            abort(404)
        except StagingConflictError as error:
            abort(409, str(error))
        except ValueError as error:
            abort(400, str(error))
        return redirect(
            url_for(
                "admin_published_app_draft_detail",
                app_id=app_id,
                media_deleted="1",
            )
        )

    @app.post("/admin/staging/apps/<app_id>/draft/screenshots")
    def admin_published_app_draft_screenshot_upload(
        app_id: str,
    ) -> Response | tuple[str, int]:
        catalog = _draft_catalog_or_error()
        _published_app_draft_or_error(app_id)
        try:
            expected_revision = _positive_revision(request.form.get("revision"))
            uploaded_file = request.files.get("file")
            if uploaded_file is None:
                raise StagingAssetValidationError("Choose a screenshot to upload.")
            upload = validate_screenshot_upload(
                filename=uploaded_file.filename or "",
                body=uploaded_file.stream.read(SCREENSHOT_MAX_BYTES + 1),
            )
        except (StagingAssetValidationError, ValueError) as error:
            return (
                _render_published_app_draft_detail(
                    app_id, asset_error=str(error)
                ),
                400,
            )
        try:
            catalog.upload_screenshot(
                identity=g.admin_identity,
                app_id=app_id,
                expected_revision=expected_revision,
                upload=upload,
            )
        except StagingAuthorizationError:
            abort(403)
        except StagingNotFoundError:
            abort(404)
        except StagingConflictError as error:
            abort(409, str(error))
        return redirect(
            url_for(
                "admin_published_app_draft_detail",
                app_id=app_id,
                screenshot_added="1",
            )
        )

    @app.post(
        "/admin/staging/apps/<app_id>/draft/screenshots/<screenshot_id>/move"
    )
    def admin_published_app_draft_screenshot_move(
        app_id: str, screenshot_id: str
    ) -> Response:
        try:
            _draft_catalog_or_error().move_screenshot(
                identity=g.admin_identity,
                app_id=app_id,
                screenshot_id=screenshot_id,
                expected_revision=_positive_revision(request.form.get("revision")),
                direction=request.form.get("direction", ""),
            )
        except StagingAuthorizationError:
            abort(403)
        except StagingNotFoundError:
            abort(404)
        except StagingConflictError as error:
            abort(409, str(error))
        except ValueError as error:
            abort(400, str(error))
        return redirect(
            url_for("admin_published_app_draft_detail", app_id=app_id)
        )

    @app.post(
        "/admin/staging/apps/<app_id>/draft/screenshots/<screenshot_id>/delete"
    )
    def admin_published_app_draft_screenshot_delete(
        app_id: str, screenshot_id: str
    ) -> Response:
        try:
            _draft_catalog_or_error().delete_screenshot(
                identity=g.admin_identity,
                app_id=app_id,
                screenshot_id=screenshot_id,
                expected_revision=_positive_revision(request.form.get("revision")),
            )
        except StagingAuthorizationError:
            abort(403)
        except StagingNotFoundError:
            abort(404)
        except StagingConflictError as error:
            abort(409, str(error))
        except ValueError as error:
            abort(400, str(error))
        return redirect(
            url_for(
                "admin_published_app_draft_detail",
                app_id=app_id,
                screenshot_deleted="1",
            )
        )

    @app.get(
        "/admin/staging/apps/<app_id>/draft/screenshots/<screenshot_id>/content"
    )
    def admin_published_app_draft_screenshot_content(
        app_id: str, screenshot_id: str
    ) -> Response:
        try:
            result = _draft_catalog_or_error().read_screenshot(
                g.admin_identity, app_id, screenshot_id
            )
        except StagingAuthorizationError:
            abort(403)
        if result is None:
            abort(404)
        screenshot, body = result
        return send_file(
            BytesIO(body),
            mimetype=screenshot.content_type,
            download_name=screenshot.filename,
            as_attachment=False,
            conditional=True,
            etag=screenshot.sha256,
            max_age=0,
        )

    @app.post("/admin/staging/apps/<app_id>/media")
    def admin_staging_media_upload(app_id: str) -> Response | tuple[str, int]:
        catalog = _staging_catalog_or_error()
        _staged_app_or_error(app_id)
        try:
            expected_revision = _positive_revision(request.form.get("revision"))
            slot = request.form.get("slot", "")
            validate_media_slot(slot)
            uploaded_file = request.files.get("file")
            if uploaded_file is None:
                raise StagingAssetValidationError("Choose a media image to upload.")
            body = uploaded_file.stream.read(MEDIA_MAX_BYTES + 1)
            upload = validate_media_upload(
                filename=uploaded_file.filename or "",
                body=body,
                description=request.form.get("description", ""),
            )
        except (StagingAssetValidationError, ValueError) as error:
            return _render_staged_app_detail(app_id, asset_error=str(error)), 400
        try:
            catalog.upload_media(
                identity=g.admin_identity,
                app_id=app_id,
                expected_revision=expected_revision,
                slot=slot,
                upload=upload,
            )
        except StagingAuthorizationError:
            abort(403)
        except StagingNotFoundError:
            abort(404)
        except StagingConflictError as error:
            abort(409, str(error))
        return redirect(
            url_for("admin_staging_app_detail", app_id=app_id, media_updated="1")
        )

    @app.post("/admin/staging/apps/<app_id>/media/<media_id>/delete")
    def admin_staging_media_delete(app_id: str, media_id: str) -> Response:
        catalog = _staging_catalog_or_error()
        try:
            expected_revision = _positive_revision(request.form.get("revision"))
            catalog.delete_media(
                identity=g.admin_identity,
                app_id=app_id,
                media_id=media_id,
                expected_revision=expected_revision,
            )
        except StagingAuthorizationError:
            abort(403)
        except StagingNotFoundError:
            abort(404)
        except StagingConflictError as error:
            abort(409, str(error))
        except ValueError as error:
            abort(400, str(error))
        return redirect(
            url_for("admin_staging_app_detail", app_id=app_id, media_deleted="1")
        )

    @app.post("/admin/staging/apps/<app_id>/screenshots")
    def admin_staging_screenshot_upload(app_id: str) -> Response | tuple[str, int]:
        catalog = _staging_catalog_or_error()
        _staged_app_or_error(app_id)
        try:
            expected_revision = _positive_revision(request.form.get("revision"))
            uploaded_file = request.files.get("file")
            if uploaded_file is None:
                raise StagingAssetValidationError("Choose a screenshot to upload.")
            body = uploaded_file.stream.read(SCREENSHOT_MAX_BYTES + 1)
            upload = validate_screenshot_upload(
                filename=uploaded_file.filename or "", body=body
            )
        except (StagingAssetValidationError, ValueError) as error:
            return _render_staged_app_detail(app_id, asset_error=str(error)), 400
        try:
            catalog.upload_screenshot(
                identity=g.admin_identity,
                app_id=app_id,
                expected_revision=expected_revision,
                upload=upload,
            )
        except StagingAuthorizationError:
            abort(403)
        except StagingNotFoundError:
            abort(404)
        except StagingConflictError as error:
            abort(409, str(error))
        return redirect(
            url_for("admin_staging_app_detail", app_id=app_id, screenshot_added="1")
        )

    @app.post(
        "/admin/staging/apps/<app_id>/screenshots/<screenshot_id>/move"
    )
    def admin_staging_screenshot_move(app_id: str, screenshot_id: str) -> Response:
        catalog = _staging_catalog_or_error()
        try:
            expected_revision = _positive_revision(request.form.get("revision"))
            direction = request.form.get("direction", "")
            catalog.move_screenshot(
                identity=g.admin_identity,
                app_id=app_id,
                screenshot_id=screenshot_id,
                expected_revision=expected_revision,
                direction=direction,
            )
        except StagingAuthorizationError:
            abort(403)
        except StagingNotFoundError:
            abort(404)
        except StagingConflictError as error:
            abort(409, str(error))
        except ValueError as error:
            abort(400, str(error))
        return redirect(url_for("admin_staging_app_detail", app_id=app_id))

    @app.post(
        "/admin/staging/apps/<app_id>/screenshots/<screenshot_id>/delete"
    )
    def admin_staging_screenshot_delete(app_id: str, screenshot_id: str) -> Response:
        catalog = _staging_catalog_or_error()
        try:
            expected_revision = _positive_revision(request.form.get("revision"))
            catalog.delete_screenshot(
                identity=g.admin_identity,
                app_id=app_id,
                screenshot_id=screenshot_id,
                expected_revision=expected_revision,
            )
        except StagingAuthorizationError:
            abort(403)
        except StagingNotFoundError:
            abort(404)
        except StagingConflictError as error:
            abort(409, str(error))
        except ValueError as error:
            abort(400, str(error))
        return redirect(
            url_for("admin_staging_app_detail", app_id=app_id, screenshot_deleted="1")
        )

    @app.get(
        "/admin/staging/apps/<app_id>/screenshots/<screenshot_id>/content"
    )
    def admin_staging_screenshot_content(app_id: str, screenshot_id: str) -> Response:
        catalog = _staging_catalog_or_error()
        try:
            result = catalog.read_screenshot(g.admin_identity, app_id, screenshot_id)
        except StagingAuthorizationError:
            abort(403)
        if result is None:
            abort(404)
        screenshot, body = result
        return send_file(
            BytesIO(body),
            mimetype=screenshot.content_type,
            download_name=screenshot.filename,
            as_attachment=False,
            conditional=True,
            etag=screenshot.sha256,
            max_age=0,
        )

    @app.get("/admin/staging/apps/<app_id>/edit")
    def admin_staging_app_edit(app_id: str) -> str:
        app_record = _staged_app_or_error(app_id)
        if app_record.status == "PUBLISHED" and not g.admin_identity.is_administrator:
            abort(403)
        if app_record.status not in {"STAGING", "PUBLISHED"}:
            abort(409, "This app record is not directly editable")
        return _render_staging_app_form(
            values=_staged_app_form_values(app_record),
            errors={},
            form_action=url_for("admin_staging_app_update", app_id=app_record.id),
            heading=f"Edit {app_record.name}",
            submit_label="Save app",
            eyebrow="Canonical catalog",
            intro="Saving updates the canonical Firestore record atomically.",
        )

    @app.post("/admin/staging/apps/<app_id>")
    def admin_staging_app_update(app_id: str) -> Response | tuple[str, int]:
        catalog = _staging_catalog_or_error()
        form = validate_staged_app_form(request.form, allow_existing_id=True)
        errors = dict(form.errors)
        if form.values["request_id"] != app_id:
            errors["request_id"] = "The form does not match this staged app; reload it."
        try:
            expected_revision = _positive_revision(request.form.get("revision"))
        except ValueError as error:
            errors["revision"] = str(error)
            expected_revision = 0
        if form.draft is None or errors:
            return (
                _render_staging_app_form(
                    values={**form.values, "revision": request.form.get("revision", "")},
                    errors=errors,
                    form_action=url_for("admin_staging_app_update", app_id=app_id),
                    heading="Edit application",
                    submit_label="Save app",
                ),
                400,
            )
        try:
            updated = catalog.update_app(
                identity=g.admin_identity,
                app_id=app_id,
                expected_revision=expected_revision,
                draft=form.draft,
            )
        except StagingAuthorizationError:
            abort(403)
        except StagingNotFoundError:
            abort(404)
        except StagingConflictError as error:
            abort(409, str(error))
        return redirect(url_for("admin_staging_app_detail", app_id=updated.id))

    @app.post("/admin/staging/apps/<app_id>/publish")
    def admin_staging_app_publish(app_id: str) -> Response:
        catalog = _staging_catalog_or_error()
        try:
            published = catalog.publish_app(
                identity=g.admin_identity,
                app_id=app_id,
                expected_revision=_positive_revision(request.form.get("revision")),
            )
        except StagingAuthorizationError:
            abort(403)
        except StagingNotFoundError:
            abort(404)
        except StagingConflictError as error:
            abort(409, str(error))
        return redirect(
            url_for("admin_staging_app_detail", app_id=published.id, published="1")
        )

    @app.post("/admin/staging/apps/<app_id>/delete")
    def admin_staging_app_delete(app_id: str) -> Response:
        catalog = _staging_catalog_or_error()
        app_record = _staged_app_or_error(app_id)
        try:
            expected_revision = _positive_revision(request.form.get("revision"))
        except ValueError as error:
            abort(400, str(error))
        if request.form.get("confirm_name") != app_record.name:
            abort(400, "Enter the exact staged app name to confirm deletion")
        try:
            catalog.delete_app(
                identity=g.admin_identity,
                app_id=app_id,
                expected_revision=expected_revision,
            )
        except StagingAuthorizationError:
            abort(403)
        except StagingNotFoundError:
            abort(404)
        except StagingConflictError as error:
            abort(409, str(error))
        return redirect(url_for("admin_staging_apps", app_deleted="1"))

    @app.get("/admin/users")
    def admin_users() -> str:
        _require_administrator()
        directory: AdminUserDirectory | None = app.config["ADMIN_USER_DIRECTORY"]
        if directory is None:
            abort(503, "Firebase user inventory is not configured")
        return render_template(
            "admin/users.html",
            users=directory.list_users(),
            role_changes_enabled=app.config["ADMIN_USER_ROLE_MANAGER"] is not None,
            role_updated=request.args.get("role_updated") == "1",
        )

    @app.post("/admin/users/<uid>/role")
    def admin_user_role(uid: str) -> Response:
        identity = _require_administrator()
        if not uid or len(uid) > 128:
            abort(400, "Firebase user ID is invalid")
        manager: AdminUserRoleManager | None = app.config["ADMIN_USER_ROLE_MANAGER"]
        if manager is None:
            abort(503, "Firebase role management is not configured")
        requested_role = request.form.get("role")
        if not isinstance(requested_role, str):
            abort(400, "A role is required")
        try:
            manager.change_role(
                actor_uid=identity.uid,
                target_uid=uid,
                requested_role=requested_role,
            )
        except UserRoleChangeError as error:
            abort(400, str(error))
        return redirect(url_for("admin_users", role_updated="1"))

    @app.post("/admin/logout")
    def admin_logout() -> Response:
        response = make_response(redirect(url_for("admin_login")))
        _clear_session_cookie(response)
        return response

    return app


def create_cloud_app(config: Mapping[str, Any] | None = None) -> Flask:
    """Create the deployable admin from the canonical top-level collections."""

    candidate_config: dict[str, Any] = {
        "RETROSTORE_PROJECT": os.environ.get("RETROSTORE_PROJECT"),
        "RETROSTORE_CATALOG_DATABASE": os.environ.get("RETROSTORE_CATALOG_DATABASE"),
        "RETROSTORE_ASSETS_BUCKET": os.environ.get("RETROSTORE_ASSETS_BUCKET"),
        "ADMIN_FIREBASE_WEB_CONFIG": _firebase_web_config_from_environment(),
        "ADMIN_AUTHENTICATOR": None,
        "ADMIN_CATALOG": None,
        "ADMIN_PUBLISHED_APP_DRAFTS": None,
        "ADMIN_STAGING_CATALOG": None,
        "ADMIN_STAGING_OBJECT_STORE": None,
        "ADMIN_USER_DIRECTORY": None,
        "ADMIN_USER_ROLE_MANAGER": None,
    }
    if config:
        candidate_config.update(config)

    project = candidate_config.get("RETROSTORE_PROJECT")
    database = candidate_config.get("RETROSTORE_CATALOG_DATABASE")
    bucket = candidate_config.get("RETROSTORE_ASSETS_BUCKET")
    missing = [
        name
        for name, value in (
            ("RETROSTORE_PROJECT", project),
            ("RETROSTORE_CATALOG_DATABASE", database),
            ("RETROSTORE_ASSETS_BUCKET", bucket),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Cloud admin configuration is missing: {', '.join(missing)}")
    if not _valid_firebase_web_config(candidate_config["ADMIN_FIREBASE_WEB_CONFIG"]):
        raise RuntimeError("Cloud admin Firebase Web configuration is missing or malformed")
    if candidate_config["ADMIN_FIREBASE_WEB_CONFIG"]["projectId"] != project:
        raise RuntimeError("Cloud admin Firebase Web project does not match storage project")

    from google.cloud import firestore, storage

    firestore_client = firestore.Client(project=project, database=database)
    if candidate_config["ADMIN_CATALOG"] is None:
        from retrostore.canonical_catalog import CanonicalCatalogRepository

        candidate_config["ADMIN_CATALOG"] = FirestoreAdminCatalog(
            CanonicalCatalogRepository(firestore_client)
        )
    role_store = FirestoreAdminRoleStore(firestore_client)
    if candidate_config["ADMIN_STAGING_OBJECT_STORE"] is None:
        candidate_config["ADMIN_STAGING_OBJECT_STORE"] = CloudStagingObjectStore(
            storage.Client(project=project).bucket(bucket)
        )
    if candidate_config["ADMIN_STAGING_CATALOG"] is None:
        candidate_config["ADMIN_STAGING_CATALOG"] = FirestoreAdminStagingCatalog(
            firestore_client,
            candidate_config["ADMIN_STAGING_OBJECT_STORE"],
        )
    if candidate_config["ADMIN_AUTHENTICATOR"] is None:
        candidate_config["ADMIN_AUTHENTICATOR"] = FirebaseAdminAuthenticator(
            project, role_resolver=role_store
        )
    if candidate_config["ADMIN_USER_DIRECTORY"] is None:
        candidate_config["ADMIN_USER_DIRECTORY"] = FirebaseAdminUserDirectory(
            project, role_store=role_store
        )
    if candidate_config["ADMIN_USER_ROLE_MANAGER"] is None:
        candidate_config["ADMIN_USER_ROLE_MANAGER"] = AdminUserRoleManager(
            candidate_config["ADMIN_USER_DIRECTORY"], role_store
        )
    return create_app(candidate_config)


def _firebase_web_config_from_environment() -> object:
    encoded = os.environ.get("RETROSTORE_FIREBASE_WEB_CONFIG_JSON")
    if encoded:
        try:
            return json.loads(encoded)
        except json.JSONDecodeError as error:
            raise RuntimeError("RETROSTORE_FIREBASE_WEB_CONFIG_JSON is invalid JSON") from error
    values = {
        "apiKey": os.environ.get("RETROSTORE_FIREBASE_API_KEY"),
        "authDomain": os.environ.get("RETROSTORE_FIREBASE_AUTH_DOMAIN"),
        "projectId": os.environ.get("RETROSTORE_FIREBASE_PROJECT_ID"),
        "appId": os.environ.get("RETROSTORE_FIREBASE_APP_ID"),
    }
    return values if all(values.values()) else None


def _valid_firebase_web_config(value: object) -> bool:
    return (
        isinstance(value, dict)
        and all(
            isinstance(value.get(field), str) and value[field]
            for field in _FIREBASE_WEB_CONFIG_FIELDS
        )
        and _firebase_auth_origin(value) is not None
    )


def _firebase_auth_origin(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    auth_domain = value.get("authDomain")
    if not isinstance(auth_domain, str) or _DNS_NAME.fullmatch(auth_domain) is None:
        return None
    return f"https://{auth_domain.lower()}"


def _new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _render_staged_app_detail(app_id: str, *, asset_error: str | None = None) -> str:
    try:
        detail = _staging_catalog_or_error().get_app_detail(g.admin_identity, app_id)
    except StagingAuthorizationError:
        abort(403)
    except ValueError:
        abort(500, "Staged app asset metadata failed validation")
    if detail is None:
        abort(404)
    if not isinstance(detail, StagedAppDetail):
        abort(500, "Staging catalog returned an invalid app detail")
    draft_record = None
    draft_catalog: AdminPublishedAppDrafts | None = current_app.config[
        "ADMIN_PUBLISHED_APP_DRAFTS"
    ]
    if detail.app.status == "PUBLISHED" and draft_catalog is not None:
        try:
            draft_record = draft_catalog.get(g.admin_identity, detail.app.id)
        except StagingAuthorizationError:
            abort(403)
    return render_template(
        "admin/staging_app_detail.html",
        app=detail.app,
        media_by_slot={item.slot: item for item in detail.media},
        media_slots=STAGED_MEDIA_SLOTS,
        screenshots=detail.screenshots,
        asset_error=asset_error,
        media_updated=request.args.get("media_updated") == "1",
        media_deleted=request.args.get("media_deleted") == "1",
        screenshot_added=request.args.get("screenshot_added") == "1",
        screenshot_deleted=request.args.get("screenshot_deleted") == "1",
        rpk_imported=request.args.get("rpk_imported") == "1",
        draft_record=draft_record,
        draft_discarded=request.args.get("draft_discarded") == "1",
        media_upload_endpoint="admin_staging_media_upload",
        media_delete_endpoint="admin_staging_media_delete",
        screenshot_upload_endpoint="admin_staging_screenshot_upload",
        screenshot_move_endpoint="admin_staging_screenshot_move",
        screenshot_delete_endpoint="admin_staging_screenshot_delete",
        screenshot_content_endpoint="admin_staging_screenshot_content",
    )


def _render_published_app_draft_detail(
    app_id: str, *, asset_error: str | None = None
) -> str:
    try:
        detail = _draft_catalog_or_error().get_detail(g.admin_identity, app_id)
    except StagingAuthorizationError:
        abort(403)
    except ValueError:
        abort(500, "Published app draft asset metadata failed validation")
    if detail is None:
        abort(404)
    if not isinstance(detail, StagedAppDetail) or detail.app.status != "DRAFT":
        abort(500, "Published app draft catalog returned invalid detail")
    return render_template(
        "admin/staging_app_detail.html",
        app=detail.app,
        media_by_slot={item.slot: item for item in detail.media},
        media_slots=STAGED_MEDIA_SLOTS,
        screenshots=detail.screenshots,
        asset_error=asset_error,
        media_updated=request.args.get("media_updated") == "1",
        media_deleted=request.args.get("media_deleted") == "1",
        screenshot_added=request.args.get("screenshot_added") == "1",
        screenshot_deleted=request.args.get("screenshot_deleted") == "1",
        rpk_imported=False,
        draft_record=detail.app,
        draft_discarded=False,
        media_upload_endpoint="admin_published_app_draft_media_upload",
        media_delete_endpoint="admin_published_app_draft_media_delete",
        screenshot_upload_endpoint="admin_published_app_draft_screenshot_upload",
        screenshot_move_endpoint="admin_published_app_draft_screenshot_move",
        screenshot_delete_endpoint="admin_published_app_draft_screenshot_delete",
        screenshot_content_endpoint="admin_published_app_draft_screenshot_content",
    )


def _uploaded_rpk() -> ValidatedRpk:
    uploaded_file = request.files.get("file")
    if uploaded_file is None:
        raise RpkValidationError("Choose an RPK file to upload.")
    body = uploaded_file.stream.read(RPK_MAX_BYTES + 1)
    return validate_rpk(filename=uploaded_file.filename or "", body=body)


def _render_rpk_import(
    *, package: ValidatedRpk | None = None, error: str | None = None
) -> str:
    return render_template(
        "admin/staging_rpk_import.html",
        package=package,
        import_error=error,
        package_limit_mib=RPK_MAX_BYTES // (1024 * 1024),
    )


def _render_staging_app_form(
    *,
    values: Mapping[str, str],
    errors: Mapping[str, str],
    form_action: str,
    heading: str,
    submit_label: str,
    back_url: str | None = None,
    cancel_url: str | None = None,
    eyebrow: str = "Canonical catalog",
    intro: str = (
        "This saves a draft in the canonical Firestore collections. It becomes "
        "visible to the public API only after publication."
    ),
    discard_action: str | None = None,
    discard_name: str | None = None,
    draft_created: bool = False,
) -> str:
    return render_template(
        "admin/staging_app_form.html",
        values=values,
        errors=errors,
        models=STAGED_APP_MODELS,
        categories=STAGED_APP_CATEGORIES,
        form_action=form_action,
        heading=heading,
        submit_label=submit_label,
        back_url=back_url or url_for("admin_staging_apps"),
        cancel_url=cancel_url or url_for("admin_staging_apps"),
        eyebrow=eyebrow,
        intro=intro,
        discard_action=discard_action,
        discard_name=discard_name,
        draft_created=draft_created,
    )


def _staging_catalog_or_error() -> AdminStagingCatalog:
    catalog = current_app.config["ADMIN_STAGING_CATALOG"]
    if catalog is None:
        abort(503, "Staging catalog is not configured")
    return catalog


def _draft_catalog_or_error() -> AdminPublishedAppDrafts:
    catalog = current_app.config["ADMIN_PUBLISHED_APP_DRAFTS"]
    if catalog is None:
        abort(503, "Published app drafts are not configured")
    return catalog


def _published_app_draft_or_error(app_id: str) -> StagedApp:
    try:
        value = _draft_catalog_or_error().get(g.admin_identity, app_id)
    except StagingAuthorizationError:
        abort(403)
    except ValueError:
        abort(500, "Published app draft metadata failed validation")
    if value is None:
        abort(404)
    return value


def _staged_app_or_error(app_id: str) -> StagedApp:
    try:
        app_record = _staging_catalog_or_error().get_app(g.admin_identity, app_id)
    except StagingAuthorizationError:
        abort(403)
    except ValueError:
        abort(404)
    if app_record is None:
        abort(404)
    return app_record


def _staged_app_form_values(app_record: StagedApp) -> Mapping[str, str]:
    return {
        "request_id": app_record.id,
        "revision": str(app_record.revision),
        "name": app_record.name,
        "version": app_record.version,
        "description": app_record.description,
        "release_year": str(app_record.release_year),
        "model": app_record.model,
        "category": app_record.category,
        "author_name": app_record.author_name,
    }


def _positive_revision(value: object) -> int:
    try:
        revision = int(value) if isinstance(value, str) else 0
    except ValueError:
        revision = 0
    if revision < 1:
        raise ValueError("The staged app revision is invalid; reload the form")
    return revision


def _require_administrator() -> AdminIdentity:
    identity = getattr(g, "admin_identity", None)
    if not isinstance(identity, AdminIdentity) or not identity.is_administrator:
        abort(403)
    return identity


def _tokens_match(expected: object, supplied: object) -> bool:
    return (
        isinstance(expected, str)
        and isinstance(supplied, str)
        and bool(expected)
        and secrets.compare_digest(expected, supplied)
    )


def _set_csrf_cookie(response: Response, value: str, *, secure: bool) -> None:
    response.set_cookie(
        _CSRF_COOKIE,
        value,
        max_age=int(SESSION_DURATION.total_seconds()),
        secure=secure,
        httponly=True,
        samesite="Strict",
        path="/admin",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(_SESSION_COOKIE, path="/admin")


app = create_app()
