/*
 * Copyright 2016, Sascha Häberling
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

package org.puder.trs80.appstore.data.user;

import com.google.common.base.Optional;
import org.puder.trs80.appstore.ui.Template;

import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.List;
import java.util.logging.Logger;

/**
 * Fills UI data and receives request from the UI to change data.
 */
public class UserViewUtil {
  private static final Logger LOG = Logger.getLogger("UserViewUtil");

  private final UserManagement userManagement;

  public UserViewUtil(UserManagement userManagement) {
    this.userManagement = userManagement;
  }

  public void handleAccountCreateRequest(HttpServletRequest req, HttpServletResponse resp) {
    Optional<String> email = userManagement.getLoggedInEmail();
    if (!email.isPresent()) {
      return;
    }

    RetroStoreUser newUser = new RetroStoreUser();
    newUser.firstName = req.getParameter("firstName");
    newUser.lastName = req.getParameter("lastName");
    newUser.email = email.get();

    // If there is no admin in the system, this user will be an admin. This helps bootstrapping the process on a fresh
    // install.
    newUser.type = userManagement.hasAdmin() ? UserAccountType.PUBLISHER : UserAccountType.ADMIN;
    userManagement.addOrChangeUser(newUser);
    LOG.info("New user created (" + newUser.email + ") with role " + newUser.type);
  }

  public void handleAddEditRequest(HttpServletRequest req, HttpServletResponse resp) {
    String firstName = req.getParameter("firstName");
    String lastName = req.getParameter("lastName");
    String email = req.getParameter("email");
    String type = req.getParameter("type");
    LOG.info("firstName: " + firstName);
    LOG.info("lastName: " + lastName);
    LOG.info("email: " + email);
    LOG.info("type: " + type);

    // If the given e-mail matches an existing user, we edit the entry.
    Optional<RetroStoreUser> existingUser = userManagement.getUserByEmail(email);
    RetroStoreUser retroStoreUser = existingUser.isPresent() ? existingUser.get() : new RetroStoreUser();

    retroStoreUser.firstName = firstName;
    retroStoreUser.lastName = lastName;
    retroStoreUser.email = email;
    retroStoreUser.type = "admin".equals(type) ? UserAccountType.ADMIN : UserAccountType.PUBLISHER;
    userManagement.addOrChangeUser(retroStoreUser);
    LOG.info("User updated/created (" + retroStoreUser.email + ")");
  }

  public void handleRemoveRequest(HttpServletRequest req, HttpServletResponse resp) {
    String email = req.getParameter("email");
    LOG.info("email: " + email);
    userManagement.removeUser(email);
  }

  public Template fillUserManagementView(UserManagement userManagement) throws IOException {
    List<RetroStoreUser> users = userManagement.getAllUsers();
    StringBuilder builder = new StringBuilder();

    for (RetroStoreUser user : users) {
      builder.append(Template.fromFile("WEB-INF/html/user/user_table_row.inc.html")
          .with("e_mail", user.email)
          .with("first_name", user.firstName)
          .with("last_name", user.lastName)
          .with("role", user.type.name())
          .render());
    }
    return Template.fromFile("WEB-INF/html/user/manage_users.inc.html")
        .withHtml("user_rows", builder.toString());
  }
}
