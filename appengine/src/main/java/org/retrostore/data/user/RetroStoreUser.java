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

package org.retrostore.data.user;

import com.googlecode.objectify.Key;
import com.googlecode.objectify.annotation.Cache;
import com.googlecode.objectify.annotation.Entity;
import com.googlecode.objectify.annotation.Id;
import com.googlecode.objectify.annotation.Index;

/**
 * Data model for a users in the TRS80 app store system.
 */
@Entity
@Cache
public class RetroStoreUser {

  /**
   * Create a key based on the email.
   */
  public static Key<RetroStoreUser> key(String email) {
    return Key.create(RetroStoreUser.class, email);
  }

  public RetroStoreUser() {
  }

  @Id
  public String email;
  public String firstName;
  public String lastName;
  @Index
  public UserAccountType type;

  // TODO: Add sanity checks before persisting the data.
}
