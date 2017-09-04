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

import com.google.common.base.Optional;
import com.google.gson.Gson;
import com.google.protobuf.ByteString;
import org.retrostore.client.common.ListAppsApiParams;
import org.retrostore.client.common.proto.ApiResponseApps;
import org.retrostore.client.common.proto.App;
import org.retrostore.client.common.proto.MediaImage;
import org.retrostore.client.common.proto.MediaType;
import org.retrostore.client.common.proto.Trs80Model;
import org.retrostore.client.common.proto.Trs80Params;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.data.app.Author;
import org.retrostore.request.RequestData;
import org.retrostore.request.Responder;
import org.retrostore.request.Response;
import org.retrostore.resources.ImageServiceWrapper;
import org.retrostore.rpc.internal.ApiCall;

import java.util.List;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * API call to list apps from the store.
 */
public class ListAppsApiCall implements ApiCall<App> {
  private static final Logger LOG = Logger.getLogger("ListAppsApiCall");
  private static final int SCREENSHOT_SIZE = 800;
  private final AppManagement mAppManagement;
  private final ImageServiceWrapper mImageService;

  public ListAppsApiCall(AppManagement appManagement, ImageServiceWrapper imageService) {
    mAppManagement = appManagement;
    mImageService = imageService;
  }

  @Override
  public String getName() {
    return "listApps";
  }

  @Override
  public Response call(RequestData data) {
    final ApiResponseApps responseApps = callInternal(data);
    return new Response() {
      @Override
      public void respond(Responder responder) {
        responder.respondProto(responseApps);
      }
    };
  }

  private ApiResponseApps callInternal(RequestData data) {
    ApiResponseApps.Builder response = ApiResponseApps.newBuilder();
    ListAppsApiParams params = parseParams(data.getBody());
    if (params == null) {
      return response.setSuccess(false).setMessage("Cannot parse parameters.").build();
    }

    // TODO: This is not efficient once we have a large number of apps.
    List<AppStoreItem> allApps = mAppManagement.getAllApps();
    if (allApps.size() - 1 < params.start) {
      return response.setSuccess(false).setMessage("Parameter 'start' out of range").build();
    }

    for (int i = params.start; i < params.start + params.num && i < allApps.size(); ++i) {
      AppStoreItem app = allApps.get(i);
      App.Builder appBuilder = App.newBuilder();

      appBuilder.setId(app.id);
      appBuilder.setName(app.listing.name);
      appBuilder.setVersion(app.listing.versionString);
      appBuilder.setDescription(app.listing.description);
      appBuilder.setReleaseYear(app.listing.releaseYear);
      Optional<Author> author = mAppManagement.getAuthorById(app.listing.authorId);
      if (author.isPresent()) {
        appBuilder.setAuthor(author.get().name);
      }

      // Set the TRS80 related parameters.
      Trs80Params.Builder trsParams = Trs80Params.newBuilder();
      switch (app.configuration.model) {
        default:
        case MODEL_I:
          trsParams.setModel(Trs80Model.MODEL_I);
          break;
        case MODEL_III:
          trsParams.setModel(Trs80Model.MODEL_III);
          break;
        case MODEL_4:
          trsParams.setModel(Trs80Model.MODEL_4);
          break;
        case MODEL_4P:
          trsParams.setModel(Trs80Model.MODEL_4P);
          break;
      }
      appBuilder.setTrs80Params(trsParams);

      for (String blobKey : app.screenshotsBlobKeys) {
        appBuilder.addScreenshotUrl(mImageService.getServingUrl(blobKey, SCREENSHOT_SIZE));
      }

      // Create the list of media images for this app (disks and casettes).
      for (AppStoreItem.MediaImage mediaImage : app.configuration.disk) {
        if (mediaImage != null) {
          appBuilder.addMediaImage(toClientType(mediaImage, MediaType.DISK));
        }
      }

      AppStoreItem.MediaImage cassette = app.configuration.cassette;
      if (cassette != null) {
        appBuilder.addMediaImage(toClientType(cassette, MediaType.CASSETTE));
      }
      response.addApp(appBuilder);
    }

    response.setSuccess(true).setMessage("All good :-)");
    return response.build();
  }

  private ListAppsApiParams parseParams(String params) {
    try {
      return (new Gson()).fromJson(params, ListAppsApiParams.class);
    } catch (Exception ex) {
      LOG.log(Level.WARNING, "Cannot parse params", ex);
      return null;
    }
  }

  private static MediaImage.Builder toClientType(AppStoreItem.MediaImage mediaImage,
                                                 MediaType type) {
    return MediaImage.newBuilder()
        .setType(type)
        .setFilename(mediaImage.filename != null ? mediaImage.filename : "")
        .setData(ByteString.copyFrom(mediaImage.data))
        .setUploadTime(mediaImage.uploadTime)
        .setDescription(mediaImage.description != null ? mediaImage.description : "");
  }
}
