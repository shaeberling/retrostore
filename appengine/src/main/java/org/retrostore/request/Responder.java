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

import com.google.gson.Gson;

import javax.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.logging.Level;
import java.util.logging.Logger;

import static com.google.common.base.Preconditions.checkNotNull;

/**
 * Simple interface and implementation for serving data of a certain type.
 */
public class Responder {
  public enum ContentType {
    PLAIN("text/plain"),
    BYTES("application/octet-stream"),
    HTML("text/html"),
    CSS("text/css"),
    JS("application/javascript"),
    JSON("application/json"),
    PNG("image/png"),
    JPEG("image/jpeg");

    public String str;

    ContentType(String str) {
      this.str = str;
    }
  }

  private static final Logger LOG = Logger.getLogger("Responder");
  private final HttpServletResponse mResponse;

  public Responder(HttpServletResponse response) {
    mResponse = checkNotNull(response);
  }

  /** Respond with the given content text and type. */
  public void respond(String content, ContentType contentType) {
    try {
      mResponse.setContentType(contentType.str);
      mResponse.getWriter().write(content);
    } catch (IOException ex) {
      LOG.log(Level.SEVERE, "Cannot serve data", ex);
    }
  }

  /** Converts the given object into JSON and sends it. */
  public void respondJson(Object object) {
    try {
      mResponse.setContentType(ContentType.JSON.str);
      mResponse.getWriter().write((new Gson()).toJson(object));
    } catch (IOException ex) {
      LOG.log(Level.SEVERE, "Cannot serve data", ex);
    }
  }

  /** Respond with a Protocol Buffer lite message. */
  public void respondProto(com.google.protobuf.GeneratedMessageLite object) {
    try {
      mResponse.setContentType(ContentType.BYTES.str);
      object.writeTo(mResponse.getOutputStream());
      mResponse.getOutputStream().close();
    } catch (IOException ex) {
      LOG.log(Level.SEVERE, "Cannot serve data", ex);
    }
  }

  /** Respond with a bad request and a plain text error message. */
  public void respondBadRequest(String content) {
    try {
      mResponse.setStatus(HttpServletResponse.SC_BAD_REQUEST);
      mResponse.setContentType(ContentType.PLAIN.str);
      mResponse.getWriter().write(content);
    } catch (IOException ex) {
      LOG.log(Level.SEVERE, "Cannot serve data", ex);
    }
  }

  /** Respond with not-found error code and no content. */
  public void respondNotFound() {
    try {
      mResponse.setStatus(HttpServletResponse.SC_NOT_FOUND);
      mResponse.setContentType(ContentType.PLAIN.str);
      mResponse.getWriter().write("");
    } catch (IOException ex) {
      LOG.log(Level.SEVERE, "Cannot serve data", ex);
    }
  }

}
