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
import org.retrostore.data.user.UserAccountType;
import org.retrostore.request.Responder;
import org.retrostore.rpc.internal.RpcCall;
import org.retrostore.rpc.internal.RpcParameters;

import java.util.Optional;
import java.util.logging.Logger;

/**
 * Call to delete a disk image.
 */
public class DeleteDiskImageRpcCall implements RpcCall<RpcParameters> {
  private static final Logger LOG = Logger.getLogger("DelDiskImgRpc");
  private final AppManagement mAppManagement;

  public DeleteDiskImageRpcCall(AppManagement appManagement) {
    mAppManagement = appManagement;
  }

  @Override
  public String getName() {
    return "deleteDiskImage";
  }

  @Override
  public boolean isPermitted(UserAccountType type) {
    return type != UserAccountType.NO_ACCOUNT && type != UserAccountType.NOT_LOGGED_IN;
  }

  @Override
  public void call(RpcParameters params, Responder responder) {
    Optional<String> appIdOpt = params.getString("appId");
    Optional<Integer> diskImageOpt = params.getInt("diskImageNo");

    if (!appIdOpt.isPresent() || !diskImageOpt.isPresent()) {
      String msg = "Both 'appId' and 'diskImageNo' must be provided.";
      responder.respondBadRequest(msg);
      LOG.warning(msg);
      return;
    }

    Optional<AppStoreItem> appOpt = mAppManagement.getAppById(appIdOpt.get());
    if (!appOpt.isPresent()) {
      String msg = String.format("App with ID '%s' not found.", appIdOpt.get());
      responder.respondBadRequest(msg);
      LOG.warning(msg);
      return;
    }

    int diskImageNo = diskImageOpt.get();
    if (diskImageNo < 0 || diskImageNo > 5) {
      String msg = String.format("Invalid diskImageNo: '%d'.", diskImageNo);
      responder.respondBadRequest(msg);
      LOG.warning(msg);
      return;
    }

    AppStoreItem app = appOpt.get();
    if (app.trs80Extension == null) {
      return;
    }

    if (diskImageNo < 4) {
      if (app.trs80Extension.disk != null) {
        long mediaId = app.trs80Extension.disk[diskImageNo];
        mAppManagement.deleteMediaImage(mediaId);
        app.trs80Extension.disk[diskImageNo] = 0;
      }
    } else if (diskImageNo == 4) {
      long mediaId = app.trs80Extension.cassette;
      mAppManagement.deleteMediaImage(mediaId);
      app.trs80Extension.cassette = 0;
    } else if (diskImageNo == 5) {
      long mediaId = app.trs80Extension.command;
      mAppManagement.deleteMediaImage(mediaId);
      app.trs80Extension.command = 0;
    }
    mAppManagement.addOrChangeApp(app);
  }
}
