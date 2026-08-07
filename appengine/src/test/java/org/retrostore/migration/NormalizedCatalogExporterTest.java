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

import com.google.appengine.api.blobstore.BlobInfo;
import com.google.appengine.api.blobstore.BlobInfoFactory;
import com.google.appengine.api.blobstore.BlobKey;
import com.google.appengine.api.blobstore.BlobstoreService;
import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.junit.Test;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.data.app.Author;
import org.retrostore.data.app.MediaImage;
import org.retrostore.resources.ImageServiceWrapper;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.lang.reflect.Proxy;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

import static com.google.common.truth.Truth.assertThat;
import static org.junit.Assert.assertThrows;

public final class NormalizedCatalogExporterTest {
  private static final Instant EXPORTED_AT = Instant.parse("2026-08-07T09:00:00Z");

  @Test
  public void exportsDeterministicNormalizedManifestAndImmutableObjects() throws Exception {
    Fixture fixture = completeFixture(false);
    NormalizedCatalogExporter.ExportBundle bundle =
        fixture.exporter.create("trs-80", EXPORTED_AT, "full:2026-08-07T09:00:00Z");
    JsonObject manifest = new Gson().fromJson(bundle.manifestJson(), JsonObject.class);

    assertThat(manifest.get("schema_version").getAsInt()).isEqualTo(1);
    assertThat(manifest.getAsJsonObject("source").get("project_id").getAsString())
        .isEqualTo("trs-80");
    assertThat(manifest.getAsJsonObject("source").get("exported_at").getAsString())
        .isEqualTo("2026-08-07T09:00:00Z");
    assertThat(manifest.getAsJsonObject("source").get("high_water_mark").getAsString())
        .isEqualTo("full:2026-08-07T09:00:00Z");

    JsonArray apps = manifest.getAsJsonArray("apps");
    assertThat(apps).hasSize(2);
    assertThat(apps.get(0).getAsJsonObject().get("id").getAsString()).isEqualTo("app-alpha");
    assertThat(apps.get(1).getAsJsonObject().get("id").getAsString()).isEqualTo("app-beta");
    JsonObject alpha = apps.get(0).getAsJsonObject();
    assertThat(alpha.get("author_id").getAsString()).isEqualTo("7");
    assertThat(alpha.get("author_name").getAsString()).isEqualTo("Jane Doe");
    assertThat(alpha.getAsJsonArray("categories").get(0).getAsString()).isEqualTo("GAME");
    assertThat(alpha.getAsJsonObject("media_slots").getAsJsonArray("disks")).hasSize(4);
    assertThat(alpha.getAsJsonObject("media_slots").get("cassette").isJsonNull()).isTrue();
    assertThat(apps.get(1).getAsJsonObject().get("author_id").isJsonNull()).isTrue();

    JsonArray media = manifest.getAsJsonArray("media");
    assertThat(media).hasSize(2);
    assertThat(media.get(0).getAsJsonObject().get("id").getAsString()).isEqualTo("101");
    assertThat(media.get(0).getAsJsonObject().get("media_type").getAsString())
        .isEqualTo("DISK");
    assertThat(media.get(1).getAsJsonObject().get("id").getAsString()).isEqualTo("102");
    assertThat(media.get(1).getAsJsonObject().get("media_type").getAsString())
        .isEqualTo("COMMAND");

    JsonObject screenshot = manifest.getAsJsonArray("screenshots").get(0).getAsJsonObject();
    assertThat(screenshot.get("id").getAsString()).startsWith("screenshot-");
    assertThat(screenshot.get("legacy_serving_url").getAsString())
        .isEqualTo("https://legacy.example/screenshot");
    assertThat(bundle.manifestJson()).doesNotContain("secret-blob-key");
    assertThat(bundle.manifestJson()).doesNotContain("screenshot bytes");

    JsonObject reconciliation = manifest.getAsJsonObject("reconciliation");
    assertThat(reconciliation.get("app_count").getAsInt()).isEqualTo(2);
    assertThat(reconciliation.get("media_count").getAsInt()).isEqualTo(2);
    assertThat(reconciliation.get("screenshot_count").getAsInt()).isEqualTo(1);
    assertThat(reconciliation.get("object_count").getAsInt()).isEqualTo(3);
    assertThat(reconciliation.get("total_bytes").getAsLong())
        .isEqualTo("disk bytes".length() + "command bytes".length() + "screenshot bytes".length());
    assertThat(reconciliation.get("content_aggregate_sha256").getAsString()).hasLength(64);
    assertThat(reconciliation.get("content_aggregate_sha256").getAsString())
        .isEqualTo("18373239bd3707a88d731e7630ef91c26ca243815812b37b1fa583ff5706a898");

    List<String> objectPaths = bundle.getObjectPaths();
    assertThat(objectPaths).hasSize(3);
    assertThat(objectPaths).isInOrder();
    assertThat(objectPaths.get(0)).startsWith("media/app-alpha/101/");
    assertThat(objectPaths.get(1)).startsWith("media/app-alpha/102/");
    assertThat(objectPaths.get(2)).startsWith("screenshots/app-alpha/screenshot-");
    assertThat(objectPaths.toString()).doesNotContain("secret-blob-key");
    assertThat(new String(bundle.getObject(objectPaths.get(0)), StandardCharsets.UTF_8))
        .isEqualTo("disk bytes");

    Map<String, byte[]> zip = unzip(bundle);
    assertThat(zip.keySet()).containsExactlyElementsIn(prefixedEntries(bundle)).inOrder();
    assertThat(new String(zip.get("manifest.json"), StandardCharsets.UTF_8))
        .isEqualTo(bundle.manifestJson());
    for (String path : objectPaths) {
      assertThat(zip.get("objects/" + path)).isEqualTo(bundle.getObject(path));
    }
  }

