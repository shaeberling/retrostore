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

import com.google.common.base.Optional;
import com.google.common.base.Strings;
import com.google.gson.Gson;
import com.google.gson.JsonSyntaxException;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.rpk.RpkData;
import org.retrostore.data.user.UserService;
import org.retrostore.resources.ResourceLoader;

import java.util.List;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * A request that lets a user import RPKs from his disk.
 */
public class ImportRpkRequest implements Request {
  private static final Logger LOG = Logger.getLogger("ImportRpkRequest");
  private final ResourceLoader mResourceLoader;
  private final AppManagement mAppManagement;

  public ImportRpkRequest(ResourceLoader resourceLoader, AppManagement appManagement) {
    mResourceLoader = resourceLoader;
    mAppManagement = appManagement;
  }

  @Override
  public boolean serveUrl(RequestData requestData, Responder responder, UserService userService) {
    if (!requestData.getUrl().startsWith("/import")) {
      return false;
    }

    if (requestData.getType() == RequestData.Type.GET) {
      serveGet(responder);
    } else if (requestData.getType() == RequestData.Type.POST) {
      servePost(requestData.getFiles(), responder);
    }
    return true;
  }

  private void serveGet(Responder responder) {
    Optional<byte[]> html = mResourceLoader.load("WEB-INF/html/upload_rpks.html.inc");
    if (!html.isPresent()) {
      responder.respondNotFound();
    } else {
      responder.respond(html.get(), Responder.ContentType.HTML);
    }
  }

  private void servePost(List<RequestData.UploadFile> files, Responder responder) {
    if (files.isEmpty()) {
      responder.respondBadRequest("No files uploaded.");
      return;
    }

    int numImported = 0;
    for (RequestData.UploadFile file : files) {
      if (addRpk(file)) {
        numImported++;
      }
    }
    responder.respond(String.format("Got %d files. Imported %d", files.size(), numImported),
        Responder.ContentType.HTML);
  }

  private boolean addRpk(RequestData.UploadFile file) {
    String json = new String(file.content);
    try {
      return storeRpk((new Gson()).fromJson(json, RpkData.class));
    } catch (JsonSyntaxException ex) {
      LOG.log(Level.WARNING, "Cannot parse JSON", ex);
    }
    return false;
  }

  private boolean storeRpk(RpkData data) {
    if (Strings.isNullOrEmpty(data.app.id)) {
      LOG.warning("RpkData has not app ID.");
      return false;
    }
    return true;
  }
}
