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

import java.util.Optional;

/**
 * A simple cache interface.
 */
public interface Cache {

  /**
   * Returns the data if it's in the cache, or otherwise calls the data provider for the data. If
   * the latter happens, the data will then also be put into the cache.
   *
   * @param resourceName the name of the resource, used as a key into our cache.
   * @param fallback     will be called to provide the data if it is not in the cache.
   * @return The data.
   */
  Optional<byte[]> get(String resourceName, DataProvider fallback);

  /**
   * Classes implementing thia interface can provide data to fill in the cache if needed.
   */
  interface DataProvider {
    /** Provide the data for the cache. */
    byte[] provide();
  }
}
