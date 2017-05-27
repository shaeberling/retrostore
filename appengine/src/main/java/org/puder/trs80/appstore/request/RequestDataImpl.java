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

package org.puder.trs80.appstore.request;

import javax.servlet.http.HttpServletRequest;

import static com.google.common.base.Preconditions.checkNotNull;

/**
 * Default RequestData implementation based on an HttpServletRequest.
 */
public class RequestDataImpl implements RequestData {
  private final HttpServletRequest mRequest;

  public RequestDataImpl(HttpServletRequest request) {
    mRequest = checkNotNull(request);
  }

  @Override
  public String getUrl() {
    return mRequest.getRequestURI();
  }

  @Override
  public String getParameter(String name) {
    return mRequest.getParameter(name);
  }
}