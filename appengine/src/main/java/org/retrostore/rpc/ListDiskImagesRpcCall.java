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

import com.google.common.base.Optional;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.data.user.UserAccountType;
import org.retrostore.request.Responder;
import org.retrostore.rpc.internal.RpcCall;
import org.retrostore.rpc.internal.RpcParameters;
import org.retrostore.util.NumUtil;

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
      "Cassette image"};
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
    Optional<Long> appIdOpt = NumUtil.parseLong(params.getString("appId"));
    if (!appIdOpt.isPresent()) {
      responder.respondBadRequest("No valid 'appId' given.");
      return;
    }

    Optional<AppStoreItem> appOpt = mAppManagement.getAppById(appIdOpt.get());
    if (!appOpt.isPresent()) {
      responder.respondBadRequest("App with given ID not found.");
      return;
    }

    AppStoreItem.Configuration configuration = appOpt.get().configuration;
    if (configuration == null) {
      responder.respondBadRequest("App has no configuration");
      return;
    }

    DiskImageInfo[] infos = new DiskImageInfo[5];
    for (int i = 0; i < 4; ++i) {
      infos[i] = new DiskImageInfo();
      infos[i].id = i;
      infos[i].label = DISK_IMAGE_LABELS[i];

      if (configuration.disk != null && configuration.disk[i] != null) {
        infos[i].name = configuration.disk[i].filename;
        infos[i].sizeInBytes = configuration.disk[i].data.length;
        infos[i].uploadTime = configuration.disk[i].uploadTime;
      }
    }
    infos[4] = new DiskImageInfo();
    infos[4].id = 4;
    infos[4].label = DISK_IMAGE_LABELS[4];
    if (configuration.cassette != null) {
      infos[4].name = configuration.cassette.filename;
      infos[4].sizeInBytes = configuration.cassette.data.length;
      infos[4].uploadTime = configuration.cassette.uploadTime;
    }
    responder.respondObject(infos);
  }
}
