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
import com.google.gson.JsonParseException;
import org.retrostore.data.app.AppStoreItem;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Independently validates normalized catalog archives and derives aggregate legacy requirements.
 *
 * <p>This class has no Objectify, Blobstore, Search, servlet, or mutation operation. A future
 * importer must supply reviewed numeric-ID allocation and screenshot-Blobstore mappings before it
 * can construct or persist legacy entities.
 */
public final class NormalizedCatalogArchiveValidator {
  private static final int MAX_ENTRIES = 100_000;
  private static final long MAX_MANIFEST_BYTES = 16L * 1024L * 1024L;
  private static final long MAX_OBJECT_BYTES = 1024L * 1024L * 1024L;
  private static final Pattern SHA256 = Pattern.compile("[0-9a-f]{64}");
  private static final Pattern SAFE_ID = Pattern.compile("[^/]+");
  private static final Gson GSON = new Gson();

  private NormalizedCatalogArchiveValidator() {}

  /** Load and reconcile a complete normalized catalog without mutating App Engine. */
  public static ValidatedCatalog load(InputStream source) throws IOException {
    Objects.requireNonNull(source);
    Map<String, byte[]> archive = readArchive(source);
    byte[] manifestBytes = archive.get("manifest.json");
    if (manifestBytes == null) {
      throw new ValidationException("Catalog archive must contain one manifest.json");
    }
    if (manifestBytes.length > MAX_MANIFEST_BYTES) {
      throw new ValidationException("Catalog archive manifest is too large");
    }

    NormalizedCatalogExporter.Manifest manifest;
    try {
      manifest = GSON.fromJson(
          new String(manifestBytes, StandardCharsets.UTF_8),
          NormalizedCatalogExporter.Manifest.class);
    } catch (JsonParseException error) {
      throw new ValidationException("Catalog archive manifest is not valid JSON", error);
    }
    validateSource(manifest);
    Map<String, NormalizedCatalogExporter.AppRecord> apps = indexApps(manifest.apps);
    Map<String, NormalizedCatalogExporter.MediaRecord> media = indexMedia(manifest.media);
    Map<String, NormalizedCatalogExporter.ScreenshotRecord> screenshots =
        indexScreenshots(manifest.screenshots);
    validateReferences(apps, media, screenshots);

    Map<String, ObjectDescriptor> descriptors = new TreeMap<>();
    for (NormalizedCatalogExporter.MediaRecord value : media.values()) {
      addDescriptor(descriptors, value.objectPath, value.size, value.sha256);
    }
    for (NormalizedCatalogExporter.ScreenshotRecord value : screenshots.values()) {
      addDescriptor(descriptors, value.objectPath, value.size, value.sha256);
    }

    Set<String> expectedEntries = new HashSet<>();
    expectedEntries.add("manifest.json");
    long totalBytes = 0;
    for (ObjectDescriptor descriptor : descriptors.values()) {
      String archivePath = "objects/" + descriptor.path;
      expectedEntries.add(archivePath);
      byte[] body = archive.get(archivePath);
      if (body == null) {
        throw new ValidationException("Catalog archive object is missing");
      }
      totalBytes += body.length;
      if (totalBytes > MAX_OBJECT_BYTES
          || body.length != descriptor.size
          || !descriptor.sha256.equals(sha256(body))) {
        throw new ValidationException("Catalog archive object failed checksum verification");
      }
    }
    if (!archive.keySet().equals(expectedEntries)) {
      throw new ValidationException("Catalog archive entries do not match its manifest");
    }
    String aggregate = contentAggregate(descriptors);
    validateReconciliation(
        manifest.reconciliation,
        apps.size(),
        media.size(),
        screenshots.size(),
        descriptors.size(),
        totalBytes,
        aggregate);
    return new ValidatedCatalog(
        manifest,
        Collections.unmodifiableMap(new TreeMap<>(apps)),
        Collections.unmodifiableMap(new TreeMap<>(media)),
        Collections.unmodifiableMap(new TreeMap<>(screenshots)),
        totalBytes,
        aggregate);
  }

