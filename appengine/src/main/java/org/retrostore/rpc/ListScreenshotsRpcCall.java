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

/**
 * Serves a list of screenshots for a given app.
 */
public class ListScreenshotsRpcCall implements RpcCall<RpcParameters> {
  private static final String PARAM_APP_ID = "appId";
  private final AppManagement mAppManagement;

  public ListScreenshotsRpcCall(AppManagement appManagement) {
    mAppManagement = appManagement;
  }

  @Override
  public String getName() {
    return "listScreenshots";
  }

  @Override
  public boolean isPermitted(UserAccountType type) {
    return type != UserAccountType.NO_ACCOUNT && type != UserAccountType.NOT_LOGGED_IN;
  }

  @Override
  public void call(RpcParameters params, Responder responder) {
    Optional<Long> appIdOpt = NumUtil.parseLong(params.getString(PARAM_APP_ID));
    if (!appIdOpt.isPresent()) {
      responder.respondBadRequest("No valid 'appId' given.");
      return;
    }
    Optional<AppStoreItem> appOpt = mAppManagement.getAppById(appIdOpt.get());
    if (!appOpt.isPresent()) {
      responder.respondBadRequest("App with given ID not found.");
      return;
    }

    // TODO: Look at ServingUrlOptions for serving a certain size.
    responder.respondJson(appOpt.get().screenshotsBlobKeys);
  }
}
