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
import com.google.gson.GsonBuilder;
import com.google.gson.annotations.SerializedName;
import org.retrostore.data.Register;
import org.retrostore.data.card.Firmware;
import org.retrostore.data.card.RetroCardFirmware;
import org.retrostore.data.card.TrsIoFirmware;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import static com.googlecode.objectify.ObjectifyService.ofy;

/** Converts both legacy inline firmware kinds into an immutable normalized archive. */
public final class NormalizedFirmwareExporter {
  private static final long ZIP_ENTRY_TIMESTAMP = 315532800000L; // 1980-01-01 UTC.
  private static final Gson MANIFEST_GSON =
      new GsonBuilder().disableHtmlEscaping().serializeNulls().create();

  private final FirmwareSource mSource;

  /** Creates a read-only exporter backed by Objectify. */
  public static NormalizedFirmwareExporter forAppEngine() {
    Register.ensureRegistered();
    return new NormalizedFirmwareExporter(new ObjectifyFirmwareSource());
  }

  NormalizedFirmwareExporter(FirmwareSource source) {
    mSource = Objects.requireNonNull(source);
  }

  /** Creates a deterministic complete firmware snapshot without modifying legacy entities. */
  public ExportBundle create(String projectId, Instant exportedAt, String highWaterMark) {
    requireNonEmpty(projectId, "projectId");
    Objects.requireNonNull(exportedAt);
    requireNonEmpty(highWaterMark, "highWaterMark");

    List<Candidate> candidates = new ArrayList<>();
    addCandidates(candidates, "card", mSource.loadCardFirmware());
    addCandidates(candidates, "trs-io", mSource.loadTrsIoFirmware());
    candidates.sort(
        Comparator.comparing((Candidate item) -> item.product)
            .thenComparingInt(item -> item.firmware.getRevision())
            .thenComparingInt(item -> item.firmware.getVersion()));

    Manifest manifest = new Manifest();
    manifest.source = new Source(projectId, exportedAt.toString(), highWaterMark);
    Map<String, byte[]> objects = new TreeMap<>();
    Map<String, FirmwareRecord> records = new LinkedHashMap<>();
    List<String> violations = new ArrayList<>();

    for (Candidate candidate : candidates) {
      Firmware source = candidate.firmware;
      String context = candidate.product + " firmware[" + source.getId() + "]";
      int revision = source.getRevision();
      int version = source.getVersion();
      if (revision < 0) {
        violations.add(context + " has a negative revision");
      }
      if (version < 1) {
        violations.add(context + " has a non-positive version");
      }
      String expectedLegacyId = revision + "-" + version;
      if (!expectedLegacyId.equals(source.getId())) {
        violations.add(context + " does not match revision and version");
      }
      byte[] body = source.getData();
      if (body == null) {
        violations.add(context + " has null data");
        continue;
      }

      String id = candidate.product + "-" + revision + "-" + version;
      String digest = sha256(body);
      String path =
          "firmware/"
              + candidate.product
              + "/"
              + revision
              + "/"
              + version
              + "/"
              + digest
              + ".bin";
      FirmwareRecord record =
          new FirmwareRecord(id, candidate.product, revision, version, path, body.length, digest);
      if (records.putIfAbsent(id, record) != null) {
        violations.add("duplicate normalized firmware ID " + id);
        continue;
      }
      objects.put(path, Arrays.copyOf(body, body.length));
    }

    if (!violations.isEmpty()) {
      throw new ExportValidationException(new ArrayList<>(new TreeSet<>(violations)));
    }
    manifest.firmware.addAll(records.values());
    manifest.reconciliation = reconciliation(manifest.firmware, objects);
    return new ExportBundle(manifest, objects);
  }

  private static void addCandidates(
      List<Candidate> result, String product, List<? extends Firmware> source) {
    if (source == null) {
      throw new IllegalStateException(product + " firmware source returned null");
    }
    for (Firmware firmware : source) {
      if (firmware == null) {
        throw new IllegalStateException(product + " firmware source contains null");
      }
      result.add(new Candidate(product, firmware));
    }
  }

