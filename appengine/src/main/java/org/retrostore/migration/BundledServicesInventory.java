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
import com.google.appengine.api.search.Document;
import com.google.appengine.api.search.Field;
import com.google.appengine.api.search.GetRequest;
import com.google.appengine.api.search.Index;
import com.google.appengine.api.search.IndexSpec;
import com.google.appengine.api.search.SearchService;
import com.google.gson.annotations.SerializedName;
import org.retrostore.data.app.AppStoreItem;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;

/** Builds a sanitized, read-only inventory of App Engine bundled services. */
public final class BundledServicesInventory {
  public static final String SEARCH_INDEX_NAME = "AppStoreItem";

  private static final int SEARCH_PAGE_SIZE = 1000;
  private final BlobSource mBlobSource;
  private final SearchSource mSearchSource;
  private final int mBlobChunkSize;

  /** Creates an inventory backed by the live App Engine bundled-service APIs. */
  public static BundledServicesInventory forAppEngine(
      BlobInfoFactory blobInfoFactory,
      BlobstoreService blobstoreService,
      SearchService searchService) {
    return new BundledServicesInventory(
        new AppEngineBlobSource(blobInfoFactory, blobstoreService),
        new AppEngineSearchSource(searchService),
        BlobstoreService.MAX_BLOB_FETCH_SIZE);
  }

  BundledServicesInventory(
      BlobSource blobSource, SearchSource searchSource, int blobChunkSize) {
    mBlobSource = Objects.requireNonNull(blobSource);
    mSearchSource = Objects.requireNonNull(searchSource);
    if (blobChunkSize <= 0) {
      throw new IllegalArgumentException("Blob chunk size must be positive.");
    }
    mBlobChunkSize = blobChunkSize;
  }

  /** Reads all Blobstore objects and Search documents without mutating either service. */
  public Report create(List<AppStoreItem> apps, Instant generatedAt) {
    Objects.requireNonNull(apps);
    Objects.requireNonNull(generatedAt);

    Report report = new Report();
    report.generatedAt = generatedAt.toString();
    report.blobstore = buildBlobReport();
    report.search = buildSearchReport(apps, mSearchSource.load());
    return report;
  }

  private BlobReport buildBlobReport() {
    List<BlobDescriptor> blobs = new ArrayList<>(mBlobSource.list());
    blobs.sort(Comparator.comparing(blob -> blob.key));

    BlobReport report = new BlobReport();
    MessageDigest aggregate = newDigest("SHA-256");
    Set<String> keys = new HashSet<>();

    for (BlobDescriptor blob : blobs) {
      if (blob.size < 0) {
        throw new IllegalStateException("Blob metadata contains a negative size.");
      }
      if (!keys.add(blob.key)) {
        report.duplicateKeyCount++;
      }

      MessageDigest sha256 = newDigest("SHA-256");
      MessageDigest md5 = newDigest("MD5");
      long offset = 0;
      while (offset < blob.size) {
        long end = Math.min(blob.size - 1, offset + mBlobChunkSize - 1L);
        byte[] bytes = mBlobSource.fetch(blob.key, offset, end);
        int expectedLength = Math.toIntExact(end - offset + 1);
        if (bytes == null || bytes.length != expectedLength) {
          throw new IllegalStateException("Blob source returned an incomplete chunk.");
        }
        sha256.update(bytes);
        md5.update(bytes);
        report.fetchRequestCount++;
        report.bytesHashed += bytes.length;
        offset += bytes.length;
      }

      byte[] contentSha256 = sha256.digest();
      byte[] contentMd5 = md5.digest();
      addString(aggregate, blob.key);
      addLong(aggregate, blob.size);
      addBytes(aggregate, contentSha256);

      report.objectCount++;
      report.totalBytes += blob.size;
      report.largestBytes = Math.max(report.largestBytes, blob.size);
      if (blob.md5 != null && !blob.md5.trim().isEmpty()) {
        report.objectsWithMetadataMd5Count++;
        if (matchesMd5(blob.md5, contentMd5)) {
          report.metadataMd5MatchCount++;
        } else {
          report.metadataMd5MismatchCount++;
        }
      }
    }

    report.contentAggregateSha256 = toHex(aggregate.digest());
    return report;
  }

