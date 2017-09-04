/*
 *  Copyright 2017, Sascha Häberling
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *         http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
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

import java.util.Collections;
import java.util.List;
import java.util.logging.Logger;

/**
 * Used to change the order of screenshots for an app.
 */
public class ReorderScreenshotsRpcCall implements RpcCall<RpcParameters> {
  private static final Logger LOG = Logger.getLogger("ReorderScreensRpc");
  private static final String PARAM_APP_ID = "appId";
  private static final String PARAM_BLOB_KEY = "blobKey";
  private static final String PARAM_DIRECTION = "direction";
  private static final String DIR_UP = "up";
  private static final String DIR_DOWN = "down";

  private final AppManagement mAppManagement;

  public ReorderScreenshotsRpcCall(AppManagement appManagement) {
    mAppManagement = appManagement;
  }

  @Override
  public String getName() {
    return "reorderScreenshots";
  }

  @Override
  public boolean isPermitted(UserAccountType type) {
    return type != UserAccountType.NO_ACCOUNT && type != UserAccountType.NOT_LOGGED_IN;
  }

  @Override
  public void call(RpcParameters params, Responder responder) {
    Optional<Long> appIdOpt = NumUtil.parseLong(params.getString(PARAM_APP_ID));
    if (!appIdOpt.isPresent()) {
      respondAndLogbadRequest("No valid 'appId' given.", responder);
      return;
    }
    Optional<AppStoreItem> appOpt = mAppManagement.getAppById(appIdOpt.get());
    if (!appOpt.isPresent()) {
      respondAndLogbadRequest("App with given ID not found.", responder);
      return;
    }
    Optional<String> blobKeyOpt = params.getString(PARAM_BLOB_KEY);
    if (!blobKeyOpt.isPresent()) {
      respondAndLogbadRequest("No 'blobKey' found.", responder);
      return;
    }

    Optional<String> directionOpt = params.getString(PARAM_DIRECTION);
    if (!directionOpt.isPresent()) {
      respondAndLogbadRequest("No 'direction' found.", responder);
      return;
    }

    List<String> blobKeys = appOpt.get().screenshotsBlobKeys;
    String blobKey = blobKeyOpt.get();

    int keyIndex = blobKeys.indexOf(blobKey);
    if (keyIndex < 0) {
      respondAndLogbadRequest(
          String.format("Blob key '%s' not found for app '%s'.", blobKey, appIdOpt.get()),
          responder);
      return;
    }

    String direction = directionOpt.get().toLowerCase();
    switch (direction) {
      case DIR_UP:
        if (keyIndex == 0) {
          LOG.info("Cannot move screenshot at index 0 up.");
          return;
        }
        Collections.swap(blobKeys, keyIndex, keyIndex - 1);
        break;
      case DIR_DOWN:
        if (keyIndex >= blobKeys.size() - 1) {
          LOG.info("Cannot move screenshot down. Already at end.");
          return;
        }
        Collections.swap(blobKeys, keyIndex, keyIndex + 1);
        break;
      default:
        respondAndLogbadRequest("Illegal 'direction': " + direction, responder);
        return;
    }
    mAppManagement.addOrChangeApp(appOpt.get());
  }

  private void respondAndLogbadRequest(String msg, Responder responder) {
    LOG.warning(msg);
    responder.respondBadRequest(msg);
  }

}
