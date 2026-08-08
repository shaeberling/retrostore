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
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.junit.Test;
import org.retrostore.data.card.RetroCardFirmware;
import org.retrostore.data.card.TrsIoFirmware;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

import static com.google.common.truth.Truth.assertThat;
import static org.junit.Assert.assertThrows;

public final class NormalizedFirmwareExporterTest {
  private static final Instant EXPORTED_AT = Instant.parse("2026-08-08T00:00:00Z");

  @Test
  public void exportsDeterministicManifestAndImmutableFirmwareObjects() throws Exception {
    FakeFirmwareSource source = completeSource(false);
    NormalizedFirmwareExporter.ExportBundle bundle =
        new NormalizedFirmwareExporter(source).create("trs-80", EXPORTED_AT, "cursor");
    JsonObject manifest = new Gson().fromJson(bundle.manifestJson(), JsonObject.class);

    assertThat(manifest.get("schema_version").getAsInt()).isEqualTo(1);
    assertThat(manifest.getAsJsonObject("source").get("project_id").getAsString())
        .isEqualTo("trs-80");
    JsonArray records = manifest.getAsJsonArray("firmware");
    assertThat(records).hasSize(3);
    assertThat(records.get(0).getAsJsonObject().get("id").getAsString())
        .isEqualTo("card-1-1");
    assertThat(records.get(1).getAsJsonObject().get("id").getAsString())
        .isEqualTo("card-1-2");
    assertThat(records.get(2).getAsJsonObject().get("id").getAsString())
        .isEqualTo("trs-io-1-1");
    assertThat(records.get(0).getAsJsonObject().get("object_path").getAsString())
        .startsWith("firmware/card/1/1/");
    assertThat(records.get(0).getAsJsonObject().get("sha256").getAsString()).hasLength(64);

    JsonObject reconciliation = manifest.getAsJsonObject("reconciliation");
    assertThat(reconciliation.get("firmware_count").getAsInt()).isEqualTo(3);
    assertThat(reconciliation.get("object_count").getAsInt()).isEqualTo(3);
    assertThat(reconciliation.get("total_bytes").getAsLong())
        .isEqualTo("card one".length() + "card two".length() + "trs one".length());
    assertThat(reconciliation.get("content_aggregate_sha256").getAsString()).hasLength(64);
    assertThat(reconciliation.get("content_aggregate_sha256").getAsString())
        .isEqualTo("97628f10de58fb2b1570045ac786bdac4cd9dab6fdda8865405c985e83a823f1");

    List<String> paths = bundle.getObjectPaths();
    assertThat(paths).isInOrder();
    Map<String, byte[]> archive = unzip(bundle);
    assertThat(archive.keySet())
        .containsExactly(
            "manifest.json",
            "objects/" + paths.get(0),
            "objects/" + paths.get(1),
            "objects/" + paths.get(2))
        .inOrder();
    assertThat(new String(archive.get("objects/" + paths.get(0)), StandardCharsets.UTF_8))
        .isEqualTo("card one");
  }

  @Test
  public void manifestAndZipAreIndependentOfSourceOrder() throws Exception {
    NormalizedFirmwareExporter.ExportBundle first =
        new NormalizedFirmwareExporter(completeSource(false))
            .create("trs-80", EXPORTED_AT, "cursor");
    NormalizedFirmwareExporter.ExportBundle second =
        new NormalizedFirmwareExporter(completeSource(true))
            .create("trs-80", EXPORTED_AT, "cursor");

    assertThat(first.manifestJson()).isEqualTo(second.manifestJson());
    assertThat(zipBytes(first)).isEqualTo(zipBytes(second));
  }

