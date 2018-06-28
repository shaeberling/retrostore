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

import com.google.common.base.Strings;
import com.google.common.collect.ImmutableList;
import com.google.common.collect.ImmutableMap;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.user.UserService;
import org.retrostore.request.Request;
import org.retrostore.request.RequestData;
import org.retrostore.request.Responder;
import org.retrostore.rpc.UploadDiskImageRpcCall;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.logging.Logger;

/**
 * Serves uploads requests through POST.
 */
public class PostUploadRequest implements Request {
  private static final Logger LOG = Logger.getLogger("PostUploadRequest");
  private static final String RPC_PREFIX = "/post";

  private final Map<String, RpcCall> mRpcCalls;

  public PostUploadRequest(AppManagement appManagement) {
    List<RpcCall<RequestData>> calls =
        ImmutableList.of(new UploadDiskImageRpcCall(appManagement));
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
  public boolean serveUrl(RequestData requestData, Responder responder, UserService userService) {
    String url = requestData.getUrl();
    if (!url.startsWith(RPC_PREFIX)) {
      return false;
    }

    String[] urlParts = url.substring(1).split("/");
    if (urlParts.length < 2) {
      LOG.info(String.format("POST url does not match: '%s'.", url));
      return false;
    }
    String method = urlParts[1];
    LOG.info(String.format("Method is '%s'.", method));

    if (Strings.isNullOrEmpty(method)) {
      responder.respondBadRequest("No method name specified.");
    } else if (!mRpcCalls.containsKey(method)) {
      responder.respondBadRequest(String.format("RPC method '%s' not found.", method));
    } else {
      RpcCall rpcCall = mRpcCalls.get(method);
      if (!rpcCall.isPermitted(userService.getForCurrentUser())) {
        responder.respondBadRequest("Current user not permitted.");
      } else {
        rpcCall.call(requestData, responder);
      }
    }
    return true;
  }
}
