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

import com.google.common.base.Strings;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.data.user.UserAccountType;
import org.retrostore.request.RequestData;
import org.retrostore.request.RequestData.UploadFile;
import org.retrostore.request.Responder;
import org.retrostore.rpc.internal.RpcCall;
import org.retrostore.util.NumUtil;

import java.util.List;
import java.util.Optional;
import java.util.logging.Logger;

/**
 * Handles disk/cassette uploads.
 */
public class UploadDiskImageRpcCall implements RpcCall<RequestData> {
  private static final Logger LOG = Logger.getLogger("UploadDiskImageRpcCall");
  private final AppManagement mAppManagement;

  public UploadDiskImageRpcCall(AppManagement appManagement) {
    mAppManagement = appManagement;
  }

  @Override
  public String getName() {
    return "uploadDiskImage";
  }

  @Override
  public boolean isPermitted(UserAccountType type) {
    return type != UserAccountType.NO_ACCOUNT && type != UserAccountType.NOT_LOGGED_IN;
  }

  @Override
  public void call(RequestData data, Responder responder) {
    String[] urlParts = data.getUrl().substring(1).split("/");

    if (urlParts.length < 4) {
      responder.respondBadRequest("Not enough parameters.");
      return;
    }

    List<UploadFile> files = data.getFiles();
    if (files.isEmpty()) {
      responder.respondBadRequest("Cannot get filename.");
      return;
    }
    // We expect exactly one file.
    UploadFile file = files.get(0);

    String appIdStr = urlParts[2];
    String diskImageStr = urlParts[3];
    LOG.info(String.format("AppId: '%s', image: '%s'.", appIdStr, diskImageStr));

    LOG.info(String.format("Upload size: '%d bytes'", file.content.length));
    if (file.content.length == 0) {
      responder.respondBadRequest("Content content data.");
      return;
    }

    Optional<Long> diskImageOpt = NumUtil.parseLong(diskImageStr);

    if (Strings.isNullOrEmpty(appIdStr)) {
      responder.respondBadRequest(String.format("Illegal app ID '%s'.", appIdStr));
      return;
    }
    if (!diskImageOpt.isPresent()) {
      responder.respondBadRequest(String.format("Illegal disk image '%s'.", diskImageStr));
      return;
    }

    Optional<AppStoreItem> appOpt = mAppManagement.getAppById(appIdStr);
    if (!appOpt.isPresent()) {
      responder.respondBadRequest(String.format("No app with ID '%s'.", appIdStr));
      return;
    }
    int diskNo = (int) (long) diskImageOpt.get();
    final long now = System.currentTimeMillis();
    AppStoreItem app = appOpt.get();

    // Add the media image to the store.
    long mediaId = mAppManagement.addMediaImage(appIdStr, file.filename, file.content);

    if (diskNo >= 0 && diskNo < 4) {
      if (app.trs80Extension.disk[diskNo] != 0) {
        // Delete the old media image.
        mAppManagement.deleteMediaImage(app.trs80Extension.disk[diskNo]);
      }
      app.trs80Extension.disk[diskNo] = mediaId;
    } else if (diskNo == 4) {
      if (app.trs80Extension.cassette != 0) {
        // Delete the old media image.
        mAppManagement.deleteMediaImage(app.trs80Extension.cassette);
      }
      app.trs80Extension.cassette = mediaId;
    } else if (diskNo == 5) {
      if (app.trs80Extension.command != 0) {
        // Delete the old media image.
        mAppManagement.deleteMediaImage(app.trs80Extension.command);
      }
      app.trs80Extension.command = mediaId;
    } else {
      responder.respondBadRequest(String.format("Illegal disk image number '%d'.", diskNo));
      return;
    }
    mAppManagement.addOrChangeApp(app);
  }

}