  @Test
  public void rejectsMalformedDuplicateAndMissingFirmwareWithoutLeakingBytes() {
    RetroCardFirmware malformed = new RetroCardFirmware(-1, 0, null);
    malformed.id = "secret-wrong-id";
    RetroCardFirmware duplicateOne = new RetroCardFirmware(1, 1, "first".getBytes());
    RetroCardFirmware duplicateTwo = new RetroCardFirmware(1, 1, "secret body".getBytes());
    FakeFirmwareSource source =
        new FakeFirmwareSource(
            Arrays.asList(malformed, duplicateOne, duplicateTwo), Collections.emptyList());

    NormalizedFirmwareExporter.ExportValidationException error =
        assertThrows(
            NormalizedFirmwareExporter.ExportValidationException.class,
            () ->
                new NormalizedFirmwareExporter(source)
                    .create("trs-80", EXPORTED_AT, "cursor"));

    assertThat(error.getViolations())
        .containsExactly(
            "card firmware[secret-wrong-id] does not match revision and version",
            "card firmware[secret-wrong-id] has a negative revision",
            "card firmware[secret-wrong-id] has a non-positive version",
            "card firmware[secret-wrong-id] has null data",
            "duplicate normalized firmware ID card-1-1")
        .inOrder();
    assertThat(error.getMessage()).doesNotContain("secret body");
  }

  @Test
  public void returnedFirmwareBytesAreDefensiveCopies() {
    NormalizedFirmwareExporter.ExportBundle bundle =
        new NormalizedFirmwareExporter(completeSource(false))
            .create("trs-80", EXPORTED_AT, "cursor");
    String path = bundle.getObjectPaths().get(0);
    byte[] first = bundle.getObject(path);
    first[0] = (byte) 'X';

    assertThat(new String(bundle.getObject(path), StandardCharsets.UTF_8)).isEqualTo("card one");
  }

  private static FakeFirmwareSource completeSource(boolean reversed) {
    List<RetroCardFirmware> cards =
        new ArrayList<>(
            Arrays.asList(
                new RetroCardFirmware(1, 2, "card two".getBytes(StandardCharsets.UTF_8)),
                new RetroCardFirmware(1, 1, "card one".getBytes(StandardCharsets.UTF_8))));
    List<TrsIoFirmware> trsIo =
        new ArrayList<>(
            Collections.singletonList(
                new TrsIoFirmware(1, 1, "trs one".getBytes(StandardCharsets.UTF_8))));
    if (reversed) {
      Collections.reverse(cards);
      Collections.reverse(trsIo);
    }
    return new FakeFirmwareSource(cards, trsIo);
  }

  private static byte[] zipBytes(NormalizedFirmwareExporter.ExportBundle bundle)
      throws Exception {
    ByteArrayOutputStream output = new ByteArrayOutputStream();
    bundle.writeZip(output);
    return output.toByteArray();
  }

  private static Map<String, byte[]> unzip(NormalizedFirmwareExporter.ExportBundle bundle)
      throws Exception {
    Map<String, byte[]> entries = new LinkedHashMap<>();
    ZipInputStream zip = new ZipInputStream(new ByteArrayInputStream(zipBytes(bundle)));
    ZipEntry entry;
    byte[] buffer = new byte[1024];
    while ((entry = zip.getNextEntry()) != null) {
      ByteArrayOutputStream body = new ByteArrayOutputStream();
      int read;
      while ((read = zip.read(buffer)) >= 0) {
        body.write(buffer, 0, read);
      }
      entries.put(entry.getName(), body.toByteArray());
    }
    return entries;
  }

  private static final class FakeFirmwareSource
      implements NormalizedFirmwareExporter.FirmwareSource {
    private final List<RetroCardFirmware> mCards;
    private final List<TrsIoFirmware> mTrsIo;

    FakeFirmwareSource(List<RetroCardFirmware> cards, List<TrsIoFirmware> trsIo) {
      mCards = cards;
      mTrsIo = trsIo;
    }

    @Override
    public List<RetroCardFirmware> loadCardFirmware() {
      return mCards;
    }

    @Override
    public List<TrsIoFirmware> loadTrsIoFirmware() {
      return mTrsIo;
    }
  }
}
