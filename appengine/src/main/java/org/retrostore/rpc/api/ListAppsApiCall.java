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

import com.google.common.collect.ImmutableList;
import com.google.gson.Gson;
import org.retrostore.client.common.ApiResponse;
import org.retrostore.client.common.ListAppsApiParams;
import org.retrostore.client.common.RetrostoreAppItem;
import org.retrostore.client.common.RetrostoreAppItem.MediaImage.Type;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.request.RequestData;
import org.retrostore.rpc.internal.ApiCall;

import java.util.ArrayList;
import java.util.List;
import java.util.logging.Level;
import java.util.logging.Logger;

import static org.retrostore.client.common.RetrostoreAppItem.MediaImage.Type.CASETTE;
import static org.retrostore.client.common.RetrostoreAppItem.MediaImage.Type.DISK;

/**
 * API call to list apps from the store.
 */
public class ListAppsApiCall implements ApiCall<RetrostoreAppItem> {
  private static final Logger LOG = Logger.getLogger("ListAppsApiCall");
  private final AppManagement mAppManagement;

  public ListAppsApiCall(AppManagement appManagement) {
    mAppManagement = appManagement;
  }

  @Override
  public String getName() {
    return "listApps";
  }

  @Override
  public ApiResponse<RetrostoreAppItem> call(RequestData data) {
    ListAppsApiParams params = parseParams(data.getBody());
    if (params == null) {
      return new ApiResponse<>("Cannot parse parameters.");
    }

    // TODO: This is not efficient once we have a large number of apps.
    List<AppStoreItem> allApps = mAppManagement.getAllApps();
    if (allApps.size() - 1 < params.start) {
      return new ApiResponse<>("Parameter 'start' out of range");
    }

    List<RetrostoreAppItem> appItems = new ArrayList<>();
    for (int i = params.start; i < params.start + params.num && i < allApps.size(); ++i) {
      AppStoreItem app = allApps.get(i);
      RetrostoreAppItem item = new RetrostoreAppItem();

      item.id = app.id;
      item.name = app.listing.name;
      item.version = app.listing.versionString;
      item.description = app.listing.description;
      // TODO: Add support for screenshots.
      item.screenshotUrls = new String[0];

      // Create the list of media images for this app (disks and casettes).
      ImmutableList.Builder<RetrostoreAppItem.MediaImage> mediaImagesForClient =
          ImmutableList.builder();
      for (AppStoreItem.MediaImage mediaImage : app.configuration.disk) {
        if (mediaImage != null) {
          mediaImagesForClient.add(toClientType(mediaImage, DISK));
        }
      }

      AppStoreItem.MediaImage cassette = app.configuration.cassette;
      if (cassette != null) {
        toClientType(cassette, CASETTE);
      }
      item.mediaImages = mediaImagesForClient.build();
      appItems.add(item);
    }
    return new ApiResponse<>(true, "All good", appItems);
  }

  private ListAppsApiParams parseParams(String params) {
    try {
      return (new Gson()).fromJson(params, ListAppsApiParams.class);
    } catch (Exception ex) {
      LOG.log(Level.WARNING, "Cannot parse params", ex);
      return null;
    }
  }

  private static RetrostoreAppItem.MediaImage toClientType(AppStoreItem.MediaImage mediaImage,
                                                           Type type) {
    return new RetrostoreAppItem.MediaImage(
        type, mediaImage.filename, mediaImage.data, mediaImage.uploadTime, mediaImage.description);
  }
}
