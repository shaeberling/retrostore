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
import org.retrostore.data.user.UserService;
import org.retrostore.resources.ResourceLoader;

import java.util.logging.Logger;

public class PublicSiteRequest implements Request {
  private static final Logger LOG = Logger.getLogger("PublicSiteReq");
  private static final String PATH = "/public";
  private static final String WEB_ROOT = "WEB-INF";

  private final ResourceLoader mResourceLoader;

  public PublicSiteRequest(ResourceLoader resourceLoader) {
    mResourceLoader = resourceLoader;
  }

  @Override
  public boolean serveUrl(RequestData requestData, Responder responder, UserService userService) {
    // We will try to match the URL to a resource within the public directory. If it exist, we'll
    // serve it.
    String url = requestData.getUrl();

    LOG.info("Public check: " + url);


    if (url.equals("/") || url.equals("")) {
      url = "/index.html";
    }

    String publicResource = PATH + url;
    Optional<byte[]> data = mResourceLoader.load(WEB_ROOT + publicResource);
    if (data.isPresent()) {
      responder.respond(data.get(), ContentType.fromFilename(url));
      return true;
    }
    return false;
  }
}
