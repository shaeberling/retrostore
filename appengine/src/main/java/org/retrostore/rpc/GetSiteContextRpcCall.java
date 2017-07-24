/*
 * Copyright 2016, Sascha Häberling
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
import org.retrostore.data.user.RetroStoreUser;
import org.retrostore.data.user.UserAccountType;
import org.retrostore.data.user.UserManagement;
import org.retrostore.request.Responder;
import org.retrostore.rpc.internal.RpcCall;
import org.retrostore.rpc.internal.RpcParameters;

/**
 * Responds with a context object that is requested from the site when loaded.
 */
public class GetSiteContextRpcCall implements RpcCall<RpcParameters> {
  private final UserManagement mUserManagement;

  public GetSiteContextRpcCall(UserManagement userManagement) {
    mUserManagement = userManagement;
  }

  private static class SiteContext {
    String firstName;
  }

  @Override
  public String getName() {
    return "getSiteContext";
  }

  @Override
  public boolean isPermitted(UserAccountType type) {
    // Any user can make this call, as long as they are logged in.
    return type != UserAccountType.NO_ACCOUNT && type != UserAccountType.NOT_LOGGED_IN;
  }

  @Override
  public void call(RpcParameters params, Responder responder) {
    SiteContext context = new SiteContext();
    Optional<RetroStoreUser> currentUser = mUserManagement.getCurrentUser();
    if (currentUser.isPresent()) {
      context.firstName = currentUser.get().firstName;
    }
    responder.respondJson(context);
  }
}