  private static SearchReport buildSearchReport(
      List<AppStoreItem> apps, SearchSnapshot liveSnapshot) {
    List<SearchDocument> expected = new ArrayList<>();
    for (AppStoreItem app : apps) {
      Document document =
          Document.newBuilder()
              .setId(app.id)
              .addField(Field.newBuilder().setName("name").setText(app.listing.name))
              .addField(
                  Field.newBuilder()
                      .setName("description")
                      .setText(app.listing.description))
              .build();
      expected.add(convertDocument(document));
    }

    SearchReport report = new SearchReport();
    report.liveDocumentCount = liveSnapshot.documents.size();
    report.expectedDocumentCount = expected.size();
    report.storageUsageBytes = liveSnapshot.storageUsageBytes;
    report.storageLimitBytes = liveSnapshot.storageLimitBytes;
    report.liveAggregateSha256 = aggregateDocuments(liveSnapshot.documents);
    report.expectedAggregateSha256 = aggregateDocuments(expected);
    report.aggregatesMatch = report.liveAggregateSha256.equals(report.expectedAggregateSha256);

    Map<String, byte[]> liveById = new HashMap<>();
    Map<String, byte[]> expectedById = new HashMap<>();
    Map<String, Map<String, Integer>> fieldTypes = new TreeMap<>();

    for (SearchDocument document : liveSnapshot.documents) {
      if (document.id == null || document.id.isEmpty()) {
        report.missingDocumentIdCount++;
      } else if (liveById.putIfAbsent(document.id, documentDigest(document)) != null) {
        report.duplicateDocumentIdCount++;
      }
      for (SearchField field : document.fields) {
        fieldTypes
            .computeIfAbsent(field.name, ignored -> new TreeMap<>())
            .merge(field.type, 1, Integer::sum);
      }
    }
    for (SearchDocument document : expected) {
      expectedById.put(document.id, documentDigest(document));
    }

    for (Map.Entry<String, byte[]> entry : expectedById.entrySet()) {
      byte[] liveDigest = liveById.get(entry.getKey());
      if (liveDigest == null) {
        report.missingLiveDocumentCount++;
      } else if (!MessageDigest.isEqual(liveDigest, entry.getValue())) {
        report.contentMismatchDocumentCount++;
      }
    }
    for (String liveId : liveById.keySet()) {
      if (!expectedById.containsKey(liveId)) {
        report.staleLiveDocumentCount++;
      }
    }

    for (Map.Entry<String, Map<String, Integer>> field : fieldTypes.entrySet()) {
      report.fieldTypes.put(field.getKey(), new LinkedHashMap<>(field.getValue()));
    }
    return report;
  }

  private static String aggregateDocuments(List<SearchDocument> documents) {
    List<SearchDocument> sorted = new ArrayList<>(documents);
    sorted.sort(
        Comparator.comparing(
                (SearchDocument document) -> document.id,
                Comparator.nullsFirst(Comparator.naturalOrder()))
            .thenComparing(document -> toHex(documentDigest(document))));

    MessageDigest digest = newDigest("SHA-256");
    for (SearchDocument document : sorted) {
      addBytes(digest, documentDigest(document));
    }
    return toHex(digest.digest());
  }

  private static byte[] documentDigest(SearchDocument document) {
    MessageDigest digest = newDigest("SHA-256");
    addString(digest, document.id);
    List<SearchField> fields = new ArrayList<>(document.fields);
    fields.sort(
        Comparator.comparing((SearchField field) -> field.name)
            .thenComparing(field -> field.type)
            .thenComparing(field -> field.value, Comparator.nullsFirst(Comparator.naturalOrder()))
            .thenComparing(field -> field.locale, Comparator.nullsFirst(Comparator.naturalOrder())));
    for (SearchField field : fields) {
      addString(digest, field.name);
      addString(digest, field.type);
      addString(digest, field.value);
      addString(digest, field.locale);
    }
    return digest.digest();
  }

  private static boolean matchesMd5(String metadataMd5, byte[] contentMd5) {
    String normalized = metadataMd5.trim();
    return normalized.equalsIgnoreCase(toHex(contentMd5))
        || normalized.equals(Base64.getEncoder().encodeToString(contentMd5));
  }

  private static SearchDocument convertDocument(Document document) {
    List<SearchField> fields = new ArrayList<>();
    for (Field field : document.getFields()) {
      fields.add(
          new SearchField(
              field.getName(),
              field.getType().name(),
              fieldValue(field),
              field.getLocale() == null ? null : field.getLocale().toLanguageTag()));
    }
    return new SearchDocument(document.getId(), fields);
  }