  /** Compare two validated snapshots and report only aggregate legacy mutation requirements. */
  public static PreflightReport preflight(
      ValidatedCatalog baseline, ValidatedCatalog candidate) {
    Objects.requireNonNull(baseline);
    Objects.requireNonNull(candidate);
    if (!baseline.getSourceProjectId().equals(candidate.getSourceProjectId())) {
      throw new ValidationException("Catalog source projects do not match");
    }
    Changes apps = changes(baseline.apps, candidate.apps);
    Changes media = changes(baseline.media, candidate.media);
    Changes screenshots = changes(baseline.screenshots, candidate.screenshots);

    Set<String> authorAllocations = new TreeSet<>();
    Set<String> baselineAuthorIds = new HashSet<>();
    for (NormalizedCatalogExporter.AppRecord app : baseline.apps.values()) {
      if (app.authorId != null) {
        baselineAuthorIds.add(app.authorId);
      }
    }
    Set<String> numericAuthorAbsenceChecks = new TreeSet<>();
    for (String appId : union(apps.added, apps.changed)) {
      String authorId = candidate.apps.get(appId).authorId;
      if (authorId == null) {
        continue;
      }
      if (!isLegacyLongId(authorId)) {
        authorAllocations.add(authorId);
      } else if (!baselineAuthorIds.contains(authorId)) {
        numericAuthorAbsenceChecks.add(authorId);
      }
    }

    int mediaAllocations = 0;
    int numericMediaAbsenceChecks = 0;
    for (String mediaId : media.added) {
      if (isLegacyLongId(mediaId)) {
        numericMediaAbsenceChecks++;
      } else {
        mediaAllocations++;
      }
    }
    return new PreflightReport(
        apps.added.size(),
        apps.changed.size(),
        apps.removed.size(),
        media.added.size(),
        media.changed.size(),
        media.removed.size(),
        screenshots.added.size(),
        screenshots.changed.size(),
        screenshots.removed.size(),
        authorAllocations.size(),
        numericAuthorAbsenceChecks.size(),
        mediaAllocations,
        numericMediaAbsenceChecks,
        screenshots.added.size() + screenshots.changed.size());
  }

  private static void validateSource(NormalizedCatalogExporter.Manifest manifest) {
    if (manifest == null || manifest.schemaVersion != 1) {
      throw new ValidationException("Unsupported catalog archive schema");
    }
    if (manifest.source == null
        || isEmpty(manifest.source.projectId)
        || isEmpty(manifest.source.exportedAt)
        || isEmpty(manifest.source.highWaterMark)) {
      throw new ValidationException("Catalog archive source is malformed");
    }
    try {
      Instant.parse(manifest.source.exportedAt);
    } catch (DateTimeParseException error) {
      throw new ValidationException("Catalog archive export time is malformed", error);
    }
    if (manifest.apps == null || manifest.media == null || manifest.screenshots == null) {
      throw new ValidationException("Catalog archive collections are malformed");
    }
  }

