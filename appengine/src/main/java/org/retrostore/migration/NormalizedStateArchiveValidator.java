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
import com.google.gson.annotations.SerializedName;
import com.google.protobuf.InvalidProtocolBufferException;
import org.retrostore.client.common.proto.SystemState;

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
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Validates the private state rollback archive and maps it to legacy entities in memory.
 *
 * <p>This class deliberately has no Objectify dependency, mutation method, servlet route, or
 * registration in {@code MainServlet}. A future writer must add exact collision preflight and
 * post-write RPC reconciliation as a separate reviewed boundary.
 */
public final class NormalizedStateArchiveValidator {
  private static final int MIN_TOKEN = 100;
  private static final int MAX_TOKEN = 999;
  private static final int MAX_ENTRIES = 902;
  private static final long MAX_MANIFEST_BYTES = 1024L * 1024L;
  private static final long MAX_ARCHIVE_BYTES = 256L * 1024L * 1024L;
  private static final Pattern SHA256 = Pattern.compile("[0-9a-f]{64}");
  private static final Gson GSON = new Gson();

  private NormalizedStateArchiveValidator() {}

  /** Load and fully validate one archive without mutating App Engine services. */
  public static ValidatedBundle load(InputStream source) throws IOException {
    Objects.requireNonNull(source);
    Map<String, byte[]> archive = readArchive(source);
    byte[] manifestBytes = archive.get("manifest.json");
    if (manifestBytes == null) {
      throw new ValidationException("State archive must contain one manifest.json");
    }
    if (manifestBytes.length > MAX_MANIFEST_BYTES) {
      throw new ValidationException("State archive manifest is too large");
    }

    Manifest manifest;
    try {
      manifest = GSON.fromJson(new String(manifestBytes, StandardCharsets.UTF_8), Manifest.class);
    } catch (JsonParseException error) {
      throw new ValidationException("State archive manifest is not valid JSON", error);
    }
    if (manifest == null || manifest.schemaVersion != 1) {
      throw new ValidationException("Unsupported state archive schema");
    }
    if (manifest.source == null || isEmpty(manifest.source.projectId)) {
      throw new ValidationException("State archive source project is malformed");
    }
    Instant capturedAt = parseInstant(manifest.source.capturedAt, "captured_at");
    if (manifest.states == null || manifest.states.size() > MAX_TOKEN - MIN_TOKEN + 1) {
      throw new ValidationException("State archive records are malformed");
    }

    Set<Long> tokens = new HashSet<>();
    Set<String> expectedEntries = new HashSet<>();
    expectedEntries.add("manifest.json");
    List<LegacyStateRecord> records = new ArrayList<>();
    long totalBytes = 0;
    for (StateRecord value : manifest.states) {
      if (value == null || value.token < MIN_TOKEN || value.token > MAX_TOKEN) {
        throw new ValidationException("State archive token is malformed");
      }
      if (!tokens.add(value.token)) {
        throw new ValidationException("State archive tokens must be unique");
      }
      Instant createdAt = parseInstant(value.createdAt, "created_at");
      Instant expiresAt = parseInstant(value.expiresAt, "expires_at");
      if (createdAt.isAfter(capturedAt) || !expiresAt.isAfter(capturedAt)) {
        throw new ValidationException("State archive contains a state outside its live window");
      }
      if (value.size < 0 || value.size > MAX_ARCHIVE_BYTES || !isSha256(value.sha256)) {
        throw new ValidationException("State archive object metadata is malformed");
      }
      String expectedPath = "states/" + value.token + "/" + value.sha256 + ".pb";
      if (!expectedPath.equals(value.objectPath) || !isNormalizedPath(expectedPath)) {
        throw new ValidationException("State archive object path is malformed");
      }
      String archivePath = "objects/" + expectedPath;
      if (!expectedEntries.add(archivePath)) {
        throw new ValidationException("State archive object paths must be unique");
      }
      byte[] body = archive.get(archivePath);
      if (body == null) {
        throw new ValidationException("State archive payload is missing");
      }
      totalBytes += body.length;
      if (totalBytes > MAX_ARCHIVE_BYTES
          || body.length != value.size
          || !value.sha256.equals(sha256(body))) {
        throw new ValidationException("State archive payload failed checksum verification");
      }
      SystemState state;
      try {
        state = SystemState.parseFrom(body);
      } catch (InvalidProtocolBufferException error) {
        throw new ValidationException("State archive payload is not a SystemState protobuf", error);
      }
      validateState(state);
      records.add(new LegacyStateRecord(value.token, createdAt, expiresAt, state, body));
    }
    if (!archive.keySet().equals(expectedEntries)) {
      throw new ValidationException("State archive entries do not match its manifest");
    }
    records.sort((left, right) -> Long.compare(left.token, right.token));
    String aggregate = contentAggregate(records);
    if (manifest.reconciliation == null
        || manifest.reconciliation.stateCount != records.size()
        || manifest.reconciliation.totalBytes != totalBytes
        || !aggregate.equals(manifest.reconciliation.contentAggregateSha256)) {
      throw new ValidationException("State archive reconciliation failed");
    }
    return new ValidatedBundle(
        manifest.source.projectId,
        capturedAt,
        records,
        totalBytes,
        aggregate);
  }

