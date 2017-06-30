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
import com.google.gson.Gson;
import com.google.gson.JsonSyntaxException;
import org.retrostore.data.user.RetroStoreUser;
import org.retrostore.data.user.UserAccountType;
import org.retrostore.data.user.UserManagement;
import org.retrostore.request.Responder;
import org.retrostore.rpc.internal.RpcCall;
import org.retrostore.rpc.internal.RpcParameters;
import org.retrostore.rpc.internal.RpcResponse;

import java.util.logging.Logger;

/**
 * Adds a new or edits an existing user.
 */
public class AddEditUserRpcCall implements RpcCall {
  private static final class Data {
    public String email;
    public String firstName;
    public String lastName;
    public String type;
  }

  private static final Logger LOG = Logger.getLogger("AddEditUserRpcCall");
  private final UserManagement mUserManagement;

  public AddEditUserRpcCall(UserManagement userManagement) {
    mUserManagement = userManagement;
  }

  @Override
  public String getName() {
    return "addEditUser";
  }

  @Override
  public boolean isPermitted(UserAccountType type) {
    return type == UserAccountType.ADMIN;
  }

  @Override
  public void call(RpcParameters params, Responder responder) {
    String body = params.getBody();
    if (Strings.isNullOrEmpty(body)) {
      // TODO: Make #call return RpcResponse and get rid of responder.
      RpcResponse.respond(false, "No data received", responder);
      return;
    }

    try {
      Data data = (new Gson()).fromJson(body, Data.class);
      if (Strings.isNullOrEmpty(data.email)) {
        RpcResponse.respond(false, "E-Mail missing", responder);
        return;
      }
      if (!isEmailValid(data.email)) {
        RpcResponse.respond(false, "E-Mail invalid", responder);
        return;
      }
      if (Strings.isNullOrEmpty(data.firstName)) {
        RpcResponse.respond(false, "First name missing", responder);
        return;
      }
      if (Strings.isNullOrEmpty(data.lastName)) {
        RpcResponse.respond(false, "Last name missing", responder);
        return;
      }
      if (Strings.isNullOrEmpty(data.type)) {
        RpcResponse.respond(false, "Account type missing", responder);
        return;
      }

      UserAccountType userAccountType;
      try {
        userAccountType = UserAccountType.valueOf(data.type);
      } catch (IllegalArgumentException ex) {
        RpcResponse.respond(false, "Account type invalid", responder);
        return;
      }


      RetroStoreUser user = new RetroStoreUser();
      user.email = data.email;
      user.firstName = data.firstName;
      user.lastName = data.lastName;
      user.type = userAccountType;
      mUserManagement.addOrChangeUser(user);

      RpcResponse.respond(true, "User changed/added", responder);
    } catch (JsonSyntaxException e) {
      RpcResponse.respond(false, "Invalid JSON data", responder);
    }
  }

  /**
   * Basic (and incomplete) check for whether the e-mail address is valid.
   */
  private static boolean isEmailValid(String email) {
    if (Strings.isNullOrEmpty(email) || !email.contains("@")) {
      return false;
    }

    String[] split = email.split("@");
    if (split.length != 2) {
      return false;
    }

    if (!split[1].contains(".")) {
      return false;
    }
    return true;
  }
}
