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
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.user.UserAccountType;
import org.retrostore.request.Responder;
import org.retrostore.rpc.internal.RpcCall;
import org.retrostore.rpc.internal.RpcParameters;
import org.retrostore.rpc.internal.RpcResponse;

/**
 * Deletes the app with the given ID.
 */
public class DeleteAppRpcCall implements RpcCall {
  private static final class Data {
    public String id;
  }

  private final AppManagement mAppManagement;

  public DeleteAppRpcCall(AppManagement appManagement) {
    mAppManagement = appManagement;
  }

  @Override
  public String getName() {
    return "deleteApp";
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
      if (Strings.isNullOrEmpty(data.id)) {
        RpcResponse.respond(false, "No email address given.", responder);
        return;
      }

      try {
        long id = Long.parseLong(data.id);
        mAppManagement.removeApp(id);
        RpcResponse.respond(true, "App deleted", responder);
      } catch (NumberFormatException ex) {
        RpcResponse.respond(false, String.format("Invalid ID '%s' ", data.id), responder);
      }
    } catch (JsonSyntaxException e) {
      RpcResponse.respond(false, "Invalid JSON data", responder);
    }
  }
}