  private static Map<String, byte[]> readArchive(InputStream source) throws IOException {
    Map<String, byte[]> values = new LinkedHashMap<>();
    long totalBytes = 0;
    int entries = 0;
    ZipInputStream zip = new ZipInputStream(source, StandardCharsets.UTF_8);
    ZipEntry entry;
    while ((entry = zip.getNextEntry()) != null) {
      entries++;
      if (entries > MAX_ENTRIES) {
        throw new ValidationException("State archive contains too many entries");
      }
      if (entry.isDirectory() || isEmpty(entry.getName())) {
        throw new ValidationException("State archive must not contain directory entries");
      }
      long limit = "manifest.json".equals(entry.getName())
          ? MAX_MANIFEST_BYTES
          : MAX_ARCHIVE_BYTES;
      if (entry.getSize() > limit) {
        throw new ValidationException("State archive entry exceeds its size limit");
      }
      byte[] body = readBounded(zip, limit);
      totalBytes += body.length;
      if (totalBytes > MAX_ARCHIVE_BYTES + MAX_MANIFEST_BYTES) {
        throw new ValidationException("State archive exceeds its total size limit");
      }
      if (values.putIfAbsent(entry.getName(), body) != null) {
        throw new ValidationException("State archive contains duplicate entries");
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
        throw new ValidationException("State archive entry exceeds its size limit");
      }
      output.write(buffer, 0, read);
    }
    return output.toByteArray();
  }

  private static String contentAggregate(List<LegacyStateRecord> records) {
    MessageDigest aggregate = newDigest();
    for (LegacyStateRecord record : records) {
      byte[] body = record.body;
      aggregate.update(ByteBuffer.allocate(Long.BYTES).putLong(record.token).array());
      aggregate.update(ByteBuffer.allocate(Long.BYTES).putLong(body.length).array());
      aggregate.update(newDigest().digest(body));
    }
    return toHex(aggregate.digest());
  }

  private static void validateState(SystemState state) {
    final int maxRegionSize = 1_000_000;
    for (SystemState.MemoryRegion region : state.getMemoryRegionsList()) {
      if (region.getStart() < 0
          || region.getStart() >= maxRegionSize
          || region.getLength() >= maxRegionSize
          || region.getData().size() >= maxRegionSize) {
        throw new ValidationException("State archive contains an invalid memory region");
      }
    }
  }

  private static org.retrostore.data.xray.SystemState toLegacyState(LegacyStateRecord record) {
    SystemState proto = record.proto;
    org.retrostore.data.xray.SystemState result =
        new org.retrostore.data.xray.SystemState();
    result.token = record.token;
    result.addTimestamp = record.createdAt.toEpochMilli();
    switch (proto.getModel()) {
      case MODEL_I:
        result.model = org.retrostore.data.xray.SystemState.Model.MODEL_I;
        break;
      case MODEL_III:
        result.model = org.retrostore.data.xray.SystemState.Model.MODEL_III;
        break;
      case MODEL_4:
        result.model = org.retrostore.data.xray.SystemState.Model.MODEL_4;
        break;
      case MODEL_4P:
        result.model = org.retrostore.data.xray.SystemState.Model.MODEL_4P;
        break;
      case UNKNOWN_MODEL:
      case UNRECOGNIZED:
        result.model = null;
        break;
    }

    SystemState.Registers sourceRegisters = proto.getRegisters();
    org.retrostore.data.xray.SystemState.Registers registers =
        new org.retrostore.data.xray.SystemState.Registers();
    registers.ix = sourceRegisters.getIx();
    registers.iy = sourceRegisters.getIy();
    registers.pc = sourceRegisters.getPc();
    registers.sp = sourceRegisters.getSp();
    registers.af = sourceRegisters.getAf();
    registers.bc = sourceRegisters.getBc();
    registers.de = sourceRegisters.getDe();
    registers.hl = sourceRegisters.getHl();
    registers.af_prime = sourceRegisters.getAfPrime();
    registers.bc_prime = sourceRegisters.getBcPrime();
    registers.de_prime = sourceRegisters.getDePrime();
    registers.hl_prime = sourceRegisters.getHlPrime();
    registers.i = sourceRegisters.getI();
    registers.r_1 = sourceRegisters.getR1();
    registers.r_2 = sourceRegisters.getR2();
    result.registers = registers;

    for (SystemState.MemoryRegion sourceRegion : proto.getMemoryRegionsList()) {
      org.retrostore.data.xray.SystemState.MemoryRegion region =
          new org.retrostore.data.xray.SystemState.MemoryRegion();
      region.start = sourceRegion.getStart();
      region.data = sourceRegion.getData().toByteArray();
      result.memoryRegions.add(region);
    }
    return result;
  }

