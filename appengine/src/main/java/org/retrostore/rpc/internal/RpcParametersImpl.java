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

import com.google.common.base.Optional;
import org.retrostore.request.RequestData;

import java.util.logging.Logger;

/**
 * Maps Requests to RpcParameters.
 */
public class RpcParametersImpl implements RpcParameters {
  private static final Logger LOG = Logger.getLogger("RpcParametersImpl");
  private final RequestData mRequestData;

  RpcParametersImpl(RequestData requestData) {
    mRequestData = requestData;
  }

  @Override
  public Optional<Integer> getInt(String name) {
    String value = mRequestData.getParameter(name);
    if (value == null) {
      return Optional.absent();
    }
    try {
      return Optional.of(Integer.parseInt(value));
    } catch (NumberFormatException ex) {
      LOG.warning(String.format("Cannot parse '%s' to integer", value));
      return Optional.absent();
    }
  }

  @Override
  public Optional<String> getString(String name) {
    return Optional.fromNullable(mRequestData.getParameter(name));
  }

  @Override
  public String getBody() {
    return mRequestData.getBody();
  }
}
