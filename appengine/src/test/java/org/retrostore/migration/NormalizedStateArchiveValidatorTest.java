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

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.protobuf.ByteString;
import org.junit.Test;
import org.retrostore.client.common.proto.SystemState;
import org.retrostore.client.common.proto.Trs80Model;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.Locale;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import static com.google.common.truth.Truth.assertThat;
import static org.junit.Assert.assertThrows;

public final class NormalizedStateArchiveValidatorTest {
  private static final long TOKEN = 321;
  private static final String CAPTURED_AT = "2026-08-10T01:00:00.000000Z";
  private static final String CREATED_AT = "2026-08-10T00:59:00.000000Z";
  private static final String EXPIRES_AT = "2026-08-17T00:59:00.000000Z";

  @Test
  public void validatesAndMapsThePrivateArchiveWithoutPersistence() throws Exception {
    byte[] body = state().toByteArray();
    NormalizedStateArchiveValidator.ValidatedBundle bundle =
        NormalizedStateArchiveValidator.load(
            new ByteArrayInputStream(archive(body, EXPIRES_AT, false)));

    assertThat(bundle.getSourceProjectId()).isEqualTo("trs-80");
    assertThat(bundle.getCapturedAt()).isEqualTo(Instant.parse(CAPTURED_AT));
    assertThat(bundle.getStateCount()).isEqualTo(1);
    assertThat(bundle.getTotalBytes()).isEqualTo(body.length);
    assertThat(bundle.getContentAggregateSha256()).isEqualTo(aggregate(body));

    org.retrostore.data.xray.SystemState legacy = bundle.getLegacyStates().get(0);
    assertThat(legacy.token).isEqualTo(TOKEN);
    assertThat(legacy.addTimestamp).isEqualTo(Instant.parse(CREATED_AT).toEpochMilli());
    assertThat(legacy.model).isEqualTo(org.retrostore.data.xray.SystemState.Model.MODEL_III);
    assertThat(legacy.registers.pc).isEqualTo(0x1234);
    assertThat(legacy.memoryRegions).hasSize(1);
    assertThat(legacy.memoryRegions.get(0).start).isEqualTo(0x4000);
    assertThat(legacy.memoryRegions.get(0).data).isEqualTo(new byte[] {'T', 'E', 'S', 'T'});

    legacy.memoryRegions.get(0).data[0] = 'X';
    assertThat(bundle.getLegacyStates().get(0).memoryRegions.get(0).data)
        .isEqualTo(new byte[] {'T', 'E', 'S', 'T'});
  }

  @Test
  public void rejectsChecksumMismatchExpiredStateAndUnexpectedEntry() throws Exception {
    byte[] body = state().toByteArray();
    byte[] mismatched = archive(body, EXPIRES_AT, true);
    assertThrows(
        NormalizedStateArchiveValidator.ValidationException.class,
        () -> NormalizedStateArchiveValidator.load(new ByteArrayInputStream(mismatched)));

    byte[] expired = archive(body, CAPTURED_AT, false);
    NormalizedStateArchiveValidator.ValidationException expiry =
        assertThrows(
            NormalizedStateArchiveValidator.ValidationException.class,
            () -> NormalizedStateArchiveValidator.load(new ByteArrayInputStream(expired)));
    assertThat(expiry).hasMessageThat().contains("live window");

    byte[] extra = archiveWithExtra(body);
    NormalizedStateArchiveValidator.ValidationException entries =
        assertThrows(
            NormalizedStateArchiveValidator.ValidationException.class,
            () -> NormalizedStateArchiveValidator.load(new ByteArrayInputStream(extra)));
    assertThat(entries).hasMessageThat().contains("entries do not match");
  }

  @Test
  public void rejectsInvalidProtobufAfterChecksumVerification() throws Exception {
    byte[] invalid = new byte[] {(byte) 0x80};
    NormalizedStateArchiveValidator.ValidationException error =
        assertThrows(
            NormalizedStateArchiveValidator.ValidationException.class,
            () ->
                NormalizedStateArchiveValidator.load(
                    new ByteArrayInputStream(archive(invalid, EXPIRES_AT, false))));

    assertThat(error).hasMessageThat().contains("SystemState protobuf");
  }

  @Test
  public void collisionPreflightClassifiesAbsentIdenticalAndExpiredWithoutWrites()
      throws Exception {
    NormalizedStateArchiveValidator.ValidatedBundle bundle = loadBundle();

    NormalizedStateArchiveValidator.PreflightReport absent =
        NormalizedStateArchiveValidator.preflight(bundle, ignored -> null);
    assertThat(absent.getStateCount()).isEqualTo(1);
    assertThat(absent.getCreates()).isEqualTo(1);
    assertThat(absent.getReuses()).isEqualTo(0);
    assertThat(absent.getExpiredReplacements()).isEqualTo(0);

    org.retrostore.data.xray.SystemState identical = bundle.getLegacyStates().get(0);
    NormalizedStateArchiveValidator.PreflightReport reused =
        NormalizedStateArchiveValidator.preflight(bundle, ignored -> identical);
    assertThat(reused.getCreates()).isEqualTo(0);
    assertThat(reused.getReuses()).isEqualTo(1);

    org.retrostore.data.xray.SystemState expired = bundle.getLegacyStates().get(0);
    expired.registers.pc++;
    expired.addTimestamp =
        Instant.parse(CAPTURED_AT).minus(Duration.ofDays(8)).toEpochMilli();
    NormalizedStateArchiveValidator.PreflightReport replace =
        NormalizedStateArchiveValidator.preflight(bundle, ignored -> expired);
    assertThat(replace.getExpiredReplacements()).isEqualTo(1);
  }