  private static Instant parseInstant(String value, String name) {
    if (isEmpty(value)) {
      throw new ValidationException("State archive " + name + " is malformed");
    }
    try {
      return Instant.parse(value);
    } catch (DateTimeParseException error) {
      throw new ValidationException("State archive " + name + " is malformed", error);
    }
  }

  private static boolean isNormalizedPath(String value) {
    return value.startsWith("states/")
        && !value.startsWith("/")
        && !value.contains("\\")
        && !value.contains("//")
        && !value.contains("/../")
        && !value.contains("/./");
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

  private static String toHex(byte[] value) {
    StringBuilder result = new StringBuilder(value.length * 2);
    for (byte item : value) {
      result.append(String.format(Locale.US, "%02x", item & 0xff));
    }
    return result.toString();
  }

  /** A fully reconciled, read-only archive result. */
  public static final class ValidatedBundle {
    private final String sourceProjectId;
    private final Instant capturedAt;
    private final List<LegacyStateRecord> records;
    private final long totalBytes;
    private final String contentAggregateSha256;

    private ValidatedBundle(
        String sourceProjectId,
        Instant capturedAt,
        List<LegacyStateRecord> records,
        long totalBytes,
        String contentAggregateSha256) {
      this.sourceProjectId = sourceProjectId;
      this.capturedAt = capturedAt;
      this.records = Collections.unmodifiableList(new ArrayList<>(records));
      this.totalBytes = totalBytes;
      this.contentAggregateSha256 = contentAggregateSha256;
    }

    public String getSourceProjectId() {
      return sourceProjectId;
    }

    public Instant getCapturedAt() {
      return capturedAt;
    }

    public int getStateCount() {
      return records.size();
    }

    public long getTotalBytes() {
      return totalBytes;
    }

    public String getContentAggregateSha256() {
      return contentAggregateSha256;
    }

    /** Return fresh mutable legacy entities; this method still performs no persistence. */
    public List<org.retrostore.data.xray.SystemState> getLegacyStates() {
      List<org.retrostore.data.xray.SystemState> result = new ArrayList<>();
      for (LegacyStateRecord record : records) {
        result.add(toLegacyState(record));
      }
      return Collections.unmodifiableList(result);
    }
  }

  private static final class LegacyStateRecord {
    final long token;
    final Instant createdAt;
    final Instant expiresAt;
    final SystemState proto;
    final byte[] body;

    LegacyStateRecord(
        long token, Instant createdAt, Instant expiresAt, SystemState proto, byte[] body) {
      this.token = token;
      this.createdAt = createdAt;
      this.expiresAt = expiresAt;
      this.proto = proto;
      this.body = body.clone();
    }
  }

  /** Validation failure without payload or token values in the message. */
  public static final class ValidationException extends IllegalArgumentException {
    ValidationException(String message) {
      super(message);
    }

    ValidationException(String message, Throwable cause) {
      super(message, cause);
    }
  }

  private static final class Manifest {
    @SerializedName("schema_version")
    int schemaVersion;

    Source source;
    List<StateRecord> states;
    Reconciliation reconciliation;
  }

  private static final class Source {
    @SerializedName("project_id")
    String projectId;

    @SerializedName("captured_at")
    String capturedAt;
  }

  private static final class StateRecord {
    long token;

    @SerializedName("created_at")
    String createdAt;

    @SerializedName("expires_at")
    String expiresAt;

    @SerializedName("object_path")
    String objectPath;

    long size;
    String sha256;
  }

  private static final class Reconciliation {
    @SerializedName("state_count")
    long stateCount;

    @SerializedName("total_bytes")
    long totalBytes;

    @SerializedName("content_aggregate_sha256")
    String contentAggregateSha256;
  }
}
