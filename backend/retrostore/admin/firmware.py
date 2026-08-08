"""Isolated staged firmware management for the administration service."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from google.cloud import firestore

from retrostore.admin.assets import StagingObjectStore, ValidatedAssetUpload
from retrostore.admin.auth import AdminIdentity

FIRMWARE_PRODUCTS: Mapping[str, str] = {
    "card": "RetroStore Card",
    "trs-io": "TRS-IO",
}
FIRMWARE_MIN_REVISION = 0
FIRMWARE_MAX_REVISION = 65_535

_FIRMWARE_COLLECTION = "firmware"
_TRACKS_COLLECTION = "firmwareStagingTracks"
_AUDIT_COLLECTION = "auditEvents"


class FirmwareAuthorizationError(PermissionError):
    """The current identity may not administer firmware."""


class FirmwareConflictError(RuntimeError):
    """A staged firmware write conflicts with another write."""


@dataclass(frozen=True, slots=True)
class StagedFirmware:
    id: str
    product: str
    revision: int
    version: int
    filename: str
    content_type: str
    object_path: str
    size: int
    sha256: str
    uploaded_by_uid: str
    uploaded_by_email: str

    @property
    def product_name(self) -> str:
        return FIRMWARE_PRODUCTS[self.product]


class AdminFirmwareStore(Protocol):
    def list_firmware(
        self, identity: AdminIdentity
    ) -> tuple[StagedFirmware, ...]: ...

    def upload_firmware(
        self,
        *,
        identity: AdminIdentity,
        product: str,
        revision: int,
        upload: ValidatedAssetUpload,
    ) -> StagedFirmware: ...

    def read_firmware(
        self, identity: AdminIdentity, firmware_id: str
    ) -> tuple[StagedFirmware, bytes] | None: ...


class FirestoreAdminFirmwareStore:
    """Append staged firmware without changing any public firmware source."""

    def __init__(self, client: firestore.Client, object_store: StagingObjectStore) -> None:
        self._client = client
        self._object_store = object_store

    def list_firmware(
        self, identity: AdminIdentity
    ) -> tuple[StagedFirmware, ...]:
        _require_administrator(identity)
        records = []
        for snapshot in self._client.collection(_FIRMWARE_COLLECTION).stream():
            value = _document_data(snapshot)
            if value.get("status") == "STAGING":
                records.append(_staged_firmware(snapshot.id, value))
        return tuple(
            sorted(
                records,
                key=lambda item: (item.product, item.revision, -item.version),
            )
        )

    def upload_firmware(
        self,
        *,
        identity: AdminIdentity,
        product: str,
        revision: int,
        upload: ValidatedAssetUpload,
    ) -> StagedFirmware:
        _require_administrator(identity)
        product = validate_firmware_product(product)
        revision = validate_firmware_revision(revision)
        if upload.content_type != "application/octet-stream":
            raise ValueError("Validated firmware content type is invalid")

        track_id = f"{product}-{revision}"
        track_reference = self._client.collection(_TRACKS_COLLECTION).document(track_id)
        expected_latest = _latest_version(track_reference.get())
        version = expected_latest + 1
        firmware_id = f"{product}-{revision}-{version}"
        object_path = (
            f"firmware-staging/{product}/{revision}/{version}/{upload.sha256}.bin"
        )
        created = self._object_store.put_verified(
            path=object_path,
            body=upload.body,
            sha256=upload.sha256,
            content_type=upload.content_type,
        )
        record = StagedFirmware(
            id=firmware_id,
            product=product,
            revision=revision,
            version=version,
            filename=upload.filename,
            content_type=upload.content_type,
            object_path=object_path,
            size=upload.size,
            sha256=upload.sha256,
            uploaded_by_uid=identity.uid,
            uploaded_by_email=identity.email,
        )
        firmware_reference = self._client.collection(_FIRMWARE_COLLECTION).document(
            firmware_id
        )
        audit_reference = self._client.collection(_AUDIT_COLLECTION).document()
        transaction = self._client.transaction()

        @firestore.transactional
        def commit_staged_firmware(transaction: Any) -> None:
            current_track = track_reference.get(transaction=transaction)
            if _latest_version(current_track) != expected_latest:
                raise FirmwareConflictError(
                    "Firmware changed concurrently; reload before trying again"
                )
            existing = firmware_reference.get(transaction=transaction)
            if existing.exists:
                raise FirmwareConflictError("Firmware version already exists")
            transaction.create(
                firmware_reference,
                {
                    "schemaVersion": 1,
                    "status": "STAGING",
                    "product": record.product,
                    "revision": record.revision,
                    "version": record.version,
                    "filename": record.filename,
                    "contentType": record.content_type,
                    "objectPath": record.object_path,
                    "size": record.size,
                    "sha256": record.sha256,
                    "uploadedByUid": record.uploaded_by_uid,
                    "uploadedByEmail": record.uploaded_by_email,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                },
            )
            transaction.set(
                track_reference,
                {
                    "schemaVersion": 1,
                    "status": "STAGING",
                    "product": record.product,
                    "revision": record.revision,
                    "latestVersion": record.version,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            transaction.create(
                audit_reference,
                {
                    "schemaVersion": 1,
                    "eventType": "STAGED_FIRMWARE_UPLOADED",
                    "status": "SUCCEEDED",
                    "actorUid": identity.uid,
                    "targetId": record.id,
                    "product": record.product,
                    "revision": record.revision,
                    "version": record.version,
                    "sha256": record.sha256,
                    "size": record.size,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                },
            )

        try:
            commit_staged_firmware(transaction)
        except Exception:
            if created:
                self._object_store.delete(object_path)
            raise
        return record

    def read_firmware(
        self, identity: AdminIdentity, firmware_id: str
    ) -> tuple[StagedFirmware, bytes] | None:
        _require_administrator(identity)
        if not _valid_firmware_id(firmware_id):
            return None
        snapshot = self._client.collection(_FIRMWARE_COLLECTION).document(
            firmware_id
        ).get()
        if not snapshot.exists:
            return None
        value = _document_data(snapshot)
        if value.get("status") != "STAGING":
            return None
        record = _staged_firmware(snapshot.id, value)
        body = self._object_store.read(record.object_path)
        if len(body) != record.size or hashlib.sha256(body).hexdigest() != record.sha256:
            raise ValueError("Staged firmware failed content verification")
        return record, body


def validate_firmware_product(value: object) -> str:
    if not isinstance(value, str) or value not in FIRMWARE_PRODUCTS:
        raise ValueError("Select a supported firmware product.")
    return value


def validate_firmware_revision(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Hardware revision must be an integer from 0 to 65535.")
    try:
        revision = int(value) if isinstance(value, (int, str)) else -1
    except ValueError:
        revision = -1
    if not FIRMWARE_MIN_REVISION <= revision <= FIRMWARE_MAX_REVISION:
        raise ValueError("Hardware revision must be an integer from 0 to 65535.")
    return revision


def _require_administrator(identity: AdminIdentity) -> None:
    if not identity.is_administrator:
        raise FirmwareAuthorizationError("Administrator access is required")


def _latest_version(snapshot: Any) -> int:
    if not snapshot.exists:
        return 0
    value = _document_data(snapshot).get("latestVersion")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("Staged firmware track has an invalid latest version")
    return value


def _staged_firmware(
    firmware_id: str, value: Mapping[str, Any]
) -> StagedFirmware:
    string_fields = {
        "product": value.get("product"),
        "filename": value.get("filename"),
        "content_type": value.get("contentType"),
        "object_path": value.get("objectPath"),
        "sha256": value.get("sha256"),
        "uploaded_by_uid": value.get("uploadedByUid"),
        "uploaded_by_email": value.get("uploadedByEmail"),
    }
    if not all(isinstance(item, str) for item in string_fields.values()):
        raise ValueError("Staged firmware document has invalid string fields")
    product = validate_firmware_product(string_fields["product"])
    revision = validate_firmware_revision(value.get("revision"))
    version = value.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("Staged firmware document has an invalid version")
    size = value.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ValueError("Staged firmware document has an invalid size")
    sha256 = string_fields["sha256"]
    if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
        raise ValueError("Staged firmware document has an invalid SHA-256")
    if string_fields["content_type"] != "application/octet-stream":
        raise ValueError("Staged firmware document has an invalid content type")
    expected_id = f"{product}-{revision}-{version}"
    expected_path = f"firmware-staging/{product}/{revision}/{version}/{sha256}.bin"
    if firmware_id != expected_id or string_fields["object_path"] != expected_path:
        raise ValueError("Staged firmware identity or object path is inconsistent")
    return StagedFirmware(
        id=firmware_id,
        revision=revision,
        version=version,
        size=size,
        **string_fields,
    )


def _valid_firmware_id(value: str) -> bool:
    if not isinstance(value, str) or len(value) > 128:
        return False
    for product in FIRMWARE_PRODUCTS:
        prefix = f"{product}-"
        if value.startswith(prefix):
            suffix = value.removeprefix(prefix).split("-")
            return len(suffix) == 2 and all(part.isdigit() for part in suffix)
    return False


def _document_data(snapshot: Any) -> Mapping[str, Any]:
    value = snapshot.to_dict()
    if not isinstance(value, Mapping):
        raise ValueError("Firestore document has no mapping data")
    return value
