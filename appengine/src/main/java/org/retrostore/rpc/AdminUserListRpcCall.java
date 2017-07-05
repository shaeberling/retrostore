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

import org.retrostore.data.user.UserAccountType;
import org.retrostore.data.user.UserManagement;
import org.retrostore.request.Responder;
import org.retrostore.rpc.internal.RpcCall;
import org.retrostore.rpc.internal.RpcParameters;

import static com.google.common.base.Preconditions.checkNotNull;

/**
 * Return a list of RetroStore users.
 */
public class AdminUserListRpcCall implements RpcCall<RpcParameters> {
  private final UserManagement mUserManagement;

  public AdminUserListRpcCall(UserManagement userManagement) {
    mUserManagement = checkNotNull(userManagement);
  }

  @Override
  public String getName() {
    return "userlist";
  }

  @Override
  public boolean isPermitted(UserAccountType type) {
    return type == UserAccountType.ADMIN;
  }

  @Override
  public void call(RpcParameters params, Responder responder) {
    responder.respondObject(mUserManagement.getAllUsers());
  }
}
