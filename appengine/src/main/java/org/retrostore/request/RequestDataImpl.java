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

package org.retrostore.request;

import com.google.common.base.Charsets;
import com.google.common.io.ByteStreams;
import com.google.common.io.CharStreams;

import javax.servlet.http.HttpServletRequest;

import java.io.IOException;
import java.io.InputStreamReader;
import java.util.logging.Logger;

import static com.google.common.base.Preconditions.checkNotNull;

/**
 * Default RequestData implementation based on an HttpServletRequest.
 */
public class RequestDataImpl implements RequestData {
  private static final Logger LOG = Logger.getLogger("RequestDataImpl");
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

  @Override
  public String getBody() {
    try {
      return CharStreams.toString(
          new InputStreamReader(mRequest.getInputStream(), Charsets.UTF_8));
    } catch (IOException ex) {
      LOG.warning(String.format("Could not read request body: '%s'.", ex.getMessage()));
      return "";
    }
  }

  @Override
  public byte[] getRawBody() {
    try {
      return ByteStreams.toByteArray(mRequest.getInputStream());
    } catch (IOException ex) {
      LOG.warning(String.format("Could not read request body: '%s'.", ex.getMessage()));
      return new byte[0];
    }
  }
}
