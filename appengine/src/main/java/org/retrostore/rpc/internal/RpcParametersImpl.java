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

package org.retrostore.rpc.internal;

import org.retrostore.request.RequestData;

import java.util.Optional;

/**
 * Maps Requests to RpcParameters.
 */
public class RpcParametersImpl implements RpcParameters {
  private final RequestData mRequestData;

  RpcParametersImpl(RequestData requestData) {
    mRequestData = requestData;
  }

  @Override
  public Optional<Integer> getInt(String name) {
    return mRequestData.getInt(name);
  }

  @Override
  public Optional<Long> getLong(String name) {
    return mRequestData.getLong(name);
  }

  @Override
  public Optional<String> getString(String name) {
    return mRequestData.getString(name);
  }

  @Override
  public String getBody() {
    return mRequestData.getBody();
  }
}