  private static Reconciliation reconciliation(
      List<FirmwareRecord> records, Map<String, byte[]> objects) {
    long totalBytes = 0;
    MessageDigest aggregate = sha256Digest();
    for (FirmwareRecord record : records) {
      totalBytes += record.size;
      String framed =
          record.id
              + "\u0000"
              + record.objectPath
              + "\u0000"
              + record.size
              + "\u0000"
              + record.sha256
              + "\n";
      aggregate.update(framed.getBytes(StandardCharsets.UTF_8));
    }
    return new Reconciliation(
        records.size(), objects.size(), totalBytes, toHex(aggregate.digest()));
  }

  private static String sha256(byte[] body) {
    return toHex(sha256Digest().digest(body));
  }

  private static MessageDigest sha256Digest() {
    try {
      return MessageDigest.getInstance("SHA-256");
    } catch (NoSuchAlgorithmException error) {
      throw new AssertionError("SHA-256 is required by the Java runtime", error);
    }
  }

  private static String toHex(byte[] value) {
    StringBuilder result = new StringBuilder(value.length * 2);
    for (byte item : value) {
      result.append(String.format(Locale.US, "%02x", item & 0xff));
    }
    return result.toString();
  }

  private static void requireNonEmpty(String value, String label) {
    if (value == null || value.isEmpty()) {
      throw new IllegalArgumentException(label + " must not be empty");
    }
  }

  interface FirmwareSource {
    List<? extends Firmware> loadCardFirmware();

    List<? extends Firmware> loadTrsIoFirmware();
  }

  private static final class ObjectifyFirmwareSource implements FirmwareSource {
    @Override
    public List<RetroCardFirmware> loadCardFirmware() {
      return ofy().load().type(RetroCardFirmware.class).list();
    }

    @Override
    public List<TrsIoFirmware> loadTrsIoFirmware() {
      return ofy().load().type(TrsIoFirmware.class).list();
    }
  }

  private static final class Candidate {
    final String product;
    final Firmware firmware;

    Candidate(String product, Firmware firmware) {
      this.product = product;
      this.firmware = firmware;
    }
  }

  /** Validation failure containing only source metadata, never firmware bytes. */
  public static final class ExportValidationException extends IllegalStateException {
    private final List<String> mViolations;

    ExportValidationException(List<String> violations) {
      super("Normalized firmware export failed:\n - " + String.join("\n - ", violations));
      mViolations = Collections.unmodifiableList(new ArrayList<>(violations));
    }

    public List<String> getViolations() {
      return mViolations;
    }
  }

  /** Successful normalized metadata plus immutable firmware payloads. */
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

  public static final class Manifest {
    @SerializedName("schema_version")
    public int schemaVersion = 1;

    public Source source;
    public List<FirmwareRecord> firmware = new ArrayList<>();
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

  public static final class FirmwareRecord {
    public String id;
    public String product;
    public int revision;
    public int version;

    @SerializedName("object_path")
    public String objectPath;

    public long size;
    public String sha256;

    FirmwareRecord(
        String id,
        String product,
        int revision,
        int version,
        String objectPath,
        long size,
        String sha256) {
      this.id = id;
      this.product = product;
      this.revision = revision;
      this.version = version;
      this.objectPath = objectPath;
      this.size = size;
      this.sha256 = sha256;
    }
  }

  public static final class Reconciliation {
    @SerializedName("firmware_count")
    public int firmwareCount;

    @SerializedName("object_count")
    public int objectCount;

    @SerializedName("total_bytes")
    public long totalBytes;

    @SerializedName("content_aggregate_sha256")
    public String contentAggregateSha256;

    Reconciliation(
        int firmwareCount, int objectCount, long totalBytes, String contentAggregateSha256) {
      this.firmwareCount = firmwareCount;
      this.objectCount = objectCount;
      this.totalBytes = totalBytes;
      this.contentAggregateSha256 = contentAggregateSha256;
    }
  }
}
