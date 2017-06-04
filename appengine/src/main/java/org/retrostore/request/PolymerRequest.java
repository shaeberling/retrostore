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

package org.retrostore.request;

import com.google.common.base.Optional;
import com.google.common.collect.Sets;
import org.retrostore.data.user.UserService;
import org.retrostore.resources.ResourceLoader;

import java.util.Set;
import java.util.logging.Logger;

/**
 * Serves files that are part of the polymer frontend.
 */
public class PolymerRequest implements Request {
  private static final Logger LOG = Logger.getLogger("PolymerRequest");

  private static final String POLYMER_ROOT = "WEB-INF/polymer-app";
  private static final Set<String> FORWARD = Sets.newHashSet("/bower_components",
      "/images", "/src", "/service-worker.js", "/manifest.json", "/index.html");

  private final ResourceLoader mResourceLoader;

  public PolymerRequest(ResourceLoader resourceLoader) {
    mResourceLoader = resourceLoader;
  }

  @Override
  public boolean serveUrl(RequestData requestData,
                          Responder responder,
                          UserService accountTypeProvider) {
    String url = requestData.getUrl();
    LOG.info("URL: " + url);

    // If a request is not for a sub-directory, we map it to index.html where it will be handled
    // by polymer on the client side.
    if (url.equals("/") || url.equals("") || !url.substring(1).contains("/")) {
      url = "/index.html";
    }

    for (String path : FORWARD) {
      if (url.startsWith(path)) {
        Optional<String> content = mResourceLoader.load(POLYMER_ROOT + url);
        if (content.isPresent()) {
          responder.respond(content.get(), fromFilename(url));
        }
        return true;
      }
    }
    return false;
  }

  private Responder.ContentType fromFilename(String filename) {
    if (filename.endsWith(".html")) {
      return Responder.ContentType.HTML;
    } else if (filename.endsWith(".css")) {
      return Responder.ContentType.CSS;
    } else if (filename.endsWith(".js")) {
      return Responder.ContentType.JS;
    } else if (filename.endsWith(".json")) {
      return Responder.ContentType.JSON;
    } else if (filename.endsWith(".jpeg")) {
      return Responder.ContentType.JPEG;
    } else if (filename.endsWith(".png")) {
      return Responder.ContentType.PNG;
    } else {
      LOG.warning("Content type not recognized for: " + filename);
      return Responder.ContentType.PLAIN;
    }
  }
}
