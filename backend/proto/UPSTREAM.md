# Frozen RetroStore API schema

- API artifact version: `0.2.13`
- Upstream repository: `https://github.com/shaeberling/retrostore-jvm-sdk`
- Upstream revision: `ff73858c68b1b60ad699acc496aecbc5b5b304e8`
- Upstream path: `src/main/proto/org/retrostore/client/common/proto/ApiProtos.proto`
- Retrieved: `2026-08-05`
- Upstream SHA-256: `d8921090ba2851ab1c102a447aa60066695bdf43c4d5808ff31cd090d7f5c70d`
- Vendored SHA-256: `3e1fa51a862bbc384d71c0b307ef48cbc0942d841f91967f4713ef328c1f8111`

The vendored file adds one trailing newline to the upstream file. A unified
diff confirms there are no schema-content differences.

`ApiProtos.proto` is the compatibility contract used by deployed clients. Any
future incompatible or additive API work must use an explicitly versioned
contract; it must not silently alter the behavior of `/api/*`.
