"""Server-side administration boundaries."""

from retrostore.admin.auth import (
    AdminIdentity,
    AuthenticationError,
    AuthorizationError,
    FirebaseAdminAuthenticator,
    RoleAssignment,
    SessionCookie,
)
from retrostore.admin.catalog import AdminCatalogDetail, MirrorAdminCatalog
from retrostore.admin.firmware import (
    FirestoreAdminFirmwareStore,
    StagedFirmware,
)
from retrostore.admin.staging import (
    FirestoreAdminStagingCatalog,
    StagedApp,
    StagedAppDraft,
)
from retrostore.admin.users import (
    AdminUser,
    AdminUserRoleManager,
    FirebaseAdminUserDirectory,
    FirestoreAdminRoleStore,
    UserRoleChangeError,
)

__all__ = [
    "AdminCatalogDetail",
    "AdminIdentity",
    "AdminUser",
    "AdminUserRoleManager",
    "AuthenticationError",
    "AuthorizationError",
    "FirebaseAdminAuthenticator",
    "FirebaseAdminUserDirectory",
    "FirestoreAdminFirmwareStore",
    "FirestoreAdminRoleStore",
    "FirestoreAdminStagingCatalog",
    "MirrorAdminCatalog",
    "RoleAssignment",
    "SessionCookie",
    "StagedApp",
    "StagedAppDraft",
    "StagedFirmware",
    "UserRoleChangeError",
]
