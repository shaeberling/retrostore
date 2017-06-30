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

package org.retrostore.rpc.internal;

import com.google.common.collect.ImmutableList;
import com.google.common.collect.ImmutableMap;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.user.UserManagement;
import org.retrostore.request.RequestData;
import org.retrostore.request.Request;
import org.retrostore.request.Responder;
import org.retrostore.data.user.UserService;
import org.retrostore.rpc.AddEditAppRpcCall;
import org.retrostore.rpc.AddEditUserRpcCall;
import org.retrostore.rpc.AdminUserListRpcCall;
import org.retrostore.rpc.AppListRpcCall;
import org.retrostore.rpc.DeleteAppRpcCall;
import org.retrostore.rpc.DeleteUserRpcCall;
import org.retrostore.rpc.GetAppFormDataRpcCall;
import org.retrostore.rpc.GetSiteContextRpcCall;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.logging.Logger;

/**
 * Serves RPC calls
 */
public class RpcCallRequest implements Request {
  private static final Logger LOG = Logger.getLogger("RpcCallRequest");

  private static final String RPC_PREFIX = "/rpc";
  private static final String RPC_METHOD_PARAM = "m";

  private final Map<String, RpcCall> mRpcCalls;


  public RpcCallRequest(UserManagement userManagement, AppManagement appManagement) {
    // Note: Add new RPC calls here.
    List<RpcCall> calls = ImmutableList.of(
        new AdminUserListRpcCall(userManagement),
        new GetSiteContextRpcCall(userManagement),
        new AddEditUserRpcCall(userManagement),
        new AddEditAppRpcCall(appManagement, userManagement),
        new GetAppFormDataRpcCall(appManagement),
        new DeleteUserRpcCall(userManagement),
        new AppListRpcCall(appManagement),
        new DeleteAppRpcCall(appManagement));

    Map<String, RpcCall> callsMapped = new HashMap<>();
    for (RpcCall call : calls) {
      if (callsMapped.containsKey(call.getName())) {
        LOG.severe("RPC call name conflict: " + call.getName());
      }
      callsMapped.put(call.getName(), call);
    }
    mRpcCalls = ImmutableMap.copyOf(callsMapped);
  }

  @Override
  public boolean serveUrl(RequestData requestData, Responder responder,
                          UserService accountTypeProvider) {
    String url = requestData.getUrl();
    if (!url.startsWith(RPC_PREFIX)) {
      return false;
    }

    String method = requestData.getParameter(RPC_METHOD_PARAM);
    if (method == null) {
      responder.respondBadRequest("No method name specified.");
    } else if (!mRpcCalls.containsKey(method)) {
      responder.respondBadRequest(String.format("RPC method '%s' not found.", method));
    } else {
      RpcCall rpcCall = mRpcCalls.get(method);
      if (!rpcCall.isPermitted(accountTypeProvider.getForCurrentUser())) {
        responder.respondBadRequest("Current user not permitted.");
      } else {
        RpcParametersImpl params = new RpcParametersImpl(requestData);
        rpcCall.call(params, responder);
      }
    }
    return true;
  }
}