  @Test
  public void outputIsIndependentOfSourceEntityOrder() {
    Fixture forward = completeFixture(false);
    Fixture reversed = completeFixture(true);

    String first =
        forward.exporter.create("trs-80", EXPORTED_AT, "cursor").manifestJson();
    String second =
        reversed.exporter.create("trs-80", EXPORTED_AT, "cursor").manifestJson();

    assertThat(first).isEqualTo(second);
  }

  @Test
  public void rejectsMissingAndOrphanedRelationshipsWithoutLeakingBlobKeys() {
    AppStoreItem app = app("app-alpha", "Alpha");
    app.listing.authorId = 999;
    app.trs80Extension.disk[0] = 888;
    app.screenshotsBlobKeys.add("secret-missing-blob");
    MediaImage orphan = media(777, "app-alpha", "orphan.cmd", "orphan");
    FakeCatalogSource source =
        new FakeCatalogSource(
            Collections.singletonList(app),
            Collections.emptyList(),
            Collections.singletonList(orphan));
    NormalizedCatalogExporter exporter =
        new NormalizedCatalogExporter(source, ignored -> null);

    NormalizedCatalogExporter.ExportValidationException error =
        assertThrows(
            NormalizedCatalogExporter.ExportValidationException.class,
            () -> exporter.create("trs-80", EXPORTED_AT, "cursor"));

    assertThat(error.getViolations())
        .containsExactly(
            "app[app-alpha] references a missing screenshot object",
            "app[app-alpha] references missing author 999",
            "app[app-alpha].media_slots.disks[0] references missing media 888",
            "media[777] is orphaned and cannot be typed safely")
        .inOrder();
    assertThat(error.getMessage()).doesNotContain("secret-missing-blob");
  }

  @Test
  public void rejectsCrossAppConflictingTypeAndInvalidMediaContent() {
    AppStoreItem app = app("app-alpha", "Alpha");
    app.trs80Extension.disk[0] = 101;
    app.trs80Extension.command = 101;
    MediaImage media = media(101, "other-app", null, "body");
    media.uploadTime = -1;
    media.data = null;
    FakeCatalogSource source =
        new FakeCatalogSource(
            Collections.singletonList(app),
            Collections.emptyList(),
            Collections.singletonList(media));
    NormalizedCatalogExporter exporter =
        new NormalizedCatalogExporter(source, ignored -> null);

    NormalizedCatalogExporter.ExportValidationException error =
        assertThrows(
            NormalizedCatalogExporter.ExportValidationException.class,
            () -> exporter.create("trs-80", EXPORTED_AT, "cursor"));

    assertThat(error.getViolations())
        .containsExactly(
            "app[app-alpha].media_slots.command references media 101 owned by app other-app",
            "app[app-alpha].media_slots.disks[0] references media 101 owned by app other-app",
            "media[101] has a negative upload time",
            "media[101] has a null filename",
            "media[101] has null data",
            "media[101] is referenced as both DISK and COMMAND")
        .inOrder();
  }

  @Test
  public void returnedObjectBytesAreDefensiveCopies() {
    Fixture fixture = completeFixture(false);
    NormalizedCatalogExporter.ExportBundle bundle =
        fixture.exporter.create("trs-80", EXPORTED_AT, "cursor");
    String path = bundle.getObjectPaths().get(0);

    byte[] first = bundle.getObject(path);
    first[0] = (byte) 'X';

    assertThat(new String(bundle.getObject(path), StandardCharsets.UTF_8))
        .isEqualTo("disk bytes");
  }