  private static Map<String, NormalizedCatalogExporter.AppRecord> indexApps(
      List<NormalizedCatalogExporter.AppRecord> values) {
    Map<String, NormalizedCatalogExporter.AppRecord> result = new HashMap<>();
    for (NormalizedCatalogExporter.AppRecord value : values) {
      if (value == null
          || !isSafeId(value.id)
          || value.name == null
          || value.version == null
          || value.description == null
          || value.publisherEmail == null
          || value.authorName == null
          || value.releaseYear < 0
          || value.firstPublishedAtMs < 0
          || value.updatedAtMs < 0
          || !"TRS80".equals(value.platform)
          || value.mediaSlots == null
          || value.mediaSlots.disks == null
          || value.mediaSlots.disks.size() != 4
          || value.categories == null
          || value.screenshotIds == null) {
        throw new ValidationException("Catalog archive app is malformed");
      }
      try {
        AppStoreItem.Model.valueOf(value.model);
        for (String category : value.categories) {
          AppStoreItem.ListingCategory.valueOf(category);
        }
      } catch (IllegalArgumentException | NullPointerException error) {
        throw new ValidationException("Catalog archive app enum is malformed", error);
      }
      if (value.authorId != null && !isSafeId(value.authorId)) {
        throw new ValidationException("Catalog archive author ID is malformed");
      }
      for (String screenshotId : value.screenshotIds) {
        if (!isSafeId(screenshotId)) {
          throw new ValidationException("Catalog archive screenshot reference is malformed");
        }
      }
      for (String mediaId : mediaSlotIds(value)) {
        if (mediaId != null && !isSafeId(mediaId)) {
          throw new ValidationException("Catalog archive media reference is malformed");
        }
      }
      if (result.putIfAbsent(value.id, value) != null) {
        throw new ValidationException("Catalog archive app IDs must be unique");
      }
    }
    return result;
  }

  private static Map<String, NormalizedCatalogExporter.MediaRecord> indexMedia(
      List<NormalizedCatalogExporter.MediaRecord> values) {
    Map<String, NormalizedCatalogExporter.MediaRecord> result = new HashMap<>();
    for (NormalizedCatalogExporter.MediaRecord value : values) {
      if (value == null
          || !isSafeId(value.id)
          || !isSafeId(value.appId)
          || value.filename == null
          || value.description == null
          || value.uploadTimeMs < 0
          || !("DISK".equals(value.mediaType)
              || "CASSETTE".equals(value.mediaType)
              || "COMMAND".equals(value.mediaType)
              || "BASIC".equals(value.mediaType))) {
        throw new ValidationException("Catalog archive media is malformed");
      }
      validateDescriptor(value.objectPath, value.size, value.sha256);
      if (result.putIfAbsent(value.id, value) != null) {
        throw new ValidationException("Catalog archive media IDs must be unique");
      }
    }
    return result;
  }

  private static Map<String, NormalizedCatalogExporter.ScreenshotRecord> indexScreenshots(
      List<NormalizedCatalogExporter.ScreenshotRecord> values) {
    Map<String, NormalizedCatalogExporter.ScreenshotRecord> result = new HashMap<>();
    for (NormalizedCatalogExporter.ScreenshotRecord value : values) {
      if (value == null
          || !isSafeId(value.id)
          || !isSafeId(value.appId)
          || value.filename == null
          || value.contentType == null
          || value.uploadTimeMs < 0) {
        throw new ValidationException("Catalog archive screenshot is malformed");
      }
      validateDescriptor(value.objectPath, value.size, value.sha256);
      if (result.putIfAbsent(value.id, value) != null) {
        throw new ValidationException("Catalog archive screenshot IDs must be unique");
      }
    }
    return result;
  }

  private static void validateReferences(
      Map<String, NormalizedCatalogExporter.AppRecord> apps,
      Map<String, NormalizedCatalogExporter.MediaRecord> media,
      Map<String, NormalizedCatalogExporter.ScreenshotRecord> screenshots) {
    Set<String> referencedMedia = new HashSet<>();
    Set<String> referencedScreenshots = new HashSet<>();
    for (NormalizedCatalogExporter.AppRecord app : apps.values()) {
      List<String> mediaIds = mediaSlotIds(app);
      String[] expectedTypes = {"DISK", "DISK", "DISK", "DISK", "CASSETTE", "COMMAND", "BASIC"};
      for (int index = 0; index < mediaIds.size(); index++) {
        String mediaId = mediaIds.get(index);
        if (mediaId == null) {
          continue;
        }
        NormalizedCatalogExporter.MediaRecord value = media.get(mediaId);
        if (value == null
            || !app.id.equals(value.appId)
            || !expectedTypes[index].equals(value.mediaType)) {
          throw new ValidationException("Catalog archive media reference is inconsistent");
        }
        if (!referencedMedia.add(mediaId)) {
          throw new ValidationException("Catalog archive media is referenced more than once");
        }
      }
      for (String screenshotId : app.screenshotIds) {
        NormalizedCatalogExporter.ScreenshotRecord value = screenshots.get(screenshotId);
        if (value == null || !app.id.equals(value.appId)) {
          throw new ValidationException("Catalog archive screenshot reference is inconsistent");
        }
        if (!referencedScreenshots.add(screenshotId)) {
          throw new ValidationException("Catalog archive screenshot is referenced more than once");
        }
      }
    }
    if (!referencedMedia.equals(media.keySet())
        || !referencedScreenshots.equals(screenshots.keySet())) {
      throw new ValidationException("Catalog archive contains an unreferenced record");
    }
  }

