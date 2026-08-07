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
import com.google.gson.GsonBuilder;
import com.google.gson.annotations.SerializedName;
import org.retrostore.data.Register;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.data.app.Author;
import org.retrostore.data.app.MediaImage;
import org.retrostore.resources.ImageServiceWrapper;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.Date;
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
import java.util.zip.ZipOutputStream;

import static com.googlecode.objectify.ObjectifyService.ofy;

/** Converts legacy Objectify catalog entities into the normalized mirror format. */
public final class NormalizedCatalogExporter {
  private static final Pattern SAFE_PATH_SEGMENT = Pattern.compile("[A-Za-z0-9._-]+");
  private static final long ZIP_ENTRY_TIMESTAMP = 315532800000L; // 1980-01-01 UTC.
  private static final Gson MANIFEST_GSON =
      new GsonBuilder().disableHtmlEscaping().serializeNulls().create();

  private final CatalogSource mCatalogSource;
  private final ScreenshotSource mScreenshotSource;

  /** Creates a read-only exporter backed by Objectify and App Engine Blobstore. */
  public static NormalizedCatalogExporter forAppEngine(
      BlobInfoFactory blobInfoFactory,
      BlobstoreService blobstoreService,
      ImageServiceWrapper imageService) {
    Register.ensureRegistered();
    return new NormalizedCatalogExporter(
        new ObjectifyCatalogSource(),
        new AppEngineScreenshotSource(blobInfoFactory, blobstoreService, imageService));
  }

  NormalizedCatalogExporter(CatalogSource catalogSource, ScreenshotSource screenshotSource) {
    mCatalogSource = Objects.requireNonNull(catalogSource);
    mScreenshotSource = Objects.requireNonNull(screenshotSource);
  }

  /**
   * Creates one deterministic full-snapshot bundle without modifying any source service.
   *
   * <p>The caller owns the high-water mark. For a full snapshot it should identify the source
   * position captured immediately before the read begins; incremental synchronization will later
   * replace this opaque value with its durable cursor.
   */
  public ExportBundle create(
      String projectId, Instant exportedAt, String highWaterMark) {
    requireNonEmpty(projectId, "projectId");
    Objects.requireNonNull(exportedAt);
    requireNonEmpty(highWaterMark, "highWaterMark");

    List<AppStoreItem> sourceApps = copyList(mCatalogSource.loadApps(), "apps");
    List<Author> sourceAuthors = copyList(mCatalogSource.loadAuthors(), "authors");
    List<MediaImage> sourceMedia = copyList(mCatalogSource.loadMedia(), "media");
    List<String> violations = new ArrayList<>();

    Map<String, AppStoreItem> appsById = indexApps(sourceApps, violations);
    Map<Long, Author> authorsById = indexAuthors(sourceAuthors, violations);
    Map<Long, MediaImage> mediaById = indexMedia(sourceMedia, violations);
    List<AppStoreItem> apps = new ArrayList<>(appsById.values());
    apps.sort(Comparator.comparing(app -> app.id));

    Manifest manifest = new Manifest();
    manifest.source = new Source(projectId, exportedAt.toString(), highWaterMark);
    Map<String, byte[]> objects = new TreeMap<>();
    Map<Long, String> mediaTypes = new HashMap<>();
    Set<Long> referencedMedia = new HashSet<>();
    Map<String, ScreenshotRecord> screenshotsById = new LinkedHashMap<>();

    for (AppStoreItem app : apps) {
      AppRecord record = convertApp(
          app,
          authorsById,
          mediaById,
          mediaTypes,
          referencedMedia,
          screenshotsById,
          objects,
          violations);
      if (record != null) {
        manifest.apps.add(record);
      }
    }

    for (MediaImage media : sourceMedia) {
      if (media != null && media.id != null && !referencedMedia.contains(media.id)) {
        violations.add("media[" + media.id + "] is orphaned and cannot be typed safely");
      }
    }

    if (!violations.isEmpty()) {
      throw new ExportValidationException(new ArrayList<>(new TreeSet<>(violations)));
    }

    List<Long> mediaIds = new ArrayList<>(referencedMedia);
    Collections.sort(mediaIds);
    for (Long mediaId : mediaIds) {
      MediaImage source = mediaById.get(mediaId);
      manifest.media.add(convertMedia(source, mediaTypes.get(mediaId), objects));
    }
    manifest.screenshots.addAll(screenshotsById.values());
    manifest.reconciliation = reconciliation(manifest, objects);
    return new ExportBundle(manifest, objects);
  }

