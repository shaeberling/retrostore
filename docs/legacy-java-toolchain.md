# Legacy Java toolchain and dependency audit

Last audited: 2026-08-06

## Reproducible build decision

The legacy App Engine application now builds with this pinned toolchain:

| Component | Pinned version | Reason |
| --- | --- | --- |
| Temurin JDK | `21.0.12+8` | Current Java 21 maintenance release; Java 21 is the newest LTS supported by the selected Gradle line |
| Java bytecode target | `11` | Preserves the legacy application's bytecode and API baseline |
| App Engine runtime | Java 25 with EE 8 compatibility | Current supported runtime while retaining the application's `javax.servlet` contract |
| Gradle | `8.14.5` | Newest Gradle 8 maintenance release and newest release compatible with the App Engine plugin |
| App Engine Gradle plugin | `2.8.7` | Current stable release |
| App Engine Java SDK | `5.0.4` | Current stable release; `5.0.5-beta.1` was excluded as a prerelease |

The Gradle distribution and wrapper JAR match the SHA-256 values published by
Gradle. `gradle/verification-metadata.xml` also records SHA-256 values for every
resolved plugin, POM, module descriptor, and JAR. There are no dynamic `+`
versions left in the build.

The Java 21 toolchain compiles with `--release 11`. This keeps the legacy
application bytecode and Java API surface stable while the non-promoted App
Engine candidate runs on Java 25. The runtime uses EE 8 compatibility mode so
the existing Servlet 2.5 descriptor and `javax.servlet` imports remain valid.

## Compatibility findings

The original Gradle 7.4.2 wrapper cannot start under the installed Java 21 JDK;
its embedded Groovy fails on Java class-file version 65. Gradle 9.6.1 is the
current Gradle release, but it also cannot configure this application. Even the
current App Engine Gradle plugin still calls `WarPluginConvention`, which Gradle
9 removed. Gradle 8.14.5 is therefore the newest working release, not merely an
arbitrary older pin.

Two modules removed from the repository years ago were still included in
`settings.gradle`, and the root build still loaded Android Gradle Plugin 3.2.0
despite having no Android module. Both stale inputs were removed.

The `retrostore-client:0.2.13` artifact remains hosted on the project's Maven
server, whose HTTPS endpoint redirects to plain HTTP. The build now allows that
protocol only inside an exclusive repository restricted to the
`org.retrostore` group. Its JAR and Gradle module checksums are enforced by
dependency verification. Before accepting them, the current downloads were
compared with artifacts in a historical local Gradle cache and matched exactly:

| Artifact | SHA-256 |
| --- | --- |
| `retrostore-client-0.2.13.jar` | `f0ece7f0a7498a751f49f1bdd45cdae4b07de90002d4093bb91aebe1ea98669a` |
| `retrostore-client-0.2.13.module` | `4c82a1f73b4daa369b8093c31c3bcaa562e249b6fcf22d37d04c88985e8e69eb` |

Moving that artifact to an HTTPS repository or vendoring its canonical source
would remove the remaining availability and transport concern. A changed
artifact cannot enter this build unnoticed in the meantime.

## Deliberately frozen application libraries

This milestone updates the build toolchain and App Engine SDK, not the deployed
application's behavioral dependency set. Protobuf Lite 3.0.0,
`retrostore-client` 0.2.13, Guava 20.0, Objectify 5.1.22, Gson 2.8.0,
Commons FileUpload 1.3.3, and Apache HttpClient/HttpMime 4.5.3 remain exactly as
used by the legacy application. They are old, but upgrading them without Java
behavioral tests would combine reproducibility work with potentially visible
API, Objectify serialization, upload, and HTTP changes.

Dependency verification makes that frozen graph deterministic. Any security or
library modernization should be a separate reviewed change with contract and
Datastore compatibility coverage. The new Cloud Run services do not inherit
these Java dependencies.

## Validation

Run the same baseline locally and in CI:

```shell
./gradlew --no-daemon :appengine:build
```

The clean audit build succeeds and produces the WAR. The build initially had no
Java test sources. The App Engine-side Blobstore/Search inventory operation now
adds eleven focused tests, so CI executes behavioral coverage rather than
treating a successful compile as sufficient.

The App Engine plugin emits Gradle convention deprecations. Those warnings are
expected and explain why the project cannot move to Gradle 9 until Google
updates or replaces that plugin. They do not alter the Java 11 bytecode target
or application behavior.

Primary release sources:

- [Gradle release service](https://services.gradle.org/versions/all)
- [App Engine Gradle plugin metadata](https://repo1.maven.org/maven2/com/google/cloud/tools/appengine-gradle-plugin/maven-metadata.xml)
- [App Engine Java SDK metadata](https://repo1.maven.org/maven2/com/google/appengine/appengine-api-1.0-sdk/maven-metadata.xml)
- [Adoptium release API](https://api.adoptium.net/v3/assets/latest/21/hotspot?architecture=x64&image_type=jdk&os=linux&vendor=eclipse)
- [App Engine Java runtime support schedule](https://cloud.google.com/appengine/docs/standard/lifecycle/support-schedule)
- [App Engine Java runtime upgrade guide](https://cloud.google.com/appengine/docs/standard/java-gen2/upgrade-java-runtime)
