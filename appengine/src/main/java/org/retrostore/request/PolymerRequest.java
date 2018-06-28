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

import com.google.common.collect.Sets;
import org.retrostore.data.user.UserService;
import org.retrostore.resources.ResourceLoader;

import java.util.Optional;
import java.util.Set;
import java.util.logging.Logger;

/**
 * Serves files that are part of the polymer frontend.
 */
public class PolymerRequest implements Request {
  private static final Logger LOG = Logger.getLogger("PolymerRequest");

  private static final String POLYMER_ROOT = "WEB-INF/polymer-app";
  private static final Set<String> FORWARD = Sets.newHashSet("/bower_components", "/images",
      "/src", "/service-worker.js", "/manifest.json", "/user-management-view",
      "/app-management-view");

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

    String rewriteUrl = url;
    if (url.startsWith("/user-management-view") || url.startsWith("/app-management-view")) {
      rewriteUrl = "/index.html";
    }

    for (String path : FORWARD) {
      if (url.startsWith(path)) {
        Optional<byte[]> content = mResourceLoader.load(POLYMER_ROOT + rewriteUrl);
        if (content.isPresent()) {
          responder.respond(content.get(), ContentType.fromFilename(rewriteUrl));
        }
        return true;
      }
    }
    return false;
  }
}