  private static List<String> mediaSlotIds(NormalizedCatalogExporter.AppRecord app) {
    List<String> result = new ArrayList<>(app.mediaSlots.disks);
    result.add(app.mediaSlots.cassette);
    result.add(app.mediaSlots.command);
    result.add(app.mediaSlots.basic);
    return result;
  }

  private static void validateDescriptor(String path, long size, String digest) {
    if (!isNormalizedPath(path) || size < 0 || size > MAX_OBJECT_BYTES || !isSha256(digest)) {
      throw new ValidationException("Catalog archive object descriptor is malformed");
    }
  }

  private static void addDescriptor(
      Map<String, ObjectDescriptor> values, String path, long size, String digest) {
    ObjectDescriptor descriptor = new ObjectDescriptor(path, size, digest);
    ObjectDescriptor existing = values.putIfAbsent(path, descriptor);
    if (existing != null && !existing.equals(descriptor)) {
      throw new ValidationException("Catalog archive object descriptors conflict");
    }
  }

  private static void validateReconciliation(
      NormalizedCatalogExporter.Reconciliation value,
      int appCount,
      int mediaCount,
      int screenshotCount,
      int objectCount,
      long totalBytes,
      String aggregate) {
    if (value == null
        || value.appCount != appCount
        || value.mediaCount != mediaCount
        || value.screenshotCount != screenshotCount
        || value.objectCount != objectCount
        || value.totalBytes != totalBytes
        || !aggregate.equals(value.contentAggregateSha256)) {
      throw new ValidationException("Catalog archive reconciliation failed");
    }
  }

  private static Map<String, byte[]> readArchive(InputStream source) throws IOException {
    Map<String, byte[]> values = new LinkedHashMap<>();
    long objectBytes = 0;
    int entries = 0;
    ZipInputStream zip = new ZipInputStream(source, StandardCharsets.UTF_8);
    ZipEntry entry;
    while ((entry = zip.getNextEntry()) != null) {
      entries++;
      if (entries > MAX_ENTRIES) {
        throw new ValidationException("Catalog archive contains too many entries");
      }
      if (entry.isDirectory() || isEmpty(entry.getName())) {
        throw new ValidationException("Catalog archive must not contain directory entries");
      }
      long limit = "manifest.json".equals(entry.getName())
          ? MAX_MANIFEST_BYTES
          : MAX_OBJECT_BYTES;
      if (entry.getSize() > limit) {
        throw new ValidationException("Catalog archive entry exceeds its size limit");
      }
      byte[] body = readBounded(zip, limit);
      if (!"manifest.json".equals(entry.getName())) {
        objectBytes += body.length;
        if (objectBytes > MAX_OBJECT_BYTES) {
          throw new ValidationException("Catalog archive objects exceed the size limit");
        }
      }
      if (values.putIfAbsent(entry.getName(), body) != null) {
        throw new ValidationException("Catalog archive contains duplicate entries");
      }
      zip.closeEntry();
    }
    return new TreeMap<>(values);
  }

