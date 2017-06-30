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

package org.retrostore.data.app;

import com.google.common.base.Optional;
import com.google.common.base.Preconditions;
import com.google.common.base.Strings;
import com.googlecode.objectify.Key;

import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.logging.Logger;

import static com.googlecode.objectify.ObjectifyService.ofy;

/**
 * Functionality to manage apps.
 */
public class AppManagement {
  private static final Logger LOG = Logger.getLogger("AppManagement");

  /**
   * Adds a new app, or if it already exists, changes the existing one with the given ID.
   */
  public void addOrChangeApp(AppStoreItem app) {
    ofy().save().entity(app).now();
  }

  /**
   * Loads an app from the data store.
   *
   * @param id the ID of the app to retrieve.
   * @return The AppStoreItem instance for the app, if it exists.
   */
  public Optional<AppStoreItem> getAppById(long id) {
    return Optional.fromNullable(ofy().load().key(AppStoreItem.key(id)).now());
  }

  /**
   * Returns a list of all apps int the data store.
   */
  public List<AppStoreItem> getAllApps() {
    return ofy().load().type(AppStoreItem.class).list();
  }

  /**
   * Deletes the app with the given ID an all the data associated with it, like disk images and
   * screenshots.
   */
  public void removeApp(long id) {
    ofy().delete().key(AppStoreItem.key(id)).now();

    // FIXME: Delete screenshots + disk images.
  }


  /**
   * Stores an author with the given name, if it does not exist.
   *
   * @param name the name of the author
   * @return The key of the newly added or existing author with the given name.
   */
  public long ensureAuthorExists(String name) {
    Preconditions.checkArgument(!Strings.isNullOrEmpty(name));

    List<Author> existingAuthors = ofy().load().type(Author.class).filter("name ==", name).list();
    if (existingAuthors.size() > 0) {
      LOG.info(String.format("Author '%s' already exists.", name));
      if (existingAuthors.size() > 1) {
        LOG.severe(String.format("We have multiple author entries for '%s'", name));
      }
      return existingAuthors.get(0).id;
    }
    Key<Author> newAuthorKey = ofy().save().entity(new Author(name)).now();
    return newAuthorKey.getId();
  }

  /**
   * Returns a list of all app authors.
   */
  public List<Author> listAuthors() {
    List<Author> authors = ofy().load().type(Author.class).list();
    Collections.sort(authors, new Comparator<Author>() {
      @Override
      public int compare(Author o1, Author o2) {
        // Sort authors by name.
        return o1.name.compareTo(o2.name);
      }
    });
    return authors;
  }
}
