/*
 * Copyright 2026, Sascha Häberling
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *       http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.retrostore.migration;

import com.google.gson.GsonBuilder;
import org.junit.Test;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Collections;
import java.util.Locale;
import java.util.Map;
import java.util.TreeMap;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import static com.google.common.truth.Truth.assertThat;
import static org.junit.Assert.assertThrows;

public final class NormalizedCatalogArchiveValidatorTest {
  @Test
  public void validatesCompleteArchivesAndDerivesAggregateLegacyRequirements()
      throws Exception {
    Fixture baseline = fixture(false);
    Fixture candidate = fixture(true);
    NormalizedCatalogArchiveValidator.ValidatedCatalog baselineCatalog =
        NormalizedCatalogArchiveValidator.load(new ByteArrayInputStream(baseline.archive()));
    NormalizedCatalogArchiveValidator.ValidatedCatalog candidateCatalog =
        NormalizedCatalogArchiveValidator.load(new ByteArrayInputStream(candidate.archive()));

    assertThat(baselineCatalog.getSourceProjectId()).isEqualTo("trs-80");
    assertThat(baselineCatalog.getAppCount()).isEqualTo(1);
    assertThat(candidateCatalog.getAppCount()).isEqualTo(2);
    assertThat(candidateCatalog.getMediaCount()).isEqualTo(1);
    assertThat(candidateCatalog.getScreenshotCount()).isEqualTo(1);
    assertThat(candidateCatalog.getTotalBytes())
        .isEqualTo("disk bytes".length() + "screen bytes".length());

    NormalizedCatalogArchiveValidator.PreflightReport plan =
        NormalizedCatalogArchiveValidator.preflight(baselineCatalog, candidateCatalog);
    assertThat(plan.appsAdded).isEqualTo(1);
    assertThat(plan.appsChanged).isEqualTo(0);
    assertThat(plan.appsRemoved).isEqualTo(0);
    assertThat(plan.mediaAdded).isEqualTo(1);
    assertThat(plan.screenshotsAdded).isEqualTo(1);
    assertThat(plan.authorIdAllocations).isEqualTo(1);
    assertThat(plan.mediaIdAllocations).isEqualTo(1);
    assertThat(plan.screenshotBlobWrites).isEqualTo(1);
  }

  @Test
  public void rejectsTamperedObjectsAndCrossAppReferencesWithoutLeakingIds()
      throws Exception {
    Fixture tamperedCandidate = fixture(true);
    tamperedCandidate.objects.put(
        tamperedCandidate.media.objectPath,
        "tamper----".getBytes(StandardCharsets.UTF_8));
    NormalizedCatalogArchiveValidator.ValidationException checksum =
        assertThrows(
            NormalizedCatalogArchiveValidator.ValidationException.class,
            () ->
                NormalizedCatalogArchiveValidator.load(
                    new ByteArrayInputStream(tamperedCandidate.archive())));
    assertThat(checksum).hasMessageThat().contains("checksum");
    assertThat(checksum).hasMessageThat().doesNotContain("media-new-id");

    Fixture crossCandidate = fixture(true);
    crossCandidate.media.appId = "app-existing";
    NormalizedCatalogArchiveValidator.ValidationException reference =
        assertThrows(
            NormalizedCatalogArchiveValidator.ValidationException.class,
            () ->
                NormalizedCatalogArchiveValidator.load(
                    new ByteArrayInputStream(crossCandidate.archive())));
    assertThat(reference).hasMessageThat().contains("reference is inconsistent");
    assertThat(reference).hasMessageThat().doesNotContain("app-new");
  }

  @Test
  public void detectsChangedAndRemovedRecordsWithoutReturningTheirIds() throws Exception {
    Fixture baseline = fixture(true);
    Fixture candidate = fixture(true);
    candidate.manifest.apps.get(0).name = "Changed private value";
    candidate.manifest.apps.remove(1);
    candidate.manifest.media.clear();
    candidate.manifest.screenshots.clear();
    candidate.objects.clear();
    reconcile(candidate);

    NormalizedCatalogArchiveValidator.PreflightReport plan =
        NormalizedCatalogArchiveValidator.preflight(
            NormalizedCatalogArchiveValidator.load(
                new ByteArrayInputStream(baseline.archive())),
            NormalizedCatalogArchiveValidator.load(
                new ByteArrayInputStream(candidate.archive())));

    assertThat(plan.appsChanged).isEqualTo(1);
    assertThat(plan.appsRemoved).isEqualTo(1);
    assertThat(plan.mediaRemoved).isEqualTo(1);
    assertThat(plan.screenshotsRemoved).isEqualTo(1);
  }

  private static Fixture fixture(boolean candidate) {
    NormalizedCatalogExporter.Manifest manifest = new NormalizedCatalogExporter.Manifest();
    manifest.source = new NormalizedCatalogExporter.Source(
        "trs-80", Instant.parse("2026-08-10T01:00:00Z").toString(), "fixture");
    manifest.apps.add(app("app-existing", "7"));
    Fixture result = new Fixture(manifest);
    if (candidate) {
      NormalizedCatalogExporter.AppRecord app = app("app-new", "author-new-id");
      app.mediaSlots.disks.set(0, "media-new-id");
      app.screenshotIds.add("screenshot-new-id");
      manifest.apps.add(app);

      byte[] disk = "disk bytes".getBytes(StandardCharsets.UTF_8);
      NormalizedCatalogExporter.MediaRecord media = new NormalizedCatalogExporter.MediaRecord();
      media.id = "media-new-id";
      media.appId = app.id;
      media.mediaType = "DISK";
      media.filename = "game.dmk";
      media.description = "Boot disk";
      media.uploadTimeMs = 1_600_000_000_001L;
      media.sha256 = sha256(disk);
      media.size = disk.length;
      media.objectPath = "media/app-new/media-new-id/" + media.sha256;
      manifest.media.add(media);
      result.media = media;
      result.objects.put(media.objectPath, disk);

      byte[] screen = "screen bytes".getBytes(StandardCharsets.UTF_8);
      NormalizedCatalogExporter.ScreenshotRecord screenshot =
          new NormalizedCatalogExporter.ScreenshotRecord();
      screenshot.id = "screenshot-new-id";
      screenshot.appId = app.id;
      screenshot.filename = "screen.png";
      screenshot.contentType = "image/png";
      screenshot.uploadTimeMs = 1_600_000_000_002L;
      screenshot.sha256 = sha256(screen);
      screenshot.size = screen.length;
      screenshot.objectPath = "screenshots/app-new/screenshot-new-id/" + screenshot.sha256 + ".png";
      manifest.screenshots.add(screenshot);
      result.objects.put(screenshot.objectPath, screen);
    }
    reconcile(result);
    return result;
  }

  private static NormalizedCatalogExporter.AppRecord app(String id, String authorId) {
    NormalizedCatalogExporter.AppRecord app = new NormalizedCatalogExporter.AppRecord();
    app.id = id;
    app.name = "App";
    app.version = "1.0";
    app.description = "Description";
    app.releaseYear = 1981;
    app.platform = "TRS80";
    app.model = "MODEL_I";
    app.categories.add("GAME");
    app.authorId = authorId;
    app.authorName = "Author";
    app.publisherEmail = "publisher@example.test";
    app.firstPublishedAtMs = 1_500_000_000_000L;
    app.updatedAtMs = 1_600_000_000_000L;
    app.mediaSlots.disks.addAll(Collections.nCopies(4, null));
    return app;
  }

  private static void reconcile(Fixture value) {
    NormalizedCatalogExporter.Reconciliation reconciliation =
        new NormalizedCatalogExporter.Reconciliation();
    reconciliation.appCount = value.manifest.apps.size();
    reconciliation.mediaCount = value.manifest.media.size();
    reconciliation.screenshotCount = value.manifest.screenshots.size();
    reconciliation.objectCount = value.objects.size();
    reconciliation.totalBytes = value.objects.values().stream().mapToLong(body -> body.length).sum();
    reconciliation.contentAggregateSha256 = aggregate(value.objects);
    value.manifest.reconciliation = reconciliation;
  }

  private static String aggregate(Map<String, byte[]> objects) {
    MessageDigest digest = newDigest();
    for (Map.Entry<String, byte[]> object : new TreeMap<>(objects).entrySet()) {
      byte[] path = object.getKey().getBytes(StandardCharsets.UTF_8);
      digest.update(ByteBuffer.allocate(Long.BYTES).putLong(path.length).array());
      digest.update(path);
      digest.update(ByteBuffer.allocate(Long.BYTES).putLong(object.getValue().length).array());
      digest.update(newDigest().digest(object.getValue()));
    }
    return toHex(digest.digest());
  }

  private static String sha256(byte[] body) {
    return toHex(newDigest().digest(body));
  }

  private static MessageDigest newDigest() {
    try {
      return MessageDigest.getInstance("SHA-256");
    } catch (Exception error) {
      throw new AssertionError(error);
    }
  }

  private static String toHex(byte[] value) {
    StringBuilder result = new StringBuilder();
    for (byte item : value) {
      result.append(String.format(Locale.US, "%02x", item & 0xff));
    }
    return result.toString();
  }

  private static final class Fixture {
    final NormalizedCatalogExporter.Manifest manifest;
    final Map<String, byte[]> objects = new TreeMap<>();
    NormalizedCatalogExporter.MediaRecord media;

    Fixture(NormalizedCatalogExporter.Manifest manifest) {
      this.manifest = manifest;
    }

    byte[] archive() throws Exception {
      ByteArrayOutputStream output = new ByteArrayOutputStream();
      ZipOutputStream zip = new ZipOutputStream(output, StandardCharsets.UTF_8);
      write(
          zip,
          "manifest.json",
          new GsonBuilder().serializeNulls().create().toJson(manifest)
              .getBytes(StandardCharsets.UTF_8));
      for (Map.Entry<String, byte[]> object : objects.entrySet()) {
        write(zip, "objects/" + object.getKey(), object.getValue());
      }
      zip.finish();
      return output.toByteArray();
    }

    private static void write(ZipOutputStream zip, String name, byte[] body) throws Exception {
      zip.putNextEntry(new ZipEntry(name));
      zip.write(body);
      zip.closeEntry();
    }
  }
}
