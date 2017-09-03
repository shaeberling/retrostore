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

package org.retrostore.data.app;

import com.google.common.base.Optional;

import java.util.List;

/**
 * Functionality to manage apps.
 */
public interface AppManagement {
  /**
   * Adds a new app, or if it already exists, changes the existing one with the given ID.
   */
  void addOrChangeApp(AppStoreItem app);

  /**
   * Loads an app from the data store.
   *
   * @param id the ID of the app to retrieve.
   * @return The AppStoreItem instance for the app, if it exists.
   */
  Optional<AppStoreItem> getAppById(long id);

  /**
   * Adds a screenshot's blob key for the app with the given ID.
   *
   * @param appId   the ID of the app to add the screenshot to.
   * @param blobKey the blob key of the screenshot to add.
   * @return Whether the screenshot was successfully added.
   */
  boolean addScreenshot(long appId, String blobKey);

  /**
   * Remove a screenshot's blob key for the app with the given ID.
   *
   * @param appId   the ID of the app to add the screenshot to.
   * @param blobKey the blob key of the screenshot to remove.
   * @return Whether the screenshot was successfully removed.
   */
  boolean removeScreenshot(long appId, String blobKey);

  /**
   * Returns a list of all apps int the data store.
   */
  List<AppStoreItem> getAllApps();

  /**
   * Deletes the app with the given ID an all the data associated with it, like disk images and
   * screenshots.
   */
  void removeApp(long id);

  /**
   * Stores an author with the given name, if it does not exist.
   *
   * @param name the name of the author
   * @return The key of the newly added or existing author with the given name.
   */
  long ensureAuthorExists(String name);

  /**
   * Returns a list of all app authors.
   */
  List<Author> listAuthors();

  /** Returns the author with the given ID, if it exists. */
  Optional<Author> getAuthorById(long id);
}