  private static byte[] readBounded(InputStream input, long limit) throws IOException {
    ByteArrayOutputStream output = new ByteArrayOutputStream();
    byte[] buffer = new byte[8192];
    long total = 0;
    int read;
    while ((read = input.read(buffer)) != -1) {
      total += read;
      if (total > limit) {
        throw new ValidationException("Catalog archive entry exceeds its size limit");
      }
      output.write(buffer, 0, read);
    }
    return output.toByteArray();
  }

  private static String contentAggregate(Map<String, ObjectDescriptor> descriptors) {
    MessageDigest aggregate = newDigest();
    for (ObjectDescriptor descriptor : descriptors.values()) {
      byte[] path = descriptor.path.getBytes(StandardCharsets.UTF_8);
      aggregate.update(ByteBuffer.allocate(Long.BYTES).putLong(path.length).array());
      aggregate.update(path);
      aggregate.update(ByteBuffer.allocate(Long.BYTES).putLong(descriptor.size).array());
      aggregate.update(hexToBytes(descriptor.sha256));
    }
    return toHex(aggregate.digest());
  }

  private static <T> Changes changes(Map<String, T> baseline, Map<String, T> candidate) {
    Set<String> added = new TreeSet<>(candidate.keySet());
    added.removeAll(baseline.keySet());
    Set<String> removed = new TreeSet<>(baseline.keySet());
    removed.removeAll(candidate.keySet());
    Set<String> changed = new TreeSet<>();
    for (String id : baseline.keySet()) {
      if (candidate.containsKey(id)
          && !GSON.toJson(baseline.get(id)).equals(GSON.toJson(candidate.get(id)))) {
        changed.add(id);
      }
    }
    return new Changes(added, changed, removed);
  }

  private static Set<String> union(Set<String> first, Set<String> second) {
    Set<String> result = new TreeSet<>(first);
    result.addAll(second);
    return result;
  }

  private static boolean isLegacyLongId(String value) {
    if (isEmpty(value) || !value.matches("[1-9][0-9]*")) {
      return false;
    }
    try {
      return Long.parseLong(value) > 0;
    } catch (NumberFormatException error) {
      return false;
    }
  }

  private static boolean isSafeId(String value) {
    return value != null
        && !value.equals(".")
        && !value.equals("..")
        && SAFE_ID.matcher(value).matches();
  }

  private static boolean isNormalizedPath(String value) {
    return value != null
        && !value.startsWith("/")
        && !value.contains("\\")
        && !value.contains("//")
        && !value.contains("/../")
        && !value.contains("/./")
        && !value.endsWith("/.")
        && !value.endsWith("/..");
  }

  private static boolean isSha256(String value) {
    return value != null && SHA256.matcher(value).matches();
  }

  private static boolean isEmpty(String value) {
    return value == null || value.isEmpty();
  }

  private static String sha256(byte[] value) {
    return toHex(newDigest().digest(value));
  }

  private static MessageDigest newDigest() {
    try {
      return MessageDigest.getInstance("SHA-256");
    } catch (NoSuchAlgorithmException error) {
      throw new AssertionError("SHA-256 is required by the Java runtime", error);
    }
  }

  private static byte[] hexToBytes(String value) {
    byte[] result = new byte[value.length() / 2];
    for (int index = 0; index < result.length; index++) {
      result[index] = (byte) Integer.parseInt(value.substring(index * 2, index * 2 + 2), 16);
    }
    return result;
  }

  private static String toHex(byte[] value) {
    StringBuilder result = new StringBuilder(value.length * 2);
    for (byte item : value) {
      result.append(String.format(Locale.US, "%02x", item & 0xff));
    }
    return result.toString();
  }

  /** Fully validated catalog evidence retained only in memory. */
  public static final class ValidatedCatalog {
    private final NormalizedCatalogExporter.Manifest manifest;
    private final Map<String, NormalizedCatalogExporter.AppRecord> apps;
    private final Map<String, NormalizedCatalogExporter.MediaRecord> media;
    private final Map<String, NormalizedCatalogExporter.ScreenshotRecord> screenshots;
    private final long totalBytes;
    private final String aggregate;

