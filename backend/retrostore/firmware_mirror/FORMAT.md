# Normalized firmware mirror format

The firmware migration artifact is a deterministic ZIP containing exactly one
`manifest.json` plus each referenced payload at
`objects/firmware/{product}/{revision}/{version}/{sha256}.bin`.

Schema version 1 has this shape:

```json
{
  "schema_version": 1,
  "source": {
    "project_id": "trs-80",
    "exported_at": "2026-08-08T00:00:00Z",
    "high_water_mark": "full:2026-08-08T00:00:00Z"
  },
  "firmware": [
    {
      "id": "card-1-9",
      "product": "card",
      "revision": 1,
      "version": 9,
      "object_path": "firmware/card/1/9/{sha256}.bin",
      "size": 777424,
      "sha256": "lowercase SHA-256"
    }
  ],
  "reconciliation": {
    "firmware_count": 14,
    "object_count": 14,
    "total_bytes": 8788432,
    "content_aggregate_sha256": "lowercase SHA-256"
  }
}
```

Only `card` and `trs-io` are valid products. IDs and paths are derived from the
product, non-negative hardware revision, positive version, and content digest;
they are never taken from filenames. Records are sorted by product, revision,
and version. The aggregate hashes this UTF-8 frame for each record in order:

```text
{id}\0{object_path}\0{size}\0{sha256}\n
```

The Java exporter and Python loader pin the same cross-language fixture digest.
The loader rejects duplicate or noncanonical records, path traversal, missing,
extra, oversized, checksum-mismatched, or size-mismatched objects, and any
reconciliation difference.

Cloud persistence writes immutable payloads under `firmware/`, stages metadata
below `firmwareSnapshots/{snapshotId}/versions`, reads it back to reproduce the
manifest hash, and only then atomically moves `firmwareControl/active`. The
top-level `firmware` and `firmwareStagingTracks` collections and the
`firmware-staging/` object prefix belong to candidate admin uploads. They are
never read as the authoritative public mirror and upload does not promote them.
