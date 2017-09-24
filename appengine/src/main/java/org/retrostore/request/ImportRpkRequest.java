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
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.data.rpk.RpkData;
import org.retrostore.data.user.RetroStoreUser;
import org.retrostore.data.user.UserManagement;
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
  private final UserManagement mUserManagement;

  public ImportRpkRequest(ResourceLoader resourceLoader, AppManagement appManagement,
                          UserManagement userManagement) {
    mResourceLoader = resourceLoader;
    mAppManagement = appManagement;
    mUserManagement = userManagement;
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
    if (!data.app.platform.equals("TRS-80")) {
      LOG.warning("Unsupported platform. Cannot import.");
      return false;
    }
    if (Strings.isNullOrEmpty(data.app.id)) {
      LOG.warning("RpkData has not app ID.");
      return false;
    }

    AppStoreItem app =  new AppStoreItem(data.app.id);
    Optional<AppStoreItem> appById = mAppManagement.getAppById(data.app.id);
    if (appById.isPresent()) {
      app = appById.get();
    }

    app.listing.name = data.app.name;
    app.listing.versionString = data.app.version;
    app.listing.description = data.app.description;
    app.listing.releaseYear = Integer.parseInt(data.app.year_published);
    app.listing.categories.clear();
    app.listing.categories.add(AppStoreItem.ListingCategory.valueOf(data.app.categories));
    app.configuration.model = AppStoreItem.Model.valueOf(data.trs.model);
    app.listing.authorId = mAppManagement.ensureAuthorExists(data.app.author);
    Optional<RetroStoreUser> userByEmail = mUserManagement.getUserByEmail(data.publisher.email);
    if (!userByEmail.isPresent()) {
      RetroStoreUser newUser = new RetroStoreUser();
      newUser.email = data.publisher.email;
      newUser.firstName = data.publisher.first_name;
      newUser.lastName = data.publisher.last_name;
      mUserManagement.addOrChangeUser(newUser);
    }
    app.listing.publisherEmail = data.publisher.email;

    // TODO: MediaImage
    // TODO: Screenshots.

    mAppManagement.addOrChangeApp(app);
    return true;
  }
}
