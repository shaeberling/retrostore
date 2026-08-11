# Representative API fixtures

These fixtures are local compatibility data, not a production persistence
configuration.

`representative_apps.json` contains the three small protobuf responses already
reviewed in `tests/contract/golden/live-safe-baseline.json`. The loader adds
non-returned placeholders so pagination retains the observed 32-item catalog
shape.

`representative_media.pb.gz.b64` is a gzip-compressed, Base64-encoded copy of
the public legacy `fetchMediaImages` response for the reviewed fixture app. It
was captured from `https://retrostore.org` on 2026-08-06 and matched the golden
observation before being added:

- Decoded protobuf size: 101,864 bytes
- Decoded protobuf SHA-256:
  `773c39cabf958c7993e243cf1e05242ab4a061808afe9df107aa5eb0772d40e3`

The runtime loader verifies both values before exposing the fixture through the
in-memory storage adapter.
