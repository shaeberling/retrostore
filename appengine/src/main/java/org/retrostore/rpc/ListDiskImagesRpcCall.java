/*
 * Copyright 2017, Sascha Häberling
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

package org.retrostore.rpc;

import org.retrostore.data.app.AppManagement;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.data.app.MediaImage;
import org.retrostore.data.user.UserAccountType;
import org.retrostore.request.Responder;
import org.retrostore.rpc.internal.RpcCall;
import org.retrostore.rpc.internal.RpcParameters;

import java.util.Map;
import java.util.Optional;

/**
 * Lists data about the disk images of an app.
 */
public class ListDiskImagesRpcCall implements RpcCall<RpcParameters> {
  public static class DiskImageInfo {
    int id;
    long sizeInBytes;
    String label;
    String name;
    long uploadTime;
  }

  private static final String[] DISK_IMAGE_LABELS = {
      "Disk Image #1",
      "Disk Image #2",
      "Disk Image #3",
      "Disk Image #4",
      "Cassette image",
      "Command image",
      "BASIC image"};
  private final AppManagement mAppManagement;

  public ListDiskImagesRpcCall(AppManagement appManagement) {
    mAppManagement = appManagement;
  }


  @Override
  public String getName() {
    return "listDiskImages";
  }

  @Override
  public boolean isPermitted(UserAccountType type) {
    return type != UserAccountType.NO_ACCOUNT && type != UserAccountType.NOT_LOGGED_IN;
  }

  @Override
  public void call(RpcParameters params, Responder responder) {
    Optional<String> appIdOpt = params.getString("appId");
    if (!appIdOpt.isPresent()) {
      responder.respondBadRequest("No valid 'appId' given.");
      return;
    }

    Optional<AppStoreItem> appOpt = mAppManagement.getAppById(appIdOpt.get());
    if (!appOpt.isPresent()) {
      responder.respondBadRequest("App with given ID not found.");
      return;
    }

    AppStoreItem.Trs80Extension trs80Extension = appOpt.get().trs80Extension;
    if (trs80Extension == null) {
      responder.respondBadRequest("App has no trs80Extension");
      return;
    }
    Map<Long, MediaImage> mediaImages = mAppManagement.getMediaImagesForApp(appIdOpt.get());

    DiskImageInfo[] infos = new DiskImageInfo[7];
    for (int i = 0; i < trs80Extension.disk.length; ++i) {
      infos[i] = new DiskImageInfo();
      infos[i].id = i;
      infos[i].label = DISK_IMAGE_LABELS[i];
      fillInfo(mediaImages.get(trs80Extension.disk[i]), infos[i]);
    }

    // Casette.
    infos[4] = new DiskImageInfo();
    infos[4].id = 4;
    infos[4].label = DISK_IMAGE_LABELS[4];
    fillInfo(mediaImages.get(trs80Extension.cassette), infos[4]);

    // Command image.
    infos[5] = new DiskImageInfo();
    infos[5].id = 5;
    infos[5].label = DISK_IMAGE_LABELS[5];
    fillInfo(mediaImages.get(trs80Extension.command), infos[5]);

    // BASIC image.
    infos[6] = new DiskImageInfo();
    infos[6].id = 6;
    infos[6].label = DISK_IMAGE_LABELS[6];
    fillInfo(mediaImages.get(trs80Extension.basic), infos[6]);
    responder.respondJson(infos);
  }

  private void fillInfo(MediaImage mediaImage, DiskImageInfo info) {
    if (mediaImage != null) {
      info.name = mediaImage.filename;
      info.sizeInBytes = mediaImage.data.length;
      info.uploadTime = mediaImage.uploadTime;
    }
  }
}
