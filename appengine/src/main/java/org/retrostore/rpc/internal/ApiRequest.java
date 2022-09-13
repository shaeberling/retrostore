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
import org.retrostore.data.xray.StateManagement;
import org.retrostore.request.Request;
import org.retrostore.request.RequestData;
import org.retrostore.request.Responder;
import org.retrostore.resources.ImageServiceWrapper;
import org.retrostore.rpc.api.DownloadStateApiCall;
import org.retrostore.rpc.api.FetchMediaImagesApiCall;
import org.retrostore.rpc.api.GetAppApiCall;
import org.retrostore.rpc.api.ListAppsApiCall;
import org.retrostore.rpc.api.ListAppsNanoApiCall;
import org.retrostore.rpc.api.UploadStateApiCall;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.logging.Logger;

/**
 * API requests are coming from external clients and are handled through this class.
 */
public class ApiRequest implements Request {
  private static final Logger LOG = Logger.getLogger("ApiRequest");

  private static final String API_PREFIX = "/api";
  private final Map<String, ApiCall> mApiCalls;

  public ApiRequest(AppManagement appManagement, ImageServiceWrapper imageService,
                    StateManagement stateManagement) {
    List<ApiCall> calls = ImmutableList.<ApiCall>of(
        new GetAppApiCall(appManagement, imageService),
        new ListAppsApiCall(appManagement, imageService),
        new ListAppsNanoApiCall(appManagement, imageService),
        new FetchMediaImagesApiCall(appManagement),
        new UploadStateApiCall(stateManagement),
        new DownloadStateApiCall(stateManagement));

    Map<String, ApiCall> callsMapped = new HashMap<>();
    for (ApiCall call : calls) {
      if (callsMapped.containsKey(call.getName())) {
        LOG.severe("API call name conflict: " + call.getName());
      }
      callsMapped.put(call.getName(), call);
    }
    mApiCalls = ImmutableMap.copyOf(callsMapped);
  }


  @Override
  public boolean serveUrl(RequestData requestData, Responder responder, UserService userService) {
    String url = requestData.getUrl();
    if (!url.startsWith(API_PREFIX)) {
      return false;
    }

    String[] urlParts = url.substring(1).split("/");
    if (urlParts.length < 2) {
      LOG.info(String.format("API url does not match: '%s'.", url));
      return false;
    }
    String method = urlParts[1];
    LOG.info(String.format("Method is '%s'.", method));

    if (Strings.isNullOrEmpty(method)) {
      responder.respondBadRequest("No method name specified.");
    } else if (!mApiCalls.containsKey(method)) {
      responder.respondBadRequest(String.format("RPC method '%s' not found.", method));
    } else {
      ApiCall apiCall = mApiCalls.get(method);
      apiCall.call(requestData).respond(responder);
    }
    return true;
  }
}
