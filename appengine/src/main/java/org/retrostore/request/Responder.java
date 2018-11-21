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

import com.google.appengine.api.blobstore.BlobKey;
import com.google.appengine.api.blobstore.BlobstoreService;
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
    JPEG("image/jpeg"),
    SVG("image/svg+xml"),
    ZIP("application/zip");

    public String str;

    ContentType(String str) {
      this.str = str;
    }
  }

  private static final Logger LOG = Logger.getLogger("Responder");
  private final HttpServletResponse mResponse;
  private final BlobstoreService mBlobstoreService;

  public Responder(HttpServletResponse response, BlobstoreService blobstoreService) {
    mResponse = checkNotNull(response);
    mBlobstoreService = blobstoreService;
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

  /** Respond with the given content text and type. */
  public void respond(byte[] content, ContentType contentType) {
    try {
      mResponse.setContentType(contentType.str);
      mResponse.addHeader("Access-Control-Allow-Origin", "*");
      mResponse.getOutputStream().write(content);
    } catch (IOException ex) {
      LOG.log(Level.SEVERE, "Cannot serve data", ex);
    }
  }

  /** Respond with the given content text and type. */
  public void respondDownload(byte[] content, String filename, ContentType contentType) {
    try {
      mResponse.setContentType(contentType.str);
      mResponse.setHeader("Content-Disposition",
          String.format("attachment; filename=\"%s\"",
              filename));
      mResponse.getOutputStream().write(content);
    } catch (IOException ex) {
      LOG.log(Level.SEVERE, "Cannot serve data", ex);
    }
  }

  // Content-Disposition: attachment; filename="fname.ext"

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
    respond(content, ContentType.PLAIN, HttpServletResponse.SC_BAD_REQUEST);
  }

  /** Respond with a bad request and a plain text error message. */
  public void respondForbidden(String content) {
    respond(content, ContentType.PLAIN, HttpServletResponse.SC_FORBIDDEN);
  }

  /** Respond with not-found error code and no content. */
  public void respondNotFound() {
    respond("", ContentType.PLAIN, HttpServletResponse.SC_NOT_FOUND);
  }

  private void respond(String content, ContentType contentType, int statusCode) {
    try {
      mResponse.setStatus(statusCode);
      mResponse.setContentType(contentType.str);
      mResponse.getWriter().write(content);
    } catch (IOException ex) {
      LOG.log(Level.SEVERE, "Cannot serve data", ex);
    }
  }

  /**
   * Serves the blob with the given ID.
   *
   * @param key the key of the blob to serve.
   * @return Whether serving the blob was successful.
   */
  public boolean respondBlob(String key) {
    BlobKey blobKey = new BlobKey(checkNotNull(key));
    try {
      mBlobstoreService.serve(blobKey, mResponse);
      return true;
    } catch (IOException e) {
      LOG.log(Level.SEVERE, String.format("Cannot serve blob '%s'", key), e);
    }
    return false;
  }

  /** Responds with a redirect request to the given URL. */
  public void respondRedirect(String url) {
    try {
      mResponse.sendRedirect(url);
    } catch (IOException ex) {
      LOG.log(Level.SEVERE, "Cannot serve redirect", ex);
    }
  }
}
