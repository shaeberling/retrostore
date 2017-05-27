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

import com.google.common.base.Optional;
import org.puder.trs80.appstore.data.user.RetroStoreUser;
import org.puder.trs80.appstore.data.user.UserAccountType;
import org.puder.trs80.appstore.data.user.UserManagement;
import org.puder.trs80.appstore.data.user.UserService;

import java.util.logging.Logger;

/**
 * Bootstrapping! After being logged in, if there is not admin, this ensure one is being created.
 */
public class EnsureAdminExistsRequest implements Request {
  private static final Logger LOG = Logger.getLogger("EnsureAdminExists");
  private final UserManagement mUserManagement;

  public EnsureAdminExistsRequest(UserManagement userManagement) {
    mUserManagement = userManagement;
  }

  @Override
  public boolean serveUrl(RequestData requestData, Responder responder, UserService userService) {
    // Nothing to do here if the user is not logged in or an admin already exists.
    // Note, if an admin already exists, he/she can then add other admins and users through the
    // regular user management.
    if (userService.getForCurrentUser().equals(UserAccountType.NOT_LOGGED_IN) || userService
        .systemHasAdmin()) {
      return false;
    }

    Optional<String> loggedInEmailOpt = mUserManagement.getLoggedInEmail();
    if (!loggedInEmailOpt.isPresent()) {
      LOG.warning("User should be logged in but does not have an e-mail.");
      return false;
    }

    RetroStoreUser firstAdminUser = new RetroStoreUser();
    firstAdminUser.email = loggedInEmailOpt.get();
    firstAdminUser.firstName = "Admin";
    firstAdminUser.lastName = "Admin";
    firstAdminUser.type = UserAccountType.ADMIN;
    mUserManagement.addOrChangeUser(firstAdminUser);
    LOG.info("Added first admin user to th system");

    responder.respond("You have been added as the initial admin user of the system", Responder
        .ContentType.PLAIN);
    return true;
  }
}