  private static String fieldValue(Field field) {
    switch (field.getType()) {
      case TEXT:
        return field.getText();
      case HTML:
        return field.getHTML();
      case ATOM:
        return field.getAtom();
      case DATE:
        return Long.toString(field.getDate().getTime());
      case NUMBER:
        return Double.toHexString(field.getNumber());
      case GEO_POINT:
        return Double.toHexString(field.getGeoPoint().getLatitude())
            + ","
            + Double.toHexString(field.getGeoPoint().getLongitude());
      case UNTOKENIZED_PREFIX:
        return field.getUntokenizedPrefix();
      case TOKENIZED_PREFIX:
        return field.getTokenizedPrefix();
      case VECTOR:
        List<String> values = new ArrayList<>();
        for (Double value : field.getVector()) {
          values.add(Double.toHexString(value));
        }
        return String.join(",", values);
      default:
        throw new IllegalStateException("Unknown Search field type.");
    }
  }

  private static MessageDigest newDigest(String algorithm) {
    try {
      return MessageDigest.getInstance(algorithm);
    } catch (NoSuchAlgorithmException e) {
      throw new IllegalStateException("Required digest algorithm is unavailable.", e);
    }
  }

  private static void addString(MessageDigest digest, String value) {
    if (value == null) {
      digest.update((byte) 0);
      return;
    }
    digest.update((byte) 1);
    addBytes(digest, value.getBytes(StandardCharsets.UTF_8));
  }

  private static void addBytes(MessageDigest digest, byte[] value) {
    addLong(digest, value.length);
    digest.update(value);
  }

  private static void addLong(MessageDigest digest, long value) {
    for (int shift = 56; shift >= 0; shift -= 8) {
      digest.update((byte) (value >>> shift));
    }
  }

  private static String toHex(byte[] value) {
    StringBuilder result = new StringBuilder(value.length * 2);
    for (byte b : value) {
      result.append(String.format(Locale.ROOT, "%02x", b & 0xff));
    }
    return result.toString();
  }

  interface BlobSource {
    List<BlobDescriptor> list();

    byte[] fetch(String key, long startInclusive, long endInclusive);
  }

  static final class BlobDescriptor {
    final String key;
    final long size;
    final String md5;

    BlobDescriptor(String key, long size, String md5) {
      this.key = Objects.requireNonNull(key);
      this.size = size;
      this.md5 = md5;
    }
  }

  interface SearchSource {
    SearchSnapshot load();
  }

  static final class SearchSnapshot {
    final List<SearchDocument> documents;
    final long storageUsageBytes;
    final long storageLimitBytes;

    SearchSnapshot(
        List<SearchDocument> documents, long storageUsageBytes, long storageLimitBytes) {
      this.documents = Collections.unmodifiableList(new ArrayList<>(documents));
      this.storageUsageBytes = storageUsageBytes;
      this.storageLimitBytes = storageLimitBytes;
    }
  }

  static final class SearchDocument {
    final String id;
    final List<SearchField> fields;

    SearchDocument(String id, List<SearchField> fields) {
      this.id = id;
      this.fields = Collections.unmodifiableList(new ArrayList<>(fields));
    }
  }

  static final class SearchField {
    final String name;
    final String type;
    final String value;
    final String locale;

    SearchField(String name, String type, String value, String locale) {
      this.name = Objects.requireNonNull(name);
      this.type = Objects.requireNonNull(type);
      this.value = value;
      this.locale = locale;
    }
  }

  /** Top-level sanitized operation result. */
  public static final class Report {
    @SerializedName("schema_version")
    public int schemaVersion = 1;

    @SerializedName("generated_at")
    public String generatedAt;

    public Safety safety = new Safety();
    public BlobReport blobstore;
    public SearchReport search;
  }

  /** Safety properties that report consumers can assert. */
  public static final class Safety {
    @SerializedName("access_mode")
    public String accessMode = "read-only";

    @SerializedName("contains_blob_keys")
    public boolean containsBlobKeys = false;

    @SerializedName("contains_search_document_ids")
    public boolean containsSearchDocumentIds = false;

    @SerializedName("contains_indexed_values")
    public boolean containsIndexedValues = false;

    @SerializedName("contains_binary_data")
    public boolean containsBinaryData = false;

    @SerializedName("digests_are_aggregate")
    public boolean digestsAreAggregate = true;
  }

  /** Aggregate Blobstore inventory; no object identifiers or contents are serialized. */
  public static final class BlobReport {
    @SerializedName("content_verified")
    public boolean contentVerified = true;

    @SerializedName("object_count")
    public int objectCount;

