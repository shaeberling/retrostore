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

package org.retrostore.data.user;

import java.util.Optional;

import static com.google.common.base.Preconditions.checkNotNull;

public class UserServiceImpl implements UserService {
  private final com.google.appengine.api.users.UserService mUserService;
  private final UserManagement mUserManagement;

  public UserServiceImpl(UserManagement userManagement,
                         com.google.appengine.api.users.UserService userService) {
    mUserManagement = checkNotNull(userManagement);
    mUserService = checkNotNull(userService);
  }

  @Override
  public boolean systemHasAdmin() {
    return mUserManagement.hasAdmin();
  }

  @Override
  public UserAccountType getForCurrentUser() {
    Optional<String> loggedInEmail = mUserManagement.getLoggedInEmail();
    if (!loggedInEmail.isPresent()) {
      return UserAccountType.NOT_LOGGED_IN;
    }
    Optional<RetroStoreUser> user = mUserManagement.getUserByEmail(loggedInEmail.get());
    if (!user.isPresent()) {
      return UserAccountType.NO_ACCOUNT;
    }
    return user.get().type;
  }

  @Override
  public String createLoginURL(String url) {
    return mUserService.createLoginURL(url);
  }
}
