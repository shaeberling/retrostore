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

import org.retrostore.data.app.AppManagement;
import org.retrostore.data.user.UserAccountType;
import org.retrostore.request.Responder;
import org.retrostore.rpc.internal.RpcCall;
import org.retrostore.rpc.internal.RpcParameters;

import java.util.Optional;
import java.util.logging.Logger;

/**
 * Call to delete a screenshot.
 */
public class DeleteScreenshotRpcCall implements RpcCall<RpcParameters> {
  private static final Logger LOG = Logger.getLogger("DelScreenshotRpc");
  private static final String PARAM_APP_ID = "appId";
  private static final String PARAM_BLOB_KEY = "blobKey";

  private final AppManagement mAppManagement;

  public DeleteScreenshotRpcCall(AppManagement appManagement) {
    mAppManagement = appManagement;
  }

  @Override
  public String getName() {
    return "deleteScreenshot";
  }

  @Override
  public boolean isPermitted(UserAccountType type) {
    return type != UserAccountType.NO_ACCOUNT && type != UserAccountType.NOT_LOGGED_IN;
  }

  @Override
  public void call(RpcParameters params, Responder responder) {
    Optional<String> appIdOpt = params.getString(PARAM_APP_ID);
    Optional<String> blobKeyOpt = params.getString(PARAM_BLOB_KEY);

    if (!appIdOpt.isPresent()) {
      String msg = "No 'appId' given for deleteScreenshot request.";
      LOG.warning(msg);
      responder.respondBadRequest(msg);
      return;
    }
    if (!blobKeyOpt.isPresent()) {
      String msg = "No 'blobKey' given for deleteScreenshot request.";
      LOG.warning(msg);
      responder.respondBadRequest(msg);
      return;
    }

    String appId = appIdOpt.get();
    String blobKey = blobKeyOpt.get();
    if (!mAppManagement.removeScreenshot(appId, blobKey)) {
      String msg = String.format(
          "Something went wrong deleting screenshot. appId '%s' and blobKey '%s'", appId, blobKey);
      responder.respondBadRequest(msg);
      LOG.warning(msg);
    }
  }
}
