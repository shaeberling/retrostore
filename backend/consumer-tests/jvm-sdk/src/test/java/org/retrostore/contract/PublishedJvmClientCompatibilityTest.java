package org.retrostore.contract;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.google.protobuf.ByteString;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.retrostore.RetrostoreClient;
import org.retrostore.RetrostoreClientImpl;
import org.retrostore.client.common.proto.App;
import org.retrostore.client.common.proto.AppNano;
import org.retrostore.client.common.proto.MediaImage;
import org.retrostore.client.common.proto.MediaImageRef;
import org.retrostore.client.common.proto.SystemState;
import org.retrostore.client.common.proto.Trs80Model;

class PublishedJvmClientCompatibilityTest {
  private static final String FIXTURE_APP_ID = "259847aa-ce3a-48bb-a037-e392beb96b22";

  @Test
  void publishedClientExercisesAllNineCandidateMethods() throws Exception {
    RetrostoreClient client = RetrostoreClientImpl.get(
        "", System.getProperty("candidateUrl") + "/api/%s", false);

    List<App> apps = client.fetchApps(0, 2);
    assertEquals(2, apps.size());
    assertEquals("Armored Patrol", apps.get(0).getName());

    App fixture = client.getApp(FIXTURE_APP_ID);
    assertNotNull(fixture);
    assertEquals("Space Invaders (Model I Edition)", fixture.getName());

    List<AppNano> nanoApps = client.fetchAppsNano(0, 2);
    assertEquals(2, nanoApps.size());
    assertEquals(apps.get(0).getId(), nanoApps.get(0).getId());

    List<MediaImage> images = client.fetchMediaImages(FIXTURE_APP_ID);
    assertEquals(2, images.size());
    MediaImage command = images.stream()
        .filter(image -> image.getFilename().equals("command.CMD"))
        .findFirst()
        .orElseThrow();
    assertEquals(3_477, command.getData().size());

    List<MediaImageRef> refs = client.fetchMediaImageRefs(FIXTURE_APP_ID);
    assertEquals(2, refs.size());
    MediaImageRef commandRef = refs.stream()
        .filter(ref -> ref.getFilename().equals("command.CMD"))
        .findFirst()
        .orElseThrow();
    assertEquals(command.getData().size(), commandRef.getSize());
    assertArrayEquals(
        command.getData().substring(0, 16).toByteArray(),
        client.fetchMediaImageRegion(commandRef, 0, 16));

    SystemState state = SystemState.newBuilder()
        .setModel(Trs80Model.MODEL_I)
        .setRegisters(SystemState.Registers.newBuilder().setPc(0x1234))
        .addMemoryRegions(SystemState.MemoryRegion.newBuilder()
            .setStart(256)
            .setLength(99)
            .setData(ByteString.copyFrom(new byte[] {1, 2, 3, 4})))
        .build();

    long token = client.uploadState(state);
    assertTrue(token > 0);

    SystemState downloaded = client.downloadState(token);
    assertNotNull(downloaded);
    assertEquals(0x1234, downloaded.getRegisters().getPc());
    assertEquals(4, downloaded.getMemoryRegions(0).getLength());
    assertArrayEquals(new byte[] {1, 2, 3, 4}, downloaded.getMemoryRegions(0).getData().toByteArray());

    SystemState withoutMemory = client.downloadState(token, true);
    assertEquals(4, withoutMemory.getMemoryRegions(0).getLength());
    assertTrue(withoutMemory.getMemoryRegions(0).getData().isEmpty());
    assertArrayEquals(
        new byte[] {1, 2, 3, 4},
        client.downloadSystemStateMemoryRegion(token, 256, 4));
  }
}