  private AppRecord convertApp(
      AppStoreItem app,
      Map<Long, Author> authorsById,
      Map<Long, MediaImage> mediaById,
      Map<Long, String> mediaTypes,
      Set<Long> referencedMedia,
      Map<String, ScreenshotRecord> screenshotsById,
      Map<String, byte[]> objects,
      List<String> violations) {
    String context = "app[" + app.id + "]";
    if (!isSafeSegment(app.id)) {
      violations.add(context + " has an ID that is unsafe for immutable object paths");
      return null;
    }
    if (app.listing == null) {
      violations.add(context + " has no listing");
      return null;
    }
    if (app.platform == null || app.platform != AppStoreItem.Platform.TRS80) {
      violations.add(context + " has an unsupported platform");
    }
    if (app.trs80Extension == null || app.trs80Extension.model == null) {
      violations.add(context + " has no TRS-80 model");
      return null;
    }
    if (app.trs80Extension.disk == null || app.trs80Extension.disk.length != 4) {
      violations.add(context + " must have exactly four disk slots");
      return null;
    }
    if (app.screenshotsBlobKeys == null) {
      violations.add(context + " has no screenshot ordering list");
      return null;
    }
    if (app.listing.name == null
        || app.listing.versionString == null
        || app.listing.description == null) {
      violations.add(context + " has null public listing text");
      return null;
    }
    if (app.listing.releaseYear < 0
        || app.listing.firstPublishTime < 0
        || app.listing.lastUpdateTime < 0) {
      violations.add(context + " has a negative year or timestamp");
    }

    AppRecord result = new AppRecord();
    result.id = app.id;
    result.name = app.listing.name;
    result.version = app.listing.versionString;
    result.description = app.listing.description;
    result.releaseYear = app.listing.releaseYear;
    result.platform = app.platform == null ? "" : app.platform.name();
    result.model = app.trs80Extension.model.name();
    result.publisherEmail = nullToEmpty(app.listing.publisherEmail);
    result.firstPublishedAtMs = app.listing.firstPublishTime;
    result.updatedAtMs = app.listing.lastUpdateTime;

    if (app.listing.categories == null) {
      violations.add(context + " has no category set");
    } else {
      for (AppStoreItem.ListingCategory category : app.listing.categories) {
        if (category == null) {
          violations.add(context + " contains a null category");
        } else {
          result.categories.add(category.name());
        }
      }
      Collections.sort(result.categories);
    }

    if (app.listing.authorId == 0) {
      result.authorId = null;
      result.authorName = "";
    } else {
      result.authorId = Long.toString(app.listing.authorId);
      Author author = authorsById.get(app.listing.authorId);
      if (author == null) {
        violations.add(context + " references missing author " + app.listing.authorId);
        result.authorName = "";
      } else if (author.name == null) {
        violations.add("author[" + author.id + "] has a null name");
        result.authorName = "";
      } else {
        result.authorName = author.name;
      }
    }

    for (int index = 0; index < 4; index++) {
      result.mediaSlots.disks.add(
          resolveMedia(
              app,
              app.trs80Extension.disk[index],
              "DISK",
              "disks[" + index + "]",
              mediaById,
              mediaTypes,
              referencedMedia,
              violations));
    }
    result.mediaSlots.cassette =
        resolveMedia(
            app,
            app.trs80Extension.cassette,
            "CASSETTE",
            "cassette",
            mediaById,
            mediaTypes,
            referencedMedia,
            violations);
    result.mediaSlots.command =
        resolveMedia(
            app,
            app.trs80Extension.command,
            "COMMAND",
            "command",
            mediaById,
            mediaTypes,
            referencedMedia,
            violations);
    result.mediaSlots.basic =
        resolveMedia(
            app,
            app.trs80Extension.basic,
            "BASIC",
            "basic",
            mediaById,
            mediaTypes,
            referencedMedia,
            violations);

    for (String blobKey : app.screenshotsBlobKeys) {
      if (blobKey == null || blobKey.isEmpty()) {
        violations.add(context + " contains an empty screenshot Blobstore key");
        continue;
      }
      String screenshotId = screenshotId(app.id, blobKey);
      result.screenshotIds.add(screenshotId);
      if (screenshotsById.containsKey(screenshotId)) {
        continue;
      }
      ScreenshotData screenshot = mScreenshotSource.load(blobKey);
      if (screenshot == null) {
        violations.add(context + " references a missing screenshot object");
        continue;
      }
      if (screenshot.data == null) {
        violations.add(context + " has a screenshot with null data");
        continue;
      }
      if (screenshot.uploadTimeMs < 0) {
        violations.add(context + " has a screenshot with a negative upload time");
      }
      screenshotsById.put(
          screenshotId,
          convertScreenshot(app.id, screenshotId, screenshot, objects));
    }
    return result;
  }

