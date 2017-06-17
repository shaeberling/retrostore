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

package org.retrostore.resources;

import com.google.common.base.Optional;

import java.util.logging.Logger;

/**
 * When running Retrostore in local debug mode, this loader can load files from a running polymer
 * debug server, thus we can immediately update the file without restart, which allows for rapid
 * development.
 * <p>
 * This instance will NEVER cache any data since we want to always have the latest version.
 */
public class PolymerDebugLoader implements ResourceLoader {
  private static final Logger LOG = Logger.getLogger("PolymerDebugLoader");
  private static final String POLYMER_ROOT = "WEB-INF/polymer-app";

  private final String mPolymerServer;
  private final ResourceLoader mFallbackResourceLoader;

  public PolymerDebugLoader(String polymerServer, ResourceLoader fallbackResourceLoader) {
    mPolymerServer = polymerServer;
    mFallbackResourceLoader = fallbackResourceLoader;
  }

  @Override
  public Optional<String> load(String filename) {
    if (!filename.startsWith(POLYMER_ROOT)) {
      LOG.warning(String.format("Not a polymer file, falling back for '%s'.", filename));
      return mFallbackResourceLoader.load(filename);
    }
    String url = mPolymerServer + filename.substring(POLYMER_ROOT.length());

    Optional<String> resource = loadUrl(url);
    if (!resource.isPresent()) {
      LOG.warning(
          String.format("Polymer debug resource cannot be loaded: '%s'. Falling back.", url));
      resource = mFallbackResourceLoader.load(filename);
    } else {
      LOG.info(String.format("Loaded from polymer server: '%s'", url));
    }
    return resource;
  }

  @Override
  public Optional<String> loadUrl(String url) {
    return mFallbackResourceLoader.loadUrl(url);
  }
}