    @SerializedName("duplicate_key_count")
    public int duplicateKeyCount;

    @SerializedName("total_bytes")
    public long totalBytes;

    @SerializedName("largest_bytes")
    public long largestBytes;

    @SerializedName("bytes_hashed")
    public long bytesHashed;

    @SerializedName("fetch_request_count")
    public long fetchRequestCount;

    @SerializedName("objects_with_metadata_md5_count")
    public int objectsWithMetadataMd5Count;

    @SerializedName("metadata_md5_match_count")
    public int metadataMd5MatchCount;

    @SerializedName("metadata_md5_mismatch_count")
    public int metadataMd5MismatchCount;

    @SerializedName("content_aggregate_sha256")
    public String contentAggregateSha256;
  }

  /** Aggregate comparison of the live Search index with current AppStoreItem entities. */
  public static final class SearchReport {
    @SerializedName("index_name")
    public String indexName = SEARCH_INDEX_NAME;

    @SerializedName("live_document_count")
    public int liveDocumentCount;

    @SerializedName("expected_document_count")
    public int expectedDocumentCount;

    @SerializedName("missing_live_document_count")
    public int missingLiveDocumentCount;

    @SerializedName("stale_live_document_count")
    public int staleLiveDocumentCount;

    @SerializedName("content_mismatch_document_count")
    public int contentMismatchDocumentCount;

    @SerializedName("duplicate_document_id_count")
    public int duplicateDocumentIdCount;

    @SerializedName("missing_document_id_count")
    public int missingDocumentIdCount;

    @SerializedName("storage_usage_bytes")
    public long storageUsageBytes;

    @SerializedName("storage_limit_bytes")
    public long storageLimitBytes;

    @SerializedName("live_aggregate_sha256")
    public String liveAggregateSha256;

    @SerializedName("expected_aggregate_sha256")
    public String expectedAggregateSha256;

    @SerializedName("aggregates_match")
    public boolean aggregatesMatch;

    @SerializedName("field_types")
    public Map<String, Map<String, Integer>> fieldTypes = new LinkedHashMap<>();
  }

  private static final class AppEngineBlobSource implements BlobSource {
    private final BlobInfoFactory mBlobInfoFactory;
    private final BlobstoreService mBlobstoreService;

    AppEngineBlobSource(
        BlobInfoFactory blobInfoFactory, BlobstoreService blobstoreService) {
      mBlobInfoFactory = Objects.requireNonNull(blobInfoFactory);
      mBlobstoreService = Objects.requireNonNull(blobstoreService);
    }

    @Override
    public List<BlobDescriptor> list() {
      List<BlobDescriptor> result = new ArrayList<>();
      Iterator<BlobInfo> infos = mBlobInfoFactory.queryBlobInfos();
      while (infos.hasNext()) {
        BlobInfo info = infos.next();
        result.add(
            new BlobDescriptor(
                info.getBlobKey().getKeyString(), info.getSize(), info.getMd5Hash()));
      }
      return result;
    }

    @Override
    public byte[] fetch(String key, long startInclusive, long endInclusive) {
      return mBlobstoreService.fetchData(new BlobKey(key), startInclusive, endInclusive);
    }
  }

  private static final class AppEngineSearchSource implements SearchSource {
    private final Index mIndex;

    AppEngineSearchSource(SearchService searchService) {
      IndexSpec indexSpec = IndexSpec.newBuilder().setName(SEARCH_INDEX_NAME).build();
      mIndex = Objects.requireNonNull(searchService).getIndex(indexSpec);
    }

    @Override
    public SearchSnapshot load() {
      List<SearchDocument> documents = new ArrayList<>();
      String startId = null;
      while (true) {
        GetRequest.Builder request =
            GetRequest.newBuilder().setLimit(SEARCH_PAGE_SIZE).setReturningIdsOnly(false);
        if (startId != null) {
          request.setStartId(startId).setIncludeStart(false);
        }

        List<Document> page = mIndex.getRange(request).getResults();
        for (Document document : page) {
          documents.add(BundledServicesInventory.convertDocument(document));
        }
        if (page.size() < SEARCH_PAGE_SIZE) {
          break;
        }

        String nextStartId = page.get(page.size() - 1).getId();
        if (nextStartId == null || nextStartId.equals(startId)) {
          throw new IllegalStateException("Search index pagination did not advance.");
        }
        startId = nextStartId;
      }
      return new SearchSnapshot(documents, mIndex.getStorageUsage(), mIndex.getStorageLimit());
    }
  }
}