  private static String resolveMedia(
      AppStoreItem app,
      long mediaId,
      String mediaType,
      String slot,
      Map<Long, MediaImage> mediaById,
      Map<Long, String> mediaTypes,
      Set<Long> referencedMedia,
      List<String> violations) {
    if (mediaId == 0) {
      return null;
    }
    String context = "app[" + app.id + "].media_slots." + slot;
    if (mediaId < 0) {
      violations.add(context + " contains negative media ID " + mediaId);
      return Long.toString(mediaId);
    }
    referencedMedia.add(mediaId);
    MediaImage media = mediaById.get(mediaId);
    if (media == null) {
      violations.add(context + " references missing media " + mediaId);
      return Long.toString(mediaId);
    }
    if (media.appId == null) {
      violations.add("media[" + mediaId + "] has no owning app ID");
    } else if (!app.id.equals(media.appId)) {
      violations.add(
          context + " references media " + mediaId + " owned by app " + media.appId);
    }
    if (media.filename == null) {
      violations.add("media[" + mediaId + "] has a null filename");
    }
    if (media.data == null) {
      violations.add("media[" + mediaId + "] has null data");
    }
    if (media.uploadTime < 0) {
      violations.add("media[" + mediaId + "] has a negative upload time");
    }
    String existingType = mediaTypes.putIfAbsent(mediaId, mediaType);
    if (existingType != null && !existingType.equals(mediaType)) {
      violations.add(
          "media[" + mediaId + "] is referenced as both " + existingType + " and " + mediaType);
    }
    return Long.toString(mediaId);
  }

  private static MediaRecord convertMedia(
      MediaImage media, String mediaType, Map<String, byte[]> objects) {
    if (media.data == null) {
      throw new IllegalStateException("Referenced media " + media.id + " has null data");
    }
    if (media.uploadTime < 0) {
      throw new IllegalStateException("Referenced media " + media.id + " has negative upload time");
    }
    byte[] body = Arrays.copyOf(media.data, media.data.length);
    String digest = sha256(body);
    String path = "media/" + media.appId + "/" + media.id + "/" + digest;
    putObject(objects, path, body);

    MediaRecord result = new MediaRecord();
    result.id = Long.toString(media.id);
    result.appId = media.appId;
    result.mediaType = mediaType;
    result.filename = nullToEmpty(media.filename);
    result.description = nullToEmpty(media.description);
    result.uploadTimeMs = media.uploadTime;
    result.objectPath = path;
    result.size = body.length;
    result.sha256 = digest;
    return result;
  }

  private static ScreenshotRecord convertScreenshot(
      String appId,
      String screenshotId,
      ScreenshotData source,
      Map<String, byte[]> objects) {
    byte[] body = Arrays.copyOf(source.data, source.data.length);
    String digest = sha256(body);
    String extension = safeExtension(source.filename);
    String path =
        "screenshots/" + appId + "/" + screenshotId + "/" + digest + extension;
    putObject(objects, path, body);

    ScreenshotRecord result = new ScreenshotRecord();
    result.id = screenshotId;
    result.appId = appId;
    result.filename = nullToEmpty(source.filename);
    result.contentType = nullToEmpty(source.contentType);
    result.uploadTimeMs = source.uploadTimeMs;
    result.legacyServingUrl = source.legacyServingUrl;
    result.objectPath = path;
    result.size = body.length;
    result.sha256 = digest;
    return result;
  }

