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

import com.google.common.base.Optional;
import com.google.common.base.Strings;
import org.retrostore.client.common.proto.ApiResponseMediaImages;
import org.retrostore.request.RequestData;
import org.retrostore.request.Responder;
import org.retrostore.request.Response;
import org.retrostore.rpc.internal.ApiCall;

import java.util.logging.Logger;

public class GetMediaImagesApiCall implements ApiCall {
  private static final Logger LOG = Logger.getLogger("GetMediaImages");

  private final String PARAM_APP_ID = "appId";

  @Override
  public String getName() {
    return "getMediaImages";
  }

  @Override
  public Response call(RequestData params) {
    final ApiResponseMediaImages response = callInternal(params);
    return new Response() {
      @Override
      public void respond(Responder responder) {
        responder.respondProto(response);
      }
    };
  }

  private ApiResponseMediaImages callInternal(RequestData params) {
    ApiResponseMediaImages.Builder response = ApiResponseMediaImages.newBuilder();

    Optional<String> appIdOpt = params.getString(PARAM_APP_ID);
    if (!appIdOpt.isPresent() || Strings.isNullOrEmpty(appIdOpt.get())) {
      return response.setSuccess(false)
          .setMessage(String.format("No '%s' given.", PARAM_APP_ID))
          .build();
    }

    return response.build();
  }
}
