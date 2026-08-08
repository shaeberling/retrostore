"""Exact public Card and TRS-IO firmware compatibility behavior."""

import re
from typing import Protocol

from flask import Response

from retrostore.firmware_mirror import FirmwareMirror

_JAVA_INTEGER = re.compile(r"[+-]?\d+")
_INTEGER_MIN = -(2**31)
_INTEGER_MAX = 2**31 - 1
_TEXT_CONTENT_TYPE = "text/plain;charset=iso-8859-1"
_BINARY_CONTENT_TYPE = "application/octet-stream"


class FirmwareStorage(Protocol):
    def latest_version(self, product: str, revision: int) -> int: ...

    def latest_firmware(self, product: str, revision: int) -> bytes | None: ...


class EmptyFirmwareStorage:
    """Explicit local-only adapter for catalog/API fixtures without firmware."""

    def latest_version(self, product: str, revision: int) -> int:
        return 0

    def latest_firmware(self, product: str, revision: int) -> bytes | None:
        return None


class MirrorFirmwareStorage:
    """Read latest firmware from one fully validated immutable snapshot."""

    def __init__(self, mirror: FirmwareMirror) -> None:
        self._mirror = mirror

    def latest_version(self, product: str, revision: int) -> int:
        record = self._mirror.latest(product, revision)
        return 0 if record is None else record.version

    def latest_firmware(self, product: str, revision: int) -> bytes | None:
        record = self._mirror.latest(product, revision)
        if record is None:
            return None
        return bytes(self._mirror.object_bytes[record.object_path])


def firmware_response(
    storage: FirmwareStorage, *, product: str, request_path: str
) -> Response:
    """Reproduce the legacy servlet's URL splitting, messages, and headers."""

    parts = request_path.rstrip("/").split("/")
    if len(parts) != 2:
        return _bad_request("Invalid URL format.")
    revision_text, operation = parts
    revision = _parse_java_integer(revision_text)
    if revision is None:
        return _bad_request(f"Revision is not a number: '{revision_text}'.")

    if operation == "version":
        return Response(
            str(storage.latest_version(product, revision)),
            status=200,
            content_type=_TEXT_CONTENT_TYPE,
        )
    if operation == "firmware":
        body = storage.latest_firmware(product, revision)
        if body is None:
            return _bad_request("Cannot find firmware data.")
        response = Response(body, status=200, content_type=_BINARY_CONTENT_TYPE)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response
    return _bad_request(f"Unknown request: '{operation}'.")


def _parse_java_integer(value: str) -> int | None:
    if _JAVA_INTEGER.fullmatch(value) is None:
        return None
    result = int(value)
    return result if _INTEGER_MIN <= result <= _INTEGER_MAX else None


def _bad_request(message: str) -> Response:
    return Response(message, status=400, content_type=_TEXT_CONTENT_TYPE)