  private static Reconciliation reconciliation(
      Manifest manifest, Map<String, byte[]> objects) {
    Reconciliation result = new Reconciliation();
    result.appCount = manifest.apps.size();
    result.mediaCount = manifest.media.size();
    result.screenshotCount = manifest.screenshots.size();
    result.objectCount = objects.size();

    MessageDigest aggregate = newDigest();
    for (Map.Entry<String, byte[]> object : objects.entrySet()) {
      byte[] path = object.getKey().getBytes(StandardCharsets.UTF_8);
      byte[] digest = hexToBytes(sha256(object.getValue()));
      aggregate.update(ByteBuffer.allocate(Long.BYTES).putLong(path.length).array());
      aggregate.update(path);
      aggregate.update(ByteBuffer.allocate(Long.BYTES).putLong(object.getValue().length).array());
      aggregate.update(digest);
      result.totalBytes += object.getValue().length;
    }
    result.contentAggregateSha256 = toHex(aggregate.digest());
    return result;
  }

  private static Map<String, AppStoreItem> indexApps(
      List<AppStoreItem> apps, List<String> violations) {
    Map<String, AppStoreItem> result = new HashMap<>();
    for (AppStoreItem app : apps) {
      if (app == null || app.id == null || app.id.isEmpty()) {
        violations.add("catalog contains an app with no ID");
      } else if (result.putIfAbsent(app.id, app) != null) {
        violations.add("catalog contains duplicate app ID " + app.id);
      }
    }
    return result;
  }

  private static Map<Long, Author> indexAuthors(
      List<Author> authors, List<String> violations) {
    Map<Long, Author> result = new HashMap<>();
    for (Author author : authors) {
      if (author == null || author.id == null) {
        violations.add("catalog contains an author with no ID");
      } else if (result.putIfAbsent(author.id, author) != null) {
        violations.add("catalog contains duplicate author ID " + author.id);
      }
    }
    return result;
  }

  private static Map<Long, MediaImage> indexMedia(
      List<MediaImage> media, List<String> violations) {
    Map<Long, MediaImage> result = new HashMap<>();
    for (MediaImage image : media) {
      if (image == null || image.id == null) {
        violations.add("catalog contains media with no ID");
      } else if (result.putIfAbsent(image.id, image) != null) {
        violations.add("catalog contains duplicate media ID " + image.id);
      }
    }
    return result;
  }

  private static <T> List<T> copyList(List<T> values, String name) {
    if (values == null) {
      throw new IllegalStateException("Catalog source returned null " + name);
    }
    return new ArrayList<>(values);
  }

  private static void putObject(Map<String, byte[]> objects, String path, byte[] body) {
    byte[] previous = objects.putIfAbsent(path, body);
    if (previous != null && !Arrays.equals(previous, body)) {
      throw new IllegalStateException("Immutable object path collision: " + path);
    }
  }

  private static String screenshotId(String appId, String blobKey) {
    MessageDigest digest = newDigest();
    digest.update(appId.getBytes(StandardCharsets.UTF_8));
    digest.update((byte) 0);
    digest.update(blobKey.getBytes(StandardCharsets.UTF_8));
    return "screenshot-" + toHex(digest.digest());
  }

  private static String safeExtension(String filename) {
    if (filename == null) {
      return "";
    }
    int dot = filename.lastIndexOf('.');
    if (dot < 0 || dot == filename.length() - 1) {
      return "";
    }
    String extension = filename.substring(dot + 1).toLowerCase(Locale.US);
    if (!extension.matches("[a-z0-9]{1,10}")) {
      return "";
    }
    return "." + extension;
  }

  private static boolean isSafeSegment(String value) {
    return value != null && SAFE_PATH_SEGMENT.matcher(value).matches();
  }

  private static String nullToEmpty(String value) {
    return value == null ? "" : value;
  }

