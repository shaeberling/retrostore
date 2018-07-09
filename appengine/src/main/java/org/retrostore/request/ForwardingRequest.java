/*
 *  Copyright 2018, Sascha Häberling
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

package org.retrostore.request;

import com.google.common.collect.ImmutableMap;
import org.retrostore.data.user.UserService;

import java.util.HashMap;
import java.util.Map;


/**
 * Contains a map to HTTP forward certain paths.
 */
public class ForwardingRequest implements Request {
  private static final Map<String, String> mapping = ImmutableMap.copyOf(
      new HashMap<String, String>() {
        {
          put("/rsc", "https://github.com/apuder/RetroStoreCard");
          put("/rsc/", "https://github.com/apuder/RetroStoreCard");
        }
      });

  @Override
  public boolean serveUrl(RequestData requestData, Responder responder, UserService userService) {
    String url = requestData.getUrl();
    // URL path needs to match exactly.
    if (!mapping.containsKey(url)) {
      return false;
    }
    responder.respondRedirect(mapping.get(url));
    return true;
  }
}
