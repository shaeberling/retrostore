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

import com.google.common.collect.ImmutableList;
import org.retrostore.data.user.UserAccountType;
import org.retrostore.data.user.UserService;
import org.retrostore.ui.Template;

import java.io.IOException;
import java.util.List;
import java.util.logging.Logger;

/**
 * Checks whether the current URL needs a logged-in user. If so, will ensure the user is forwarded
 * to the login-page first.
 */
public class LoginRequest implements Request {
  private static final Logger LOG = Logger.getLogger("PolymerRequest");
  private static List<String> sLoginPrefixes = getLoginPrefixes();

  private static List<String> getLoginPrefixes() {
    return ImmutableList.of("/index.html", "/admin");
  }

  private boolean matchesPrefix(String url) {
    for (String prefix : sLoginPrefixes) {
      if (url.startsWith(prefix)) {
        return true;
      }
    }
    return false;
  }


  @Override
  public boolean serveUrl(RequestData requestData, Responder responder, UserService userService) {
    // TODO: At the moment, there is not non-admin user-visible page. Once that exists and we
    // have moved the admin portion to /admin, this filter can go away since we do not require
    // normal users to be logged in.
    if (!requestData.getUrl().equals("/") && !matchesPrefix(requestData.getUrl())) {
      return false;
    }

    // If the user is not logged in, forward to login page.
    if (userService.getForCurrentUser() == UserAccountType.NOT_LOGGED_IN) {
      try {
        String thisUrl = requestData.getUrl();
        String html = Template.fromFile("WEB-INF/html/login_forward.html")
            .with("forwarding_url", userService.createLoginURL(thisUrl))
            .render();
        responder.respond(html, Responder.ContentType.HTML);
      } catch (IOException ex) {
        responder.respondBadRequest("There was an internal error.");
      }
      return true;
    }
    return false;
  }
}
