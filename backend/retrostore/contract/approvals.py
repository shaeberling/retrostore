"""Strict, expiring approvals for reviewed compatibility differences."""

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Self

_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class DifferenceApproval:
    scenario: str
    field: str
    difference_sha256: str
    reason: str
    owner: str
    expires_on: date

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if not isinstance(value, dict):
            raise ValueError("Each approval must be a JSON object")
        expected_keys = {
            "scenario",
            "field",
            "difference_sha256",
            "reason",
            "owner",
            "expires_on",
        }
        if set(value) != expected_keys:
            raise ValueError(
                f"Approval fields must be exactly {sorted(expected_keys)}; found {sorted(value)}"
            )
        strings = {key: value[key] for key in expected_keys - {"expires_on"}}
        if any(not isinstance(item, str) or not item.strip() for item in strings.values()):
            raise ValueError("Approval string fields must be non-empty")
        digest = strings["difference_sha256"]
        if _SHA256.fullmatch(digest) is None:
            raise ValueError("difference_sha256 must be a lowercase SHA-256 digest")
        try:
            expires_on = date.fromisoformat(value["expires_on"])
        except (TypeError, ValueError) as error:
            raise ValueError("expires_on must be an ISO date") from error
        return cls(
            scenario=strings["scenario"],
            field=strings["field"],
            difference_sha256=digest,
            reason=strings["reason"],
            owner=strings["owner"],
            expires_on=expires_on,
        )

    def details(self, status: str) -> dict[str, str]:
        return {
            "status": status,
            "reason": self.reason,
            "owner": self.owner,
            "expires_on": self.expires_on.isoformat(),
        }


def load_approvals(path: Path) -> tuple[DifferenceApproval, ...]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or set(value) != {"schema_version", "approvals"}:
        raise ValueError("Approval document must contain only schema_version and approvals")
    if value["schema_version"] != 1 or not isinstance(value["approvals"], list):
        raise ValueError("Unsupported approval document schema")
    approvals = tuple(DifferenceApproval.from_dict(item) for item in value["approvals"])
    keys = [(approval.scenario, approval.field) for approval in approvals]
    if len(set(keys)) != len(keys):
        raise ValueError("Approval document contains duplicate scenario/field entries")
    return approvals


def difference_fingerprint(scenario: str, field: str, difference: Any) -> str:
    canonical = json.dumps(
        {"scenario": scenario, "field": field, "difference": difference},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def evaluate_approvals(
    report: dict[str, Any],
    approvals: tuple[DifferenceApproval, ...] = (),
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Annotate a comparison report and return its strict approval gate result."""

    evaluated = copy.deepcopy(report)
    evaluation_date = today or datetime.now(UTC).date()
    approvals_by_key = {(approval.scenario, approval.field): approval for approval in approvals}
    exact_matches: set[tuple[str, str]] = set()
    approved_count = 0
    difference_count = 0

    for result in evaluated["results"]:
        scenario = result["scenario"]
        fingerprints = {}
        statuses = {}
        for field, difference in result["differences"].items():
            difference_count += 1
            key = (scenario, field)
            fingerprint = difference_fingerprint(scenario, field, difference)
            fingerprints[field] = fingerprint
            approval = approvals_by_key.get(key)
            if approval is None or approval.difference_sha256 != fingerprint:
                statuses[field] = {"status": "unapproved"}
                continue

            exact_matches.add(key)
            if approval.expires_on < evaluation_date:
                statuses[field] = approval.details("expired")
            else:
                statuses[field] = approval.details("approved")
                approved_count += 1
        result["difference_fingerprints"] = fingerprints
        result["difference_approvals"] = statuses

    expired_count = sum(approval.expires_on < evaluation_date for approval in approvals)
    stale_count = len(set(approvals_by_key) - exact_matches)
    unapproved_count = difference_count - approved_count
    passes = unapproved_count == 0 and expired_count == 0 and stale_count == 0
    evaluated["approval_gate"] = {
        "evaluated_on": evaluation_date.isoformat(),
        "passes": passes,
        "difference_fields": difference_count,
        "approved": approved_count,
        "unapproved": unapproved_count,
        "expired_approvals": expired_count,
        "stale_approvals": stale_count,
    }
    return evaluated
