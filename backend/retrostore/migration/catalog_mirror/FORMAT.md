# Normalized catalog mirror format

Schema version 1 is the read-only catalog shard exchanged between the legacy
Objectify exporter and the new persistence layer. It covers apps, ordered TRS-80
media slots, media metadata, and ordered screenshots. Authors are denormalized
into app records for API reads while their source IDs are retained.

The Java exporter packages the manifest and immutable bodies as:

```text
catalog-export.zip
├── manifest.json
└── objects/
    ├── media/{appId}/{mediaId}/{sha256}
    └── screenshots/{appId}/{screenshotId}/{sha256}.{ext}
```

Archive entry order and timestamps are deterministic. Legacy Blobstore keys are
used only to read source screenshots; they are replaced by stable hashed
screenshot IDs and never appear in the manifest or archive paths.

This is deliberately not yet the complete production migration bundle. Users,
firmware, active states, audit metadata, and synchronization reports will be
versioned shards with their own access and retention rules.

## Manifest

The UTF-8 JSON document has this top-level shape:

```json
{
  "schema_version": 1,
  "source": {
    "project_id": "trs-80",
    "exported_at": "2026-08-06T20:00:00Z",
    "high_water_mark": "opaque-source-position"
  },
  "apps": [],
  "media": [],
  "screenshots": [],
  "reconciliation": {
    "app_count": 0,
    "media_count": 0,
    "screenshot_count": 0,
    "object_count": 0,
    "total_bytes": 0,
    "content_aggregate_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  }
}
```

An app record keeps public API fields and migration/admin metadata separate:

```json
{
  "id": "legacy-app-id",
  "name": "Armored Patrol",
  "version": "1.0",
  "description": "...",
  "release_year": 1981,
  "platform": "TRS80",
  "model": "MODEL_I",
  "categories": ["GAME"],
  "author_id": "42",
  "author_name": "Jane Doe",
  "publisher_email": "publisher@example.com",
  "first_published_at_ms": 1500000000000,
  "updated_at_ms": 1600000000000,
  "media_slots": {
    "disks": ["1001", null, null, null],
    "cassette": null,
    "command": "1002",
    "basic": null
  },
  "screenshot_ids": ["shot-1", "shot-2"]
}
```

Media and screenshot records contain immutable object descriptors rather than
binary JSON fields. A media record adds `id`, `app_id`, `media_type`, `filename`,
`description`, and `upload_time_ms`; a screenshot adds `id`, `app_id`,
`filename`, `content_type`, `upload_time_ms`, and an optional transitional
`legacy_serving_url`. Both contain:

```json
{
  "object_path": "media/app-id/media-id/sha256",
  "size": 1234,
  "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

The reconciliation aggregate is deterministic across languages. Sort unique
objects by UTF-8 path. For each object, hash the path byte length as a signed
64-bit big-endian integer, the path bytes, the content length in the same integer
format, and the 32 raw bytes of the content SHA-256. The manifest stores the
hexadecimal SHA-256 of that complete stream.

## Enforced invariants

The Python reader and compatibility adapter currently enforce:

- schema version, supported platform/model/media enums, and four disk positions;
- unique app, media, and screenshot IDs;
- normalized relative object paths with no traversal;
- exact object sizes and SHA-256 checksums before the mirror becomes ready;
- independent count, byte-total, and aggregate object-checksum reconciliation;
- every referenced media and screenshot record exists and belongs to its app;
- every media record is used in a slot of the matching type; and
- defensive protobuf copies at the compatibility-storage boundary.

Empty legacy slots remain positional empty protobuf messages. Screenshot URL
generation is injected into the adapter so tests can retain captured App Engine
URLs while the deployed candidate uses stable RetroStore-owned asset URLs.

The local adapter eagerly loads verified objects to make fixtures deterministic.
The Cloud Storage adapter may stream/range-read media, but it must enforce the
same descriptor and reference invariants and must not report ready until the
manifest has reconciled successfully.