  private static void requireNonEmpty(String value, String name) {
    if (value == null || value.trim().isEmpty()) {
      throw new IllegalArgumentException(name + " must not be empty");
    }
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

  interface CatalogSource {
    List<AppStoreItem> loadApps();

    List<Author> loadAuthors();

    List<MediaImage> loadMedia();
  }

  interface ScreenshotSource {
    ScreenshotData load(String blobKey);
  }

  static final class ScreenshotData {
    final String filename;
    final String contentType;
    final long uploadTimeMs;
    final String legacyServingUrl;
    final byte[] data;

    ScreenshotData(
        String filename,
        String contentType,
        long uploadTimeMs,
        String legacyServingUrl,
        byte[] data) {
      this.filename = filename;
      this.contentType = contentType;
      this.uploadTimeMs = uploadTimeMs;
      this.legacyServingUrl = legacyServingUrl;
      this.data = data == null ? null : Arrays.copyOf(data, data.length);
    }
  }

  /** Validation failure that lists every safely discoverable referential-integrity problem. */
  public static final class ExportValidationException extends IllegalStateException {
    private final List<String> mViolations;

    ExportValidationException(List<String> violations) {
      super("Normalized catalog export failed:\n - " + String.join("\n - ", violations));
      mViolations = Collections.unmodifiableList(new ArrayList<>(violations));
    }

    public List<String> getViolations() {
      return mViolations;
    }
  }

  /** Successful normalized metadata plus immutable object payloads. */
  public static final class ExportBundle {
    private final Manifest mManifest;
    private final Map<String, byte[]> mObjects;

    ExportBundle(Manifest manifest, Map<String, byte[]> objects) {
      mManifest = manifest;
      mObjects = new TreeMap<>();
      for (Map.Entry<String, byte[]> object : objects.entrySet()) {
        mObjects.put(object.getKey(), Arrays.copyOf(object.getValue(), object.getValue().length));
      }
    }

    public String manifestJson() {
      return MANIFEST_GSON.toJson(mManifest);
    }

    public List<String> getObjectPaths() {
      return Collections.unmodifiableList(new ArrayList<>(mObjects.keySet()));
    }

    public byte[] getObject(String path) {
      byte[] body = mObjects.get(path);
      return body == null ? null : Arrays.copyOf(body, body.length);
    }

    /** Writes a deterministic transport archive without closing the caller's stream. */
    public void writeZip(OutputStream output) throws IOException {
      Objects.requireNonNull(output);
      ZipOutputStream zip = new ZipOutputStream(output, StandardCharsets.UTF_8);
      writeEntry(zip, "manifest.json", manifestJson().getBytes(StandardCharsets.UTF_8));
      for (Map.Entry<String, byte[]> object : mObjects.entrySet()) {
        writeEntry(zip, "objects/" + object.getKey(), object.getValue());
      }
      zip.finish();
      zip.flush();
    }

    private static void writeEntry(ZipOutputStream zip, String name, byte[] body)
        throws IOException {
      ZipEntry entry = new ZipEntry(name);
      entry.setTime(ZIP_ENTRY_TIMESTAMP);
      zip.putNextEntry(entry);
      zip.write(body);
      zip.closeEntry();
    }
  }

  /** Top-level catalog mirror schema version 1. */
  public static final class Manifest {
    @SerializedName("schema_version")
    public int schemaVersion = 1;

    public Source source;
    public List<AppRecord> apps = new ArrayList<>();
    public List<MediaRecord> media = new ArrayList<>();
    public List<ScreenshotRecord> screenshots = new ArrayList<>();
    public Reconciliation reconciliation;
  }

  public static final class Source {
    @SerializedName("project_id")
    public String projectId;

    @SerializedName("exported_at")
    public String exportedAt;

    @SerializedName("high_water_mark")
    public String highWaterMark;

    Source(String projectId, String exportedAt, String highWaterMark) {
      this.projectId = projectId;
      this.exportedAt = exportedAt;
      this.highWaterMark = highWaterMark;
    }
  }

  public static final class AppRecord {
    public String id;
    public String name;
    public String version;
    public String description;

    @SerializedName("release_year")
    public int releaseYear;

    public String platform;
    public String model;
    public List<String> categories = new ArrayList<>();

    @SerializedName("author_id")
    public String authorId;

    @SerializedName("author_name")
    public String authorName;

    @SerializedName("publisher_email")
    public String publisherEmail;

    @SerializedName("first_published_at_ms")
    public long firstPublishedAtMs;

    @SerializedName("updated_at_ms")
    public long updatedAtMs;

    @SerializedName("media_slots")
    public MediaSlots mediaSlots = new MediaSlots();

    @SerializedName("screenshot_ids")
    public List<String> screenshotIds = new ArrayList<>();
  }

  public static final class MediaSlots {
    public List<String> disks = new ArrayList<>();
    public String cassette;
    public String command;
    public String basic;
  }

  public static final class MediaRecord {
    public String id;

    @SerializedName("app_id")
    public String appId;

    @SerializedName("media_type")
    public String mediaType;

    public String filename;
    public String description;

    @SerializedName("upload_time_ms")
    public long uploadTimeMs;

    @SerializedName("object_path")
    public String objectPath;

    public long size;
    public String sha256;
  }

  public static final class ScreenshotRecord {
    public String id;

    @SerializedName("app_id")
    public String appId;

    public String filename;

    @SerializedName("content_type")
    public String contentType;

    @SerializedName("upload_time_ms")
    public long uploadTimeMs;

    @SerializedName("legacy_serving_url")
    public String legacyServingUrl;

    @SerializedName("object_path")
    public String objectPath;

    public long size;
    public String sha256;
  }

  public static final class Reconciliation {
    @SerializedName("app_count")
    public int appCount;

    @SerializedName("media_count")
    public int mediaCount;

    @SerializedName("screenshot_count")
    public int screenshotCount;

    @SerializedName("object_count")
    public int objectCount;

    @SerializedName("total_bytes")
    public long totalBytes;

    @SerializedName("content_aggregate_sha256")
    public String contentAggregateSha256;
  }

  private static final class ObjectifyCatalogSource implements CatalogSource {
    @Override
    public List<AppStoreItem> loadApps() {
      return ofy().load().type(AppStoreItem.class).list();
    }

    @Override
    public List<Author> loadAuthors() {
      return ofy().load().type(Author.class).list();
    }

    @Override
    public List<MediaImage> loadMedia() {
      return ofy().load().type(MediaImage.class).list();
    }
  }

  static final class AppEngineScreenshotSource implements ScreenshotSource {
    private final BlobInfoFactory mBlobInfoFactory;
    private final BlobstoreService mBlobstoreService;
    private final ImageServiceWrapper mImageService;

    AppEngineScreenshotSource(
        BlobInfoFactory blobInfoFactory,
        BlobstoreService blobstoreService,
        ImageServiceWrapper imageService) {
      mBlobInfoFactory = Objects.requireNonNull(blobInfoFactory);
      mBlobstoreService = Objects.requireNonNull(blobstoreService);
      mImageService = Objects.requireNonNull(imageService);
    }

    @Override
    public ScreenshotData load(String blobKey) {
      BlobInfo info = mBlobInfoFactory.loadBlobInfo(new BlobKey(blobKey));
      if (info == null) {
        return null;
      }
      if (info.getSize() < 0 || info.getSize() > Integer.MAX_VALUE) {
        throw new IllegalStateException("Screenshot has an unsupported size");
      }
      ByteArrayOutputStream output = new ByteArrayOutputStream((int) info.getSize());
      long offset = 0;
      while (offset < info.getSize()) {
        long end = Math.min(
            info.getSize() - 1,
            offset + BlobstoreService.MAX_BLOB_FETCH_SIZE - 1L);
        byte[] chunk = mBlobstoreService.fetchData(new BlobKey(blobKey), offset, end);
        int expected = Math.toIntExact(end - offset + 1);
        if (chunk == null || chunk.length != expected) {
          throw new IllegalStateException("Blobstore returned an incomplete screenshot chunk");
        }
        output.write(chunk, 0, chunk.length);
        offset += chunk.length;
      }
      Date creation = info.getCreation();
      return new ScreenshotData(
          info.getFilename(),
          info.getContentType(),
          creation == null ? 0 : creation.getTime(),
          mImageService.getServingUrl(blobKey).orElse(null),
          output.toByteArray());
    }
  }
}
