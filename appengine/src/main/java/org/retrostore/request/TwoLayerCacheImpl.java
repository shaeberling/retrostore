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

import com.google.common.base.Preconditions;
import org.retrostore.resources.MemcacheWrapper;

import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import java.util.logging.Logger;

/**
 * A two-level cache, using simple class-instance-local HashMap as the first level, and memcache
 * as the second level.
 */
public class TwoLayerCacheImpl implements Cache {
  private static final Logger LOG = Logger.getLogger("TwoLayerCache");

  private static Map<String, byte[]> sFirstLevel = new HashMap<>(100);
  private final MemcacheWrapper mMemcache;
  private static int mNumServedFirstLevel = 0;
  private static int mNumServedMemcache = 0;
  private static int mNumCacheMisses = 0;

  public TwoLayerCacheImpl(MemcacheWrapper memcache) {
    mMemcache = memcache;
  }

  @Override
  public Optional<byte[]> get(String resourceName, DataProvider fallback) {
    Preconditions.checkNotNull(resourceName);
    Preconditions.checkNotNull(fallback);

    LOG.info("Current cache stats: " + toString());

    if (sFirstLevel.containsKey(resourceName) && sFirstLevel.get(resourceName) != null) {
      mNumServedFirstLevel++;
      return Optional.of(sFirstLevel.get(resourceName));
    }

    Optional<byte[]> dataOpt = mMemcache.get(resourceName);
    if (dataOpt.isPresent()) {
      mNumServedMemcache++;
      sFirstLevel.put(resourceName, dataOpt.get());
      return dataOpt;
    }

    mNumCacheMisses++;
    byte[] data = fallback.provide();
    if (data != null && data.length > 0) {
      sFirstLevel.put(resourceName, data);
      mMemcache.put(resourceName, data);
    }
    return Optional.ofNullable(data);
  }

  @Override
  public String toString() {
    return String.format("Cache, served %d first-level and %d from memcache. Missed %d.",
        mNumServedFirstLevel, mNumServedMemcache, mNumCacheMisses);
  }
}