  @Test
  public void appEngineScreenshotSourceReadsBoundedChunksAndMetadata() {
    byte[] content = new byte[BlobstoreService.MAX_BLOB_FETCH_SIZE + 3];
    for (int index = 0; index < content.length; index++) {
      content[index] = (byte) (index % 251);
    }
    BlobKey key = new BlobKey("secret-key");
    BlobInfo info =
        new BlobInfo(
            key,
            "image/png",
            new Date(1_600_000_000_003L),
            "screen.png",
            content.length);
    BlobInfoFactory infoFactory =
        new BlobInfoFactory() {
          @Override
          public BlobInfo loadBlobInfo(BlobKey requested) {
            return requested.equals(key) ? info : null;
          }
        };
    List<String> ranges = new ArrayList<>();
    BlobstoreService blobstore = fakeBlobstore(content, ranges, false);
    ImageServiceWrapper images = fixedImageService("https://legacy.example/screen");

    NormalizedCatalogExporter.ScreenshotData result =
        new NormalizedCatalogExporter.AppEngineScreenshotSource(
            infoFactory, blobstore, images)
            .load("secret-key");

    assertThat(result.filename).isEqualTo("screen.png");
    assertThat(result.contentType).isEqualTo("image/png");
    assertThat(result.uploadTimeMs).isEqualTo(1_600_000_000_003L);
    assertThat(result.legacyServingUrl).isEqualTo("https://legacy.example/screen");
    assertThat(result.data).isEqualTo(content);
    assertThat(ranges)
        .containsExactly(
            "0-" + (BlobstoreService.MAX_BLOB_FETCH_SIZE - 1),
            BlobstoreService.MAX_BLOB_FETCH_SIZE + "-" + (content.length - 1))
        .inOrder();
  }

  @Test
  public void appEngineScreenshotSourceRejectsIncompleteChunk() {
    byte[] content = "abc".getBytes(StandardCharsets.UTF_8);
    BlobKey key = new BlobKey("secret-key");
    BlobInfo info =
        new BlobInfo(key, "image/png", new Date(0), "screen.png", content.length);
    BlobInfoFactory infoFactory =
        new BlobInfoFactory() {
          @Override
          public BlobInfo loadBlobInfo(BlobKey requested) {
            return info;
          }
        };
    NormalizedCatalogExporter.AppEngineScreenshotSource source =
        new NormalizedCatalogExporter.AppEngineScreenshotSource(
            infoFactory,
            fakeBlobstore(content, new ArrayList<>(), true),
            fixedImageService("https://legacy.example/screen"));

    IllegalStateException error =
        assertThrows(IllegalStateException.class, () -> source.load("secret-key"));

    assertThat(error).hasMessageThat().contains("incomplete screenshot chunk");
    assertThat(error).hasMessageThat().doesNotContain("secret-key");
  }

  private static Fixture completeFixture(boolean reversed) {
    AppStoreItem alpha = app("app-alpha", "Alpha");
    alpha.listing.authorId = 7;
    alpha.listing.publisherEmail = "publisher@example.test";
    alpha.listing.categories.add(AppStoreItem.ListingCategory.GAME);
    alpha.trs80Extension.disk[0] = 101;
    alpha.trs80Extension.command = 102;
    alpha.screenshotsBlobKeys.add("secret-blob-key");

    AppStoreItem beta = app("app-beta", "Beta");
    beta.trs80Extension.model = AppStoreItem.Model.MODEL_III;

    Author author = new Author("Jane Doe");
    author.id = 7L;
    MediaImage disk = media(101, "app-alpha", "alpha.dmk", "disk bytes");
    MediaImage command = media(102, "app-alpha", "alpha.cmd", "command bytes");

    List<AppStoreItem> apps = new ArrayList<>(Arrays.asList(alpha, beta));
    List<MediaImage> media = new ArrayList<>(Arrays.asList(disk, command));
    if (reversed) {
      Collections.reverse(apps);
      Collections.reverse(media);
    }
    FakeCatalogSource source =
        new FakeCatalogSource(apps, Collections.singletonList(author), media);
    FakeScreenshotSource screenshots = new FakeScreenshotSource();
    screenshots.values.put(
        "secret-blob-key",
        new NormalizedCatalogExporter.ScreenshotData(
            "screen.PNG",
            "image/png",
            1_600_000_000_003L,
            "https://legacy.example/screenshot",
            "screenshot bytes".getBytes(StandardCharsets.UTF_8)));
    return new Fixture(new NormalizedCatalogExporter(source, screenshots));
  }

