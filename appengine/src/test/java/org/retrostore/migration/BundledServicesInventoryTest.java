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

import com.google.gson.Gson;
import org.junit.Test;
import org.retrostore.data.app.AppStoreItem;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static com.google.common.truth.Truth.assertThat;
import static org.junit.Assert.assertThrows;

public final class BundledServicesInventoryTest {
  @Test
  public void hashesBlobContentsInBoundedChunksAndChecksMetadataMd5() throws Exception {
    byte[] content = "abcdefg".getBytes(StandardCharsets.UTF_8);
    FakeBlobSource blobs = new FakeBlobSource();
    blobs.add("blob-b", content, Base64.getEncoder().encodeToString(md5(content)));
    blobs.add("blob-a", new byte[0], hex(md5(new byte[0])));
    blobs.add("blob-c", new byte[0], "not-the-empty-content-md5");

    BundledServicesInventory inventory =
        new BundledServicesInventory(blobs, emptySearch(), 3);
    BundledServicesInventory.Report report =
        inventory.create(Collections.emptyList(), Instant.parse("2026-08-06T12:00:00Z"));

    assertThat(report.generatedAt).isEqualTo("2026-08-06T12:00:00Z");
    assertThat(report.safety.accessMode).isEqualTo("read-only");
    assertThat(report.safety.containsBlobKeys).isFalse();
    assertThat(report.safety.containsSearchDocumentIds).isFalse();
    assertThat(report.blobstore.contentVerified).isTrue();
    assertThat(report.blobstore.objectCount).isEqualTo(3);
    assertThat(report.blobstore.totalBytes).isEqualTo(7);
    assertThat(report.blobstore.largestBytes).isEqualTo(7);
    assertThat(report.blobstore.bytesHashed).isEqualTo(7);
    assertThat(report.blobstore.fetchRequestCount).isEqualTo(3);
    assertThat(report.blobstore.objectsWithMetadataMd5Count).isEqualTo(3);
    assertThat(report.blobstore.metadataMd5MatchCount).isEqualTo(2);
    assertThat(report.blobstore.metadataMd5MismatchCount).isEqualTo(1);
    assertThat(report.blobstore.contentAggregateSha256).hasLength(64);
    assertThat(blobs.fetches)
        .containsExactly("blob-b:0-2", "blob-b:3-5", "blob-b:6-6")
        .inOrder();
    String json = new Gson().toJson(report);
    assertThat(json).doesNotContain("blob-a");
    assertThat(json).doesNotContain("blob-b");
    assertThat(json).doesNotContain("abcdefg");
  }

  @Test
  public void rejectsIncompleteBlobReads() {
    BundledServicesInventory.BlobSource incomplete =
        new BundledServicesInventory.BlobSource() {
          @Override
          public List<BundledServicesInventory.BlobDescriptor> list() {
            return Collections.singletonList(
                new BundledServicesInventory.BlobDescriptor("blob", 3, null));
          }

          @Override
          public byte[] fetch(String key, long startInclusive, long endInclusive) {
            return new byte[0];
          }
        };
    BundledServicesInventory inventory =
        new BundledServicesInventory(incomplete, emptySearch(), 3);

    assertThrows(
        IllegalStateException.class,
        () -> inventory.create(Collections.emptyList(), Instant.EPOCH));
  }

  @Test
  public void comparesLiveSearchDocumentsWithoutExposingTheirValues() {
    List<AppStoreItem> apps = new ArrayList<>();
    apps.add(app("app-a", "Alpha", "Expected description"));
    apps.add(app("app-b", "Beta", "Missing from index"));

    List<BundledServicesInventory.SearchDocument> live = new ArrayList<>();
    live.add(document("app-a", "Alpha", "Wrong description"));
    live.add(document("secret-stale-id-9f2c", "Old", "Stale document"));
    live.add(document("secret-stale-id-9f2c", "Old duplicate", "Duplicate ID"));
    live.add(document(null, "No ID", "Unexpected"));
    BundledServicesInventory.SearchSource search =
        () -> new BundledServicesInventory.SearchSnapshot(live, 123, 456);

    BundledServicesInventory.Report report =
        new BundledServicesInventory(new FakeBlobSource(), search, 3)
            .create(apps, Instant.EPOCH);

    assertThat(report.search.indexName).isEqualTo("AppStoreItem");
    assertThat(report.search.liveDocumentCount).isEqualTo(4);
    assertThat(report.search.expectedDocumentCount).isEqualTo(2);
    assertThat(report.search.missingLiveDocumentCount).isEqualTo(1);
    assertThat(report.search.staleLiveDocumentCount).isEqualTo(1);
    assertThat(report.search.contentMismatchDocumentCount).isEqualTo(1);
    assertThat(report.search.duplicateDocumentIdCount).isEqualTo(1);
    assertThat(report.search.missingDocumentIdCount).isEqualTo(1);
    assertThat(report.search.storageUsageBytes).isEqualTo(123);
    assertThat(report.search.storageLimitBytes).isEqualTo(456);
    assertThat(report.search.aggregatesMatch).isFalse();
    assertThat(report.search.fieldTypes.get("name").get("TEXT")).isEqualTo(4);
    String json = new Gson().toJson(report);
    assertThat(json).doesNotContain("app-a");
    assertThat(json).doesNotContain("secret-stale-id-9f2c");
    assertThat(json).doesNotContain("Wrong description");
  }

