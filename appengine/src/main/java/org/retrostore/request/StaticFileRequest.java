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

package org.retrostore.request;

import com.google.common.base.Optional;
import com.google.common.collect.Sets;
import org.retrostore.data.user.UserService;
import org.retrostore.resources.ResourceLoader;

import java.util.Set;
import java.util.logging.Logger;

/**
 * Serves static files.
 */
public class StaticFileRequest implements Request {
  private static final Logger LOG = Logger.getLogger("StaticFileRequest");
  private static final String WEB_ROOT = "WEB-INF";


  private static final Set<String> FILTER = Sets.newHashSet(
      "/gfx", "/public", "/static", "/favicon", "/bootstrap", "/.well-known");

  private final ResourceLoader mResourceLoader;

  public StaticFileRequest(ResourceLoader resourceLoader) {
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

    // Re-write the favicon path in case the browser is requesting it.
    if (url.equals("/favicon.ico")) {
      url = "/favicon/favicon.ico";
    }

    for (String path : FILTER) {
      if (url.startsWith(path)) {
        Optional<byte[]> content = mResourceLoader.load(WEB_ROOT + url);
        if (content.isPresent()) {
          responder.respond(content.get(), ContentType.fromFilename(url));
          return true;
        }
      }
    }
    return false;
  }
}
