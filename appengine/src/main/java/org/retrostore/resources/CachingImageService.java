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

package org.retrostore.resources;

import com.google.common.base.Optional;

import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/**
 * Image service caching layer around an actual image service.
 */
public class CachingImageService implements ImageServiceWrapper {
  private final ImageServiceWrapper mImageService;
  private final MemcacheWrapper mMemcacheService;
  private final Map<String, String> mMemoryCache;

  public CachingImageService(ImageServiceWrapper imageService, MemcacheWrapper memcacheService) {
    mImageService = imageService;
    mMemcacheService = memcacheService;
    mMemoryCache = new HashMap<>();
  }

  @Override
  public Optional<String> getServingUrl(String blobKey, int imageSize) {
    String key = key(blobKey, imageSize);
    if (mMemoryCache.containsKey(key)) {
      return Optional.of(mMemoryCache.get(key));
    }

    Optional<String> urlOpt = mMemcacheService.getString(key);
    if (urlOpt.isPresent()) {
      mMemoryCache.put(key, urlOpt.get());
      return urlOpt;
    }

    // It's not in any cache.
    Optional<String> servingUrl = mImageService.getServingUrl(blobKey, imageSize);
    if (!servingUrl.isPresent()) {
      return Optional.absent();
    }
    mMemcacheService.put(key, servingUrl.get());
    mMemoryCache.put(key, servingUrl.get());
    return servingUrl;
  }

  private static String key(String blobKey, int imageSize) {
    return String.format(Locale.US, "screenshot_url_%s-%d", blobKey, imageSize);
  }
}
