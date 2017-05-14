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

package org.puder.trs80.appstore;

import com.google.common.base.Charsets;
import com.google.common.base.Optional;
import com.google.common.collect.Sets;
import com.google.common.io.CharStreams;
import org.puder.trs80.appstore.data.user.UserService;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.util.Set;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Serves files that are part of the polymer frontend.
 */
public class PolymerServing implements RequestServing {
  private static final Logger LOG = Logger.getLogger("PolymerServing");

  private static final String POLYMER_ROOT = "WEB-INF/polymer-app";

  private static final Set<String> FORWARD = Sets.newHashSet("/bower_components",
      "/images", "/src", "/service-worker.js", "/manifest.json", "/index.html");

  @Override
  public boolean serveUrl(Request request, Responder responder, UserService accountTypeProvider) {
    String url = request.getUrl();
    LOG.info("URL: " + url);

    if (url.equals("/") || url.equals("") || url.startsWith("/view")) {
      url = "/index.html";
    }

    for (String path : FORWARD) {
      if (url.startsWith(path)) {
        Optional<String> content = load(POLYMER_ROOT + url);
        if (content.isPresent()) {
          responder.respond(content.get(), fromFilename(url));
        }
        return true;
      }
    }
    return false;
  }

  private Optional<String> load(String filename) {
    // TODO: Cache!
    try {
      InputStream fileStream = new FileInputStream(new File(filename));
      String content = CharStreams.toString(new InputStreamReader(fileStream, Charsets.UTF_8));
      return Optional.of(content);
    } catch (IOException e) {
      LOG.log(Level.SEVERE, "Cannot load file.", e);
    }
    return Optional.absent();
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
