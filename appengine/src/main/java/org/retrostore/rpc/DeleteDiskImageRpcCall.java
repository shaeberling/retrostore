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

/**
 * Call to delete a disk image.
 */
public class DeleteDiskImageRpcCall implements RpcCall<RpcParameters> {
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
    Optional<Long> appIdOpt = params.getLong("appId");
    Optional<Integer> diskImageOpt = params.getInt("diskImageNo");

    if (!appIdOpt.isPresent() || !diskImageOpt.isPresent()) {
      responder.respondBadRequest("Both 'appId' and 'diskImageNo' must be provided.");
      return;
    }

    Optional<AppStoreItem> appOpt = mAppManagement.getAppById(appIdOpt.get());
    if (!appOpt.isPresent()) {
      responder.respondBadRequest(String.format("App with ID '%d' not found.", appIdOpt.get()));
      return;
    }

    int diskImageNo = diskImageOpt.get();
    if (diskImageNo < 0 || diskImageNo > 4) {
      responder.respondBadRequest(String.format("Invalid diskImageNo: '%d'.", diskImageNo));
      return;
    }

    AppStoreItem app = appOpt.get();
    if (app.configuration == null) {
      return;
    }

    if (diskImageNo < 4) {
      if (app.configuration.disk != null) {
        app.configuration.disk[diskImageNo] = null;
      }
    } else if (diskImageNo == 4) {
      app.configuration.cassette = null;
    }
    mAppManagement.addOrChangeApp(app);
  }
}
