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

package org.retrostore.rpc.api;

import com.google.common.base.Strings;
import com.google.gson.Gson;
import com.google.protobuf.InvalidProtocolBufferException;
import org.retrostore.client.common.GetAppApiParams;
import org.retrostore.client.common.proto.ApiResponseApps;
import org.retrostore.client.common.proto.GetAppParams;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.request.RequestData;
import org.retrostore.request.Response;
import org.retrostore.resources.ImageServiceWrapper;
import org.retrostore.rpc.internal.ApiCall;

import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Returns data for a single app, excluding the disk images.
 */
public class GetAppApiCall implements ApiCall {
  private static final Logger LOG = Logger.getLogger("GetAppApiCall");

  private final AppManagement mAppManagement;
  private final ApiHelper mApiHelper;

  public GetAppApiCall(AppManagement appManagement, ImageServiceWrapper imageService) {
    mAppManagement = appManagement;
    mApiHelper = new ApiHelper(appManagement, imageService);
  }

  @Override
  public String getName() {
    return "getApp";
  }

  @Override
  public Response call(RequestData params) {
    String appId = getAppIdFromParams(params.getRawBody());
    final ApiResponseApps responseApp = callInternal(appId);
    return responder -> responder.respondProto(responseApp);
  }

  private ApiResponseApps callInternal(String appId) {
    ApiResponseApps.Builder response = ApiResponseApps.newBuilder();
    if (Strings.isNullOrEmpty(appId)) {
      return response.setSuccess(false).setMessage("Invalid request, appId missing.").build();
    }

    java.util.Optional<AppStoreItem> appById = mAppManagement.getAppById(appId);
    if (!appById.isPresent()) {
      return response.setSuccess(false).setMessage("App not found.").build();
    }
    response.addApp(mApiHelper.convert(appById.get()));
    return response.setSuccess(true).setMessage("All good :-)").build();
  }

  // Works with the old (JSON) and new (PB) parameter API.
  private String getAppIdFromParams(byte[] data) {
    GetAppParams params;
    try {
      params = GetAppParams.parseFrom(data);
      return params.getAppId();
    } catch (InvalidProtocolBufferException e) {
      // If this fails, try to parse it as JSON.
      GetAppApiParams oldParams = parseLegacyParams(new String(data));
      if (oldParams != null) {
        LOG.warning("Legacy parameters used.");
        return oldParams.appId;
      }
      LOG.severe("Cannot parse parameters.");

    }
    return null;
  }


  private GetAppApiParams parseLegacyParams(String params) {
    try {
      return (new Gson()).fromJson(params, GetAppApiParams.class);
    } catch (Exception ex) {
      LOG.log(Level.WARNING, "Cannot parse params", ex);
      return null;
    }
  }
}
