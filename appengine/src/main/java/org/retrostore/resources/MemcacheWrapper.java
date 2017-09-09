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

/**
 * Simple mockable memcache wrapper.
 */
public interface MemcacheWrapper {
  /**
   * Gets the item with the given key, if available.
   *
   * @param key the key of the item.
   * @return The item, if available in memcache.
   */
  Optional<byte[]> get(String key);

  /**
   * Adds or updates an item in memcache.
   *
   * @param key  the key of the item.
   * @param data the data to put into the cache.
   */
  void put(String key, byte[] data);
}
