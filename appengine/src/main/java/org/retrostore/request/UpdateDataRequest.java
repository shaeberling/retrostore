/*
 *  Copyright 2018, Sascha Häberling
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
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.app.AppSearch;
import org.retrostore.data.user.UserService;

import java.util.logging.Logger;

import static org.retrostore.data.user.UserAccountType.ADMIN;

/** Helps to manage data through manual triggers. */
public class UpdateDataRequest implements Request {
  private static final Logger LOG = Logger.getLogger("UpdateDataRequest");
  private static final String API_PREFIX = "/updateData";
  private final AppSearch mAppSearch;
  private final AppManagement mAppManagement;

  public UpdateDataRequest(AppSearch appSearch, AppManagement appManagement) {
    mAppSearch = appSearch;
    mAppManagement = appManagement;
  }

  @Override
  public boolean serveUrl(RequestData requestData, Responder responder, UserService userService) {
    String url = requestData.getUrl();
    if (!url.startsWith(API_PREFIX)) {
      return false;
    }
    if (userService.getForCurrentUser() != ADMIN) {
      responder.respondForbidden("You need to be an admin");
      return true;
    }

    Optional<String> actionOpt = requestData.getString("action");
    if (!actionOpt.isPresent()) {
      responder.respondBadRequest("Need 'action' parameter");
      return true;
    }
    String action = actionOpt.get();
    if ("updateSearchIndex".equalsIgnoreCase(action)) {
      long start = System.currentTimeMillis();
      mAppSearch.refreshIndex(mAppManagement.getAllApps());
      long end = System.currentTimeMillis();
      LOG.info(String.format("Updating search index took %dms.", (end - start)));
    }
    return true;
  }
}
