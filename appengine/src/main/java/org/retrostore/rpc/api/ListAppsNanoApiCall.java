/*
 * Copyright 2017, Sascha Häberling
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *        http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.retrostore.rpc.api;

import com.google.protobuf.InvalidProtocolBufferException;
import org.retrostore.client.common.proto.ApiResponseAppsNano;
import org.retrostore.client.common.proto.AppNano;
import org.retrostore.client.common.proto.ListAppsParams;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.request.RequestData;
import org.retrostore.request.Response;
import org.retrostore.resources.ImageServiceWrapper;

import java.util.ArrayList;
import java.util.List;
import java.util.logging.Logger;

/**
 * API call to list apps from the store. This is the NANO version which uses a more memory friendly
 * data structure.
 */
public class ListAppsNanoApiCall extends ListAppsApiCall {
  private static final Logger LOG = Logger.getLogger("ListAppsNanoApiCall");

  public ListAppsNanoApiCall(AppManagement appManagement, ImageServiceWrapper imageService) {
    super(appManagement, imageService);
  }

  @Override
  public String getName() {
    return "listAppsNano";
  }

  @Override
  public Response call(final RequestData data) {
    ListAppsParams params = getAppIdFromParams(data.getRawBody());
    return responder -> responder.respondProto(callInternal(params));
  }

  // PB parameter API only (this call was created after the change).
  private ListAppsParams getAppIdFromParams(byte[] data) {
    try {
      return ListAppsParams.parseFrom(data);
    } catch (InvalidProtocolBufferException e) {
      LOG.warning("Cannot parse ListAppsParam.");
      return null;
    }
  }

  private ApiResponseAppsNano callInternal(ListAppsParams params) {
    ApiResponseAppsNano.Builder response = ApiResponseAppsNano.newBuilder();
    List<AppStoreItem> filteredApps = null;
    try {
      filteredApps = listInternal(params);
    } catch (Exception e) {
      return response.setSuccess(false).setMessage(e.getMessage()).build();
    }

    long tPreBuilding = System.currentTimeMillis();
    List<AppNano.Builder> apps = new ArrayList<>();
    for (int i = params.getStart(); i < params.getStart() + params.getNum() && i < filteredApps.size(); ++i) {
      AppStoreItem appStoreItem = filteredApps.get(i);
      apps.add(mApiHelper.convertToNano(appStoreItem));
    }
    LOG.info(String.format("[Perf] Building list took %d ms.", (System
        .currentTimeMillis() - tPreBuilding)));

    for (AppNano.Builder app : apps) {
      response.addApp(app.build());
    }
    return response.setSuccess(true).setMessage("All good :-)").build();
  }
}
