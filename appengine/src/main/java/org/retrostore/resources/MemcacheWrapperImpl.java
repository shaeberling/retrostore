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

import com.google.appengine.api.memcache.MemcacheService;
import com.google.common.base.Preconditions;

import java.util.Optional;

/**
 * Default implementation using the actual memcache.
 */
public class MemcacheWrapperImpl implements MemcacheWrapper {
  private final MemcacheService mMemcacheService;

  public MemcacheWrapperImpl(MemcacheService memcacheService) {
    mMemcacheService = Preconditions.checkNotNull(memcacheService);
  }

  @Override
  public Optional<byte[]> get(String key) {
    return Optional.ofNullable((byte[]) mMemcacheService.get(key));
  }

  @Override
  public void put(String key, Object data) {
    mMemcacheService.put(key, data);
  }

  @Override
  public Optional<String> getString(String key) {
    return Optional.ofNullable((String) mMemcacheService.get(key));
  }

  @Override
  public Optional<Object> getObject(String key) {
    return Optional.ofNullable(mMemcacheService.get(key));
  }
}
