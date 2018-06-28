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

import org.retrostore.data.user.UserService;
import org.retrostore.resources.ResourceLoader;

import java.util.Optional;

/**
 * Handles loading favicon related files. We make this its own request so that no matter which
 * request handler is being used (either for the admin backend or the main page), the favicon is
 * loaded correctly.
 */
public class FaviconRequest implements Request {
  private static final String WEB_ROOT = "WEB-INF";
  private final ResourceLoader mResourceLoader;

  public FaviconRequest(ResourceLoader resourceLoader) {
    mResourceLoader = resourceLoader;
  }

  @Override
  public boolean serveUrl(RequestData requestData, Responder responder, UserService userService) {
    String url = requestData.getUrl();

    // Re-write the favicon path in case the browser is requesting it.
    if (url.equals("/favicon.ico")) {
      url = "/favicon/favicon.ico";
    }

    if (!url.startsWith("/favicon")) {
      return false;
    }
    Optional<byte[]> data = mResourceLoader.load(WEB_ROOT + url);
    if (data.isPresent()) {
      responder.respond(data.get(), ContentType.fromFilename(url));
    } else {
      responder.respondNotFound();
    }
    return true;
  }
}
