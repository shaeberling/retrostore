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
import com.google.protobuf.ByteString;
import com.google.protobuf.InvalidProtocolBufferException;
import org.retrostore.client.common.FetchMediaImagesApiParams;
import org.retrostore.client.common.proto.ApiResponseMediaImages;
import org.retrostore.client.common.proto.FetchMediaImagesParams;
import org.retrostore.client.common.proto.MediaImage;
import org.retrostore.client.common.proto.MediaType;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.request.RequestData;
import org.retrostore.request.Response;
import org.retrostore.rpc.internal.ApiCall;

import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.logging.Level;
import java.util.logging.Logger;

public class FetchMediaImagesApiCall implements ApiCall {
  private static final Logger LOG = Logger.getLogger("FetchMediaImages");

  private final AppManagement mAppManagement;

  static class Params {
    final String appId;
    final Set<MediaType> types;

    Params(String appId, Set<MediaType> types) {
      this.appId = appId;
      this.types = types;
    }
  }

  public FetchMediaImagesApiCall(AppManagement appManagement) {
    mAppManagement = appManagement;
  }

  @Override
  public String getName() {
    return "fetchMediaImages";
  }

  @Override
  public Response call(RequestData data) {
    Params params = parseParams(data.getRawBody());
    final ApiResponseMediaImages response = callInternal(params);
    return responder -> responder.respondProto(response);
  }

  // Works with the old (JSON) and new (PB) parameter API.
  private Params parseParams(byte[] data) {
    FetchMediaImagesParams params;
    try {
      params = FetchMediaImagesParams.parseFrom(data);
      return new Params(params.getAppId(), new HashSet<>(params.getMediaTypeList()));
    } catch (InvalidProtocolBufferException e) {
      // If this fails, try to parse it as JSON.
      FetchMediaImagesApiParams oldParams = parseLegacyParams(new String(data));
      if (oldParams != null) {
        // Legacy params didn't have media type limits.
        LOG.warning("Legacy parameters used.");
        return new Params(oldParams.appId, new HashSet<>());
      }
      LOG.severe("Cannot parse parameters.");

    }
    return null;
  }

  // Called from FetchMediaImageRefsApiCall, to avoid duplication.
  ApiResponseMediaImages callInternal(Params params) {
    ApiResponseMediaImages.Builder response = ApiResponseMediaImages.newBuilder();
    if (Strings.isNullOrEmpty(params.appId)) {
      return response.setSuccess(false).setMessage("No appId given.").build();
    }

    java.util.Optional<AppStoreItem> appById = mAppManagement.getAppById(params.appId);
    if (!appById.isPresent()) {
      return response.setSuccess(false)
          .setMessage(String.format("Cannot find app with ID '%s'.", params.appId))
          .build();
    }
    AppStoreItem app = appById.get();
    AppStoreItem.Trs80Extension trs80Ext = app.trs80Extension;

    Map<Long, org.retrostore.data.app.MediaImage> mediaImagesForApp =
        mAppManagement.getMediaImagesForApp(app.id);

    // This is TRS80 specific.
    if (params.types.isEmpty() || params.types.contains(MediaType.DISK)) {
      for (int i = 0; i < 4; ++i) {
        MediaImage.Builder mediaImageBld = MediaImage.newBuilder();

        if (trs80Ext.disk.length > i && trs80Ext.disk[i] != 0) {
          if (mediaImagesForApp.containsKey(trs80Ext.disk[i])) {
            convert(mediaImagesForApp.get(trs80Ext.disk[i]), mediaImageBld, MediaType.DISK);
          }
        }
        response.addMediaImage(mediaImageBld);
      }
    }
    if (params.types.isEmpty() || params.types.contains(MediaType.CASSETTE)) {
      MediaImage.Builder mediaImageBld = MediaImage.newBuilder();
      if (trs80Ext.cassette != 0 && mediaImagesForApp.containsKey(trs80Ext.cassette)) {
        convert(mediaImagesForApp.get(trs80Ext.cassette), mediaImageBld, MediaType.CASSETTE);
      }
      response.addMediaImage(mediaImageBld);
    }
    if (params.types.isEmpty() || params.types.contains(MediaType.COMMAND)) {
      MediaImage.Builder mediaImageBld = MediaImage.newBuilder();
      if (trs80Ext.command != 0 && mediaImagesForApp.containsKey(trs80Ext.command)) {
        convert(mediaImagesForApp.get(trs80Ext.command), mediaImageBld, MediaType.COMMAND);
      }
      response.addMediaImage(mediaImageBld);
    }
    if (params.types.isEmpty() || params.types.contains(MediaType.BASIC)) {
      MediaImage.Builder mediaImageBld = MediaImage.newBuilder();
      if (trs80Ext.basic != 0 && mediaImagesForApp.containsKey(trs80Ext.basic)) {
        convert(mediaImagesForApp.get(trs80Ext.basic), mediaImageBld, MediaType.BASIC);
      }
      response.addMediaImage(mediaImageBld);
    }
    return response.setSuccess(true).setMessage("All good :-)").build();
  }

  private void convert(org.retrostore.data.app.MediaImage from,
                       MediaImage.Builder to,
                       MediaType type) {
    to.setType(type);
    to.setFilename(from.filename);
    to.setData(ByteString.copyFrom(from.data));
    to.setUploadTime(from.uploadTime);
    to.setDescription(from.description != null ? from.description : "");
  }

  private FetchMediaImagesApiParams parseLegacyParams(String params) {
    try {
      return (new Gson()).fromJson(params, FetchMediaImagesApiParams.class);
    } catch (Exception ex) {
      LOG.log(Level.WARNING, "Cannot parse params", ex);
      return null;
    }
  }
}
