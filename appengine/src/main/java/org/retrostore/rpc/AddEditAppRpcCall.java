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

package org.retrostore.rpc;

import com.google.common.base.Optional;
import com.google.common.base.Strings;
import com.google.gson.Gson;
import com.google.gson.JsonSyntaxException;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.data.app.AppStoreItem.ListingCategory;
import org.retrostore.data.app.AppStoreItem.Model;
import org.retrostore.data.user.UserAccountType;
import org.retrostore.data.user.UserManagement;
import org.retrostore.request.Responder;
import org.retrostore.rpc.internal.RpcCall;
import org.retrostore.rpc.internal.RpcParameters;
import org.retrostore.rpc.internal.RpcResponse;

import java.util.logging.Logger;

/**
 * Add or edit an app entry.
 */
public class AddEditAppRpcCall implements RpcCall<RpcParameters> {

  private static final class Data {
    public String appId;
    public String appName;
    public String appVersion;
    public String description;
    public String releaseYear;
    public String origAuthorId;
    public String newAuthor;
    public String category;
    public String model;
  }

  private static final Logger LOG = Logger.getLogger("AddEditAppRpcCall");
  private final AppManagement mAppManagement;
  private final UserManagement mUserManagement;

  public AddEditAppRpcCall(AppManagement appManagement, UserManagement userManagement) {
    mAppManagement = appManagement;
    mUserManagement = userManagement;
  }

  @Override
  public String getName() {
    return "addEditApp";
  }

  @Override
  public boolean isPermitted(UserAccountType type) {
    return type == UserAccountType.ADMIN;
  }

  @Override
  public void call(RpcParameters params, Responder responder) {
    String body = params.getBody();
    if (Strings.isNullOrEmpty(body)) {
      // TODO: Make #call return RpcResponse and get rid of responder.
      RpcResponse.respond(false, "No data received", responder);
      return;
    }

    try {
      Data data = (new Gson()).fromJson(body, Data.class);
      if (checkNullEmpty(data.appName, "App name missing", responder) ||
          checkNullEmpty(data.appVersion, "App version missing", responder) ||
          checkNullEmpty(data.description, "Description missing", responder) ||
          checkNoValidInt(data.releaseYear, "Release yer invalid", responder, true) ||
          checkNullEmpty(data.category, "Category missing", responder) ||
          checkNullEmpty(data.model, "Model missing", responder)) {
        return;
      }

      if ("-1".equals(data.origAuthorId) && Strings.isNullOrEmpty(data.newAuthor.trim())) {
        RpcResponse.respond(false, "No author selected or entered", responder);
        return;
      }

      Optional<Model> model =
          getEnumValue(Model.class, data.model, "Illegal TRS model '%s'", responder);
      Optional<ListingCategory> category =
          getEnumValue(ListingCategory.class, data.category, "Illegal app category '%s'",
              responder);
      if (!model.isPresent() ||
          !category.isPresent()) {
        return;
      }

      AppStoreItem appStoreItem = new AppStoreItem();

      // Let's see if an existing app exists, so this becomes an edit and not an add operation.
      if (!Strings.isNullOrEmpty(data.appId)) {
        try {
          Optional<AppStoreItem> existingApp = mAppManagement.getAppById(data.appId);
          if (existingApp.isPresent()) {
            appStoreItem = existingApp.get();
          } else {
            LOG.warning(String.format("Cannot find app with id '%s'.", data.appId));
          }

        } catch (NumberFormatException ex) {
          LOG.warning(String.format("Cannot parse appId '%s'.", data.appId));
        }
      }

      appStoreItem.listing.name = data.appName;
      appStoreItem.listing.versionString = data.appVersion;
      appStoreItem.listing.description = data.description;
      // We already checked above that this is a valid integer.
      appStoreItem.listing.releaseYear = Integer.parseInt(data.releaseYear);
      appStoreItem.listing.categories.clear();
      appStoreItem.listing.categories.add(category.get());
      appStoreItem.trs80Extension.model = model.get();

      // Set the publisher.
      if (Strings.isNullOrEmpty(appStoreItem.listing.publisherEmail)) {
        Optional<String> loggedInEmail = mUserManagement.getLoggedInEmail();
        if (!loggedInEmail.isPresent()) {
          LOG.severe("Non-logged in user tries to save App item.");
          RpcResponse.respond(false, "Not logged in", responder);
        } else {
          appStoreItem.listing.publisherEmail = loggedInEmail.get();
        }
      }

      // If the author ID was not set, a new author needs to be created.
      if ("-1".equals(data.origAuthorId)) {
        String authorName = data.newAuthor.trim();
        long authorId = mAppManagement.ensureAuthorExists(authorName);
        appStoreItem.listing.authorId = authorId;
      } else {
        try {
          long authorId = Long.parseLong(data.origAuthorId);
          appStoreItem.listing.authorId = authorId;
        } catch (IllegalArgumentException ex) {
          String errorMessage = String.format("Bad original author ID '%s'", data.origAuthorId);
          LOG.severe(errorMessage);
          RpcResponse.respond(false, errorMessage, responder);
          return;
        }
      }

      mAppManagement.addOrChangeApp(appStoreItem);
      RpcResponse.respond(true, "App data changed/added", responder);
    } catch (JsonSyntaxException e) {
      RpcResponse.respond(false, "Invalid JSON data", responder);
    }
  }

  private static boolean checkNullEmpty(String var, String errorMessage, Responder responder) {
    if (Strings.isNullOrEmpty(var)) {
      RpcResponse.respond(false, errorMessage, responder);
      return true;
    } else {
      return false;
    }
  }

  private static boolean checkNoValidInt(String var, String errorMessage, Responder responder,
                                         boolean enforcePositiveNum) {
    try {
      int num = Integer.parseInt(var);
      if (enforcePositiveNum && num < 0) {
        RpcResponse.respond(false, errorMessage, responder);
        return true;
      }
      return false;
    } catch (NumberFormatException ex) {
      RpcResponse.respond(false, errorMessage, responder);
      return true;
    }
  }

  private static <T extends Enum<T>> Optional<T> getEnumValue(
      Class<T> enumType, String value,
      String errorMessage, Responder responder) {
    try {
      return Optional.of(Enum.valueOf(enumType, value));
    } catch (IllegalArgumentException ex) {
      errorMessage = String.format(errorMessage, value);
      LOG.severe(errorMessage);
      RpcResponse.respond(false, errorMessage, responder);
      return Optional.absent();
    }
  }
}
