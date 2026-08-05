"""Stable response observations and semantic protobuf normalization."""

import base64
import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Self

import httpx
from google.protobuf import json_format
from google.protobuf.message import Message

from retrostore.contract.scenarios import ContractScenario
from retrostore.contracts import ResponseKind


@dataclass(frozen=True, slots=True)
class ResponseObservation:
    scenario: str
    method: str
    request_format: str
    status_code: int
    content_type: str | None
    access_control_allow_origin: str | None
    body_length: int
    body_sha256: str
    body_base64: str
    semantic_body: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Self:
        return cls(**value)


def normalize_protobuf(message_type: type[Message], body: bytes) -> dict[str, Any]:
    message = message_type()
    message.ParseFromString(body)
    return json_format.MessageToDict(
        message,
        preserving_proto_field_name=True,
        always_print_fields_with_no_presence=True,
    )


def observe_response(
    scenario: ContractScenario, response: httpx.Response
) -> ResponseObservation:
    body = response.content
    semantic_body = None
    if scenario.method.response_kind == ResponseKind.PROTOBUF:
        if scenario.method.response_type is None:
            raise ValueError(f"{scenario.method.name} has no protobuf response type")
        semantic_body = normalize_protobuf(scenario.method.response_type, body)

    return ResponseObservation(
        scenario=scenario.name,
        method=scenario.method.name,
        request_format=scenario.request_format,
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        access_control_allow_origin=response.headers.get("access-control-allow-origin"),
        body_length=len(body),
        body_sha256=hashlib.sha256(body).hexdigest(),
        body_base64=base64.b64encode(body).decode("ascii"),
        semantic_body=semantic_body,
    )


def compare_observations(
    expected: ResponseObservation, actual: ResponseObservation
) -> dict[str, dict[str, Any]]:
    """Return differing contract fields; an empty result means parity."""

    fields = (
        "status_code",
        "content_type",
        "access_control_allow_origin",
        "body_length",
    )
    differences = {
        field: {"expected": getattr(expected, field), "actual": getattr(actual, field)}
        for field in fields
        if getattr(expected, field) != getattr(actual, field)
    }

    if expected.semantic_body is not None or actual.semantic_body is not None:
        if expected.semantic_body != actual.semantic_body:
            differences["semantic_body"] = {
                "expected": expected.semantic_body,
                "actual": actual.semantic_body,
            }
    elif expected.body_sha256 != actual.body_sha256:
        differences["body_sha256"] = {
            "expected": expected.body_sha256,
            "actual": actual.body_sha256,
        }

    return differences