  private static AppStoreItem app(String id, String name) {
    AppStoreItem app = new AppStoreItem(id);
    app.platform = AppStoreItem.Platform.TRS80;
    app.listing.name = name;
    app.listing.versionString = "1.0";
    app.listing.description = name + " description";
    app.listing.releaseYear = 1981;
    app.listing.firstPublishTime = 1_500_000_000_000L;
    app.listing.lastUpdateTime = 1_600_000_000_000L;
    app.trs80Extension.model = AppStoreItem.Model.MODEL_I;
    return app;
  }

  private static MediaImage media(long id, String appId, String filename, String body) {
    MediaImage media = new MediaImage();
    media.id = id;
    media.appId = appId;
    media.filename = filename;
    media.description = "Description";
    media.uploadTime = 1_600_000_000_001L;
    media.data = body.getBytes(StandardCharsets.UTF_8);
    return media;
  }

  private static Map<String, byte[]> unzip(NormalizedCatalogExporter.ExportBundle bundle)
      throws Exception {
    ByteArrayOutputStream archive = new ByteArrayOutputStream();
    bundle.writeZip(archive);
    Map<String, byte[]> result = new LinkedHashMap<>();
    ZipInputStream zip =
        new ZipInputStream(
            new ByteArrayInputStream(archive.toByteArray()), StandardCharsets.UTF_8);
    ZipEntry entry;
    while ((entry = zip.getNextEntry()) != null) {
      result.put(entry.getName(), readAll(zip));
      zip.closeEntry();
    }
    return result;
  }

  private static byte[] readAll(ZipInputStream input) throws Exception {
    ByteArrayOutputStream output = new ByteArrayOutputStream();
    byte[] buffer = new byte[128];
    int read;
    while ((read = input.read(buffer)) != -1) {
      output.write(buffer, 0, read);
    }
    return output.toByteArray();
  }

  private static List<String> prefixedEntries(
      NormalizedCatalogExporter.ExportBundle bundle) {
    List<String> result = new ArrayList<>();
    result.add("manifest.json");
    for (String path : bundle.getObjectPaths()) {
      result.add("objects/" + path);
    }
    return result;
  }

  private static BlobstoreService fakeBlobstore(
      byte[] content, List<String> ranges, boolean incomplete) {
    return (BlobstoreService)
        Proxy.newProxyInstance(
            NormalizedCatalogExporterTest.class.getClassLoader(),
            new Class<?>[] {BlobstoreService.class},
            (proxy, method, arguments) -> {
              if (!method.getName().equals("fetchData")) {
                throw new AssertionError("Unexpected Blobstore call: " + method.getName());
              }
              long start = (long) arguments[1];
              long end = (long) arguments[2];
              ranges.add(start + "-" + end);
              int length = Math.toIntExact(end - start + 1);
              if (incomplete) {
                return new byte[Math.max(0, length - 1)];
              }
              return Arrays.copyOfRange(content, Math.toIntExact(start), Math.toIntExact(end + 1));
            });
  }

  private static ImageServiceWrapper fixedImageService(String url) {
    return new ImageServiceWrapper() {
      @Override
      public Optional<String> getServingUrl(String blobKey, int imageSize) {
        return Optional.of(url);
      }

      @Override
      public Optional<String> getServingUrl(String blobKey) {
        return Optional.of(url);
      }
    };
  }

  private static final class Fixture {
    final NormalizedCatalogExporter exporter;

    Fixture(NormalizedCatalogExporter exporter) {
      this.exporter = exporter;
    }
  }

  private static final class FakeCatalogSource
      implements NormalizedCatalogExporter.CatalogSource {
    final List<AppStoreItem> apps;
    final List<Author> authors;
    final List<MediaImage> media;

    FakeCatalogSource(
        List<AppStoreItem> apps, List<Author> authors, List<MediaImage> media) {
      this.apps = apps;
      this.authors = authors;
      this.media = media;
    }

    @Override
    public List<AppStoreItem> loadApps() {
      return apps;
    }

    @Override
    public List<Author> loadAuthors() {
      return authors;
    }

    @Override
    public List<MediaImage> loadMedia() {
      return media;
    }
  }

  private static final class FakeScreenshotSource
      implements NormalizedCatalogExporter.ScreenshotSource {
    final Map<String, NormalizedCatalogExporter.ScreenshotData> values = new HashMap<>();

    @Override
    public NormalizedCatalogExporter.ScreenshotData load(String blobKey) {
      return values.get(blobKey);
    }
  }
}