    private ValidatedCatalog(
        NormalizedCatalogExporter.Manifest manifest,
        Map<String, NormalizedCatalogExporter.AppRecord> apps,
        Map<String, NormalizedCatalogExporter.MediaRecord> media,
        Map<String, NormalizedCatalogExporter.ScreenshotRecord> screenshots,
        long totalBytes,
        String aggregate) {
      this.manifest = manifest;
      this.apps = apps;
      this.media = media;
      this.screenshots = screenshots;
      this.totalBytes = totalBytes;
      this.aggregate = aggregate;
    }

    public String getSourceProjectId() {
      return manifest.source.projectId;
    }

    public int getAppCount() {
      return apps.size();
    }

    public int getMediaCount() {
      return media.size();
    }

    public int getScreenshotCount() {
      return screenshots.size();
    }

    public long getTotalBytes() {
      return totalBytes;
    }

    public String getContentAggregateSha256() {
      return aggregate;
    }
  }

  /** Aggregate-only requirements; record IDs and catalog field values are deliberately absent. */
  public static final class PreflightReport {
    public final int appsAdded;
    public final int appsChanged;
    public final int appsRemoved;
    public final int mediaAdded;
    public final int mediaChanged;
    public final int mediaRemoved;
    public final int screenshotsAdded;
    public final int screenshotsChanged;
    public final int screenshotsRemoved;
    public final int authorIdAllocations;
    public final int numericAuthorAbsenceChecks;
    public final int mediaIdAllocations;
    public final int numericMediaAbsenceChecks;
    public final int screenshotBlobWrites;

    private PreflightReport(
        int appsAdded,
        int appsChanged,
        int appsRemoved,
        int mediaAdded,
        int mediaChanged,
        int mediaRemoved,
        int screenshotsAdded,
        int screenshotsChanged,
        int screenshotsRemoved,
        int authorIdAllocations,
        int numericAuthorAbsenceChecks,
        int mediaIdAllocations,
        int numericMediaAbsenceChecks,
        int screenshotBlobWrites) {
      this.appsAdded = appsAdded;
      this.appsChanged = appsChanged;
      this.appsRemoved = appsRemoved;
      this.mediaAdded = mediaAdded;
      this.mediaChanged = mediaChanged;
      this.mediaRemoved = mediaRemoved;
      this.screenshotsAdded = screenshotsAdded;
      this.screenshotsChanged = screenshotsChanged;
      this.screenshotsRemoved = screenshotsRemoved;
      this.authorIdAllocations = authorIdAllocations;
      this.numericAuthorAbsenceChecks = numericAuthorAbsenceChecks;
      this.mediaIdAllocations = mediaIdAllocations;
      this.numericMediaAbsenceChecks = numericMediaAbsenceChecks;
      this.screenshotBlobWrites = screenshotBlobWrites;
    }
  }

  private static final class Changes {
    final Set<String> added;
    final Set<String> changed;
    final Set<String> removed;

    Changes(Set<String> added, Set<String> changed, Set<String> removed) {
      this.added = added;
      this.changed = changed;
      this.removed = removed;
    }
  }

  private static final class ObjectDescriptor {
    final String path;
    final long size;
    final String sha256;

    ObjectDescriptor(String path, long size, String sha256) {
      this.path = path;
      this.size = size;
      this.sha256 = sha256;
    }

    @Override
    public boolean equals(Object other) {
      if (!(other instanceof ObjectDescriptor)) {
        return false;
      }
      ObjectDescriptor value = (ObjectDescriptor) other;
      return path.equals(value.path) && size == value.size && sha256.equals(value.sha256);
    }

    @Override
    public int hashCode() {
      return Objects.hash(path, size, sha256);
    }
  }

  /** Validation failure whose message never includes catalog values or record IDs. */
  public static final class ValidationException extends IllegalArgumentException {
    ValidationException(String message) {
      super(message);
    }

    ValidationException(String message, Throwable cause) {
      super(message, cause);
    }
  }
}
