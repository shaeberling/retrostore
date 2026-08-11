import copy
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).parents[2]
POLICY_PATH = REPOSITORY_ROOT / "infra/data-retention/retention-policy.json"
VALIDATOR_PATH = REPOSITORY_ROOT / "infra/data-retention/validate.py"


def _validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("data_retention_validate", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _policy() -> dict[str, object]:
    return json.loads(POLICY_PATH.read_text())


def test_checked_in_retention_proposal_is_no_delete_and_unapproved() -> None:
    _validator().validate(_policy())


def test_retention_proposal_rejects_automatic_deletion() -> None:
    policy = copy.deepcopy(_policy())
    policy["proposed_policy"]["legacy_data_backups"]["automatic_deletion_enabled"] = True

    with pytest.raises(ValueError, match="must not enable automatic deletion"):
        _validator().validate(policy)


def test_retention_proposal_rejects_inferred_report_queue_retention() -> None:
    policy = copy.deepcopy(_policy())
    policy["proposed_policy"]["public_report_queue"]["retention_days"] = 30

    with pytest.raises(ValueError, match="before the report workflow decision"):
        _validator().validate(policy)


def test_retention_proposal_rejects_silent_owner_assignment() -> None:
    policy = copy.deepcopy(_policy())
    policy["required_approvals"]["data_owner"] = "unconfirmed@example.com"

    with pytest.raises(ValueError, match="assigned without confirmation"):
        _validator().validate(policy)