  @Test
  public void collisionPreflightRejectsADifferentLiveLegacyState() throws Exception {
    NormalizedStateArchiveValidator.ValidatedBundle bundle = loadBundle();
    org.retrostore.data.xray.SystemState different = bundle.getLegacyStates().get(0);
    different.registers.pc++;

    NormalizedStateArchiveValidator.ValidationException error =
        assertThrows(
            NormalizedStateArchiveValidator.ValidationException.class,
            () -> NormalizedStateArchiveValidator.preflight(bundle, ignored -> different));

    assertThat(error).hasMessageThat().contains("different live legacy state");
    assertThat(error).hasMessageThat().doesNotContain(Long.toString(TOKEN));
  }

  private static NormalizedStateArchiveValidator.ValidatedBundle loadBundle()
      throws Exception {
    return NormalizedStateArchiveValidator.load(
        new ByteArrayInputStream(archive(state().toByteArray(), EXPIRES_AT, false)));
  }

  private static SystemState state() {
    return SystemState.newBuilder()
        .setModel(Trs80Model.MODEL_III)
        .setRegisters(SystemState.Registers.newBuilder().setPc(0x1234))
        .addMemoryRegions(
            SystemState.MemoryRegion.newBuilder()
                .setStart(0x4000)
                .setLength(4)
                .setData(ByteString.copyFromUtf8("TEST")))
        .build();
  }

  private static byte[] archive(byte[] body, String expiresAt, boolean mismatch)
      throws Exception {
    String digest = mismatch ? repeat('0', 64) : sha256(body);
    JsonObject manifest = manifest(body, digest, expiresAt);
    return zip(
        manifest.toString().getBytes(StandardCharsets.UTF_8),
        "objects/states/" + TOKEN + "/" + digest + ".pb",
        body,
        false);
  }

  private static byte[] archiveWithExtra(byte[] body) throws Exception {
    String digest = sha256(body);
    return zip(
        manifest(body, digest, EXPIRES_AT).toString().getBytes(StandardCharsets.UTF_8),
        "objects/states/" + TOKEN + "/" + digest + ".pb",
        body,
        true);
  }

  private static JsonObject manifest(byte[] body, String digest, String expiresAt) {
    JsonObject source = new JsonObject();
    source.addProperty("project_id", "trs-80");
    source.addProperty("captured_at", CAPTURED_AT);

    JsonObject record = new JsonObject();
    record.addProperty("token", TOKEN);
    record.addProperty("created_at", CREATED_AT);
    record.addProperty("expires_at", expiresAt);
    record.addProperty("object_path", "states/" + TOKEN + "/" + digest + ".pb");
    record.addProperty("size", body.length);
    record.addProperty("sha256", digest);
    JsonArray states = new JsonArray();
    states.add(record);

    JsonObject reconciliation = new JsonObject();
    reconciliation.addProperty("state_count", 1);
    reconciliation.addProperty("total_bytes", body.length);
    reconciliation.addProperty("content_aggregate_sha256", aggregate(body));

    JsonObject manifest = new JsonObject();
    manifest.addProperty("schema_version", 1);
    manifest.add("source", source);
    manifest.add("states", states);
    manifest.add("reconciliation", reconciliation);
    return manifest;
  }

  private static byte[] zip(
      byte[] manifest, String objectPath, byte[] body, boolean includeExtra) throws Exception {
    ByteArrayOutputStream output = new ByteArrayOutputStream();
    ZipOutputStream zip = new ZipOutputStream(output, StandardCharsets.UTF_8);
    write(zip, "manifest.json", manifest);
    write(zip, objectPath, body);
    if (includeExtra) {
      write(zip, "unexpected.txt", new byte[] {1});
    }
    zip.finish();
    return output.toByteArray();
  }

  private static void write(ZipOutputStream zip, String name, byte[] body) throws Exception {
    zip.putNextEntry(new ZipEntry(name));
    zip.write(body);
    zip.closeEntry();
  }

  private static String aggregate(byte[] body) {
    MessageDigest digest = newDigest();
    digest.update(ByteBuffer.allocate(Long.BYTES).putLong(TOKEN).array());
    digest.update(ByteBuffer.allocate(Long.BYTES).putLong(body.length).array());
    digest.update(newDigest().digest(body));
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

  private static String repeat(char value, int count) {
    StringBuilder result = new StringBuilder(count);
    for (int index = 0; index < count; index++) {
      result.append(value);
    }
    return result.toString();
  }
}
