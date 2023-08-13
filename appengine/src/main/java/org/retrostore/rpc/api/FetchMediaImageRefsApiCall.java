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

import com.google.protobuf.InvalidProtocolBufferException;
import org.retrostore.client.common.proto.ApiResponseMediaImageRefs;
import org.retrostore.client.common.proto.ApiResponseMediaImages;
import org.retrostore.client.common.proto.FetchMediaImageRefsParams;
import org.retrostore.client.common.proto.MediaImage;
import org.retrostore.client.common.proto.MediaImageRef;
import org.retrostore.data.app.AppManagement;
import org.retrostore.request.RequestData;
import org.retrostore.request.Response;
import org.retrostore.rpc.internal.ApiCall;

import java.util.HashSet;
import java.util.logging.Logger;

public class FetchMediaImageRefsApiCall implements ApiCall {
  private static final Logger LOG = Logger.getLogger("FetchMediaImageRefs");

  private final FetchMediaImagesApiCall mediaImageCall;

  public FetchMediaImageRefsApiCall(AppManagement appManagement) {
    mediaImageCall = new FetchMediaImagesApiCall(appManagement);
  }

  @Override
  public String getName() {
    return "fetchMediaImageRefs";
  }

  @Override
  public Response call(RequestData data) {
    FetchMediaImagesApiCall.Params params = parseParams(data.getRawBody());
    final ApiResponseMediaImageRefs response = callInternal(params);
    return responder -> responder.respondProto(response);
  }

  private FetchMediaImagesApiCall.Params parseParams(byte[] data) {
    FetchMediaImageRefsParams params;
    try {
      params = FetchMediaImageRefsParams.parseFrom(data);
      return new FetchMediaImagesApiCall.Params(params.getAppId(), new HashSet<>(params.getMediaTypeList()));
    } catch (InvalidProtocolBufferException e) {
      LOG.severe("Cannot parse parameters.");
    }
    return null;
  }

  private ApiResponseMediaImageRefs callInternal(FetchMediaImagesApiCall.Params params) {
    ApiResponseMediaImageRefs.Builder response = ApiResponseMediaImageRefs.newBuilder();

    // Piggy back on top of the original media image fetch call, to avoid code duplication.
    ApiResponseMediaImages mediaImages = mediaImageCall.callInternal(params);

    // Return error if fetching the media images failed.
    if (!mediaImages.getSuccess()) {
      return response.setSuccess(false)
          .setMessage(mediaImages.getMessage())
          .build();
    }

    // Convert all media images to references.
    for (MediaImage image : mediaImages.getMediaImageList()) {
      // Skip empty/UNKNOWN entries.
      if (image.getData().size() == 0) continue;

      String ref = params.appId + "/" + image.getFilename();
      response.addMediaImageRef(MediaImageRef.newBuilder()
          .setType(image.getType())
          .setFilename(image.getFilename())
          .setUploadTime(image.getUploadTime())
          .setDescription(image.getDescription())
          .setDataRef(ref));
    }

    return response.setSuccess(true).setMessage("All good :-)").build();
  }
}