  @Test
  public void searchDigestIsIndependentOfDocumentAndFieldOrder() {
    List<AppStoreItem> apps = new ArrayList<>();
    apps.add(app("app-a", "Alpha", "First"));
    apps.add(app("app-b", "Beta", "Second"));

    List<BundledServicesInventory.SearchDocument> live = new ArrayList<>();
    live.add(documentWithReversedFields("app-b", "Beta", "Second"));
    live.add(documentWithReversedFields("app-a", "Alpha", "First"));
    BundledServicesInventory.SearchSource search =
        () -> new BundledServicesInventory.SearchSnapshot(live, 0, 0);

    BundledServicesInventory.Report report =
        new BundledServicesInventory(new FakeBlobSource(), search, 3)
            .create(apps, Instant.EPOCH);

    assertThat(report.search.aggregatesMatch).isTrue();
    assertThat(report.search.liveAggregateSha256)
        .isEqualTo(report.search.expectedAggregateSha256);
    assertThat(report.search.missingLiveDocumentCount).isEqualTo(0);
    assertThat(report.search.staleLiveDocumentCount).isEqualTo(0);
    assertThat(report.search.contentMismatchDocumentCount).isEqualTo(0);
  }

  private static BundledServicesInventory.SearchSource emptySearch() {
    return () ->
        new BundledServicesInventory.SearchSnapshot(Collections.emptyList(), 0, 0);
  }

  private static AppStoreItem app(String id, String name, String description) {
    AppStoreItem app = new AppStoreItem(id);
    app.listing.name = name;
    app.listing.description = description;
    return app;
  }

  private static BundledServicesInventory.SearchDocument document(
      String id, String name, String description) {
    List<BundledServicesInventory.SearchField> fields = new ArrayList<>();
    fields.add(new BundledServicesInventory.SearchField("name", "TEXT", name, null));
    fields.add(
        new BundledServicesInventory.SearchField(
            "description", "TEXT", description, null));
    return new BundledServicesInventory.SearchDocument(id, fields);
  }

  private static BundledServicesInventory.SearchDocument documentWithReversedFields(
      String id, String name, String description) {
    List<BundledServicesInventory.SearchField> fields = new ArrayList<>();
    fields.add(
        new BundledServicesInventory.SearchField(
            "description", "TEXT", description, null));
    fields.add(new BundledServicesInventory.SearchField("name", "TEXT", name, null));
    return new BundledServicesInventory.SearchDocument(id, fields);
  }

  private static byte[] md5(byte[] value) throws Exception {
    return MessageDigest.getInstance("MD5").digest(value);
  }

  private static String hex(byte[] value) {
    StringBuilder result = new StringBuilder(value.length * 2);
    for (byte b : value) {
      result.append(String.format("%02x", b & 0xff));
    }
    return result.toString();
  }

  private static final class FakeBlobSource implements BundledServicesInventory.BlobSource {
    private final List<BundledServicesInventory.BlobDescriptor> descriptors =
        new ArrayList<>();
    private final Map<String, byte[]> contents = new HashMap<>();
    private final List<String> fetches = new ArrayList<>();

    void add(String key, byte[] content, String md5) {
      descriptors.add(new BundledServicesInventory.BlobDescriptor(key, content.length, md5));
      contents.put(key, content);
    }

    @Override
    public List<BundledServicesInventory.BlobDescriptor> list() {
      return descriptors;
    }

    @Override
    public byte[] fetch(String key, long startInclusive, long endInclusive) {
      fetches.add(key + ":" + startInclusive + "-" + endInclusive);
      byte[] source = contents.get(key);
      int length = Math.toIntExact(endInclusive - startInclusive + 1);
      byte[] result = new byte[length];
      System.arraycopy(source, Math.toIntExact(startInclusive), result, 0, length);
      return result;
    }
  }
}
