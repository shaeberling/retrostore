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
import com.google.common.io.ByteStreams;
import org.retrostore.request.Cache;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.MalformedURLException;
import java.net.URL;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Loads files as resources and caches them aggressively.
 */
public class DefaultResourceLoader implements ResourceLoader {
  private static final Logger LOG = Logger.getLogger("DefaultResourceLoader");

  private final Cache mCache;

  public DefaultResourceLoader(Cache cache) {
    mCache = cache;
  }

  @Override
  public Optional<byte[]> load(final String filename) {
    return mCache.get(filename, new Cache.DataProvider() {
      @Override
      public byte[] provide() {
        return loadFile(filename);
      }
    });
  }

  private byte[] loadFile(String filename) {
    // TODO: Debug mode for local reloading
    try {
      File file = new File(filename);
      LOG.info("Loading file: " + file.getAbsolutePath());
      return toBytes(new FileInputStream(file));
    } catch (IOException ignore) {
      LOG.log(Level.INFO, String.format("Cannot load file as resource '%s'.", filename));
    }
    return null;
  }

  @Override
  public Optional<byte[]> loadUrl(String urlStr) {
    try {
      URL url = new URL(urlStr);
      InputStream is = url.openStream();
      return Optional.of(toBytes(is));
    } catch (MalformedURLException e) {
      LOG.log(Level.SEVERE, "Invalid URL", e);
    } catch (IOException e) {
      LOG.log(Level.SEVERE, "Cannot read URL", e);
    }
    return Optional.absent();
  }

  private byte[] toBytes(InputStream input) throws IOException {
    ByteArrayOutputStream data = new ByteArrayOutputStream();
    ByteStreams.copy(input, data);
    return data.toByteArray();
  }
}
