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

package org.puder.trs80.appstore.rpc.internal;

import com.google.common.collect.ImmutableList;
import com.google.common.collect.ImmutableMap;
import org.puder.trs80.appstore.Request;
import org.puder.trs80.appstore.RequestServing;
import org.puder.trs80.appstore.Responder;
import org.puder.trs80.appstore.data.user.UserService;
import org.puder.trs80.appstore.rpc.AdminUserListRpcCall;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.logging.Logger;

/**
 * Serves RPC calls
 */
public class RpcCallServing implements RequestServing {
  private static final Logger LOG = Logger.getLogger("RpcCallServing");

  private static final String RPC_PREFIX = "/rpc";
  private static final String RPC_METHOD_PARAM = "m";

  private final Map<String, RpcCall> mRpcCalls = getRpcCalls();

  private static Map<String, RpcCall> getRpcCalls() {
    // Note: Add new RPC calls here.
    List<RpcCall> calls = ImmutableList.<RpcCall>of(new AdminUserListRpcCall());

    Map<String, RpcCall> callsMapped = new HashMap<>();
    for (RpcCall call : calls) {
      if (callsMapped.containsKey(call.getName())) {
        LOG.severe("RPC call name conflict: " + call.getName());
      }
      callsMapped.put(call.getName(), call);
    }
    return ImmutableMap.copyOf(callsMapped);
  }

  @Override
  public boolean serveUrl(Request request, Responder responder, UserService accountTypeProvider) {
    String url = request.getUrl();
    if (!url.startsWith(RPC_PREFIX)) {
      return false;
    }

    String method = request.getParameter(RPC_METHOD_PARAM);
    if (method == null) {
      responder.respondBadRequest("No method name specified.");
    } else if (!mRpcCalls.containsKey(method)) {
      responder.respondBadRequest(String.format("RPC method '%s' not found.", method));
    } else {
      RpcCall rpcCall = mRpcCalls.get(method);
      if (!rpcCall.isPermitted(accountTypeProvider.getForCurrentUser())) {
        responder.respondBadRequest("Current user not permitted.");
      } else {
        RpcParametersImpl params = new RpcParametersImpl(request);
        rpcCall.call(params, responder);
      }
    }
    return true;
  }
}
