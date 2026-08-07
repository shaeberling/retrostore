# Approved compatibility differences

The compatibility gate defaults to zero differences. A reviewed transitional
difference can be approved only by pinning the exact scenario, field, and
reference/candidate value fingerprint emitted in a comparison report.

```json
{
  "schema_version": 1,
  "approvals": [
    {
      "scenario": "example_scenario",
      "field": "semantic_body",
      "difference_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "reason": "Temporary candidate asset URL during mirror validation",
      "owner": "named-migration-owner@example.com",
      "expires_on": "2026-08-20"
    }
  ]
}
```

Run either comparator with `--approvals /path/to/approvals.json`. When a run
finds an unapproved difference, its output still contains
`difference_fingerprints`; copy the reviewed fingerprint into the approval file
rather than calculating or weakening it by hand.

The gate fails when:

- a difference has no approval;
- reference or candidate values change, invalidating the exact fingerprint;
- an approval is expired;
- an approval is unused because its scenario/field disappeared;
- the file contains duplicate scenario/field entries; or
- any required reason, owner, expiry, or digest is missing.

Approvals never turn a difference into a match. The ordinary comparison summary
continues to report it, while `approval_gate.passes` records whether every
difference is explicitly understood and current. Cutover policy can still
require the stricter `summary.different == 0` even when a temporary parallel-run
comparison is allowed to proceed.
