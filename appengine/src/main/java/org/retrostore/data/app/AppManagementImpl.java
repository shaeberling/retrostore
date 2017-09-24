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
import org.retrostore.data.BlobstoreWrapper;

import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.logging.Logger;

import static com.googlecode.objectify.ObjectifyService.ofy;

/**
 * Default app management implementation.
 */
public class AppManagementImpl implements AppManagement {
  private static final Logger LOG = Logger.getLogger("AppManagementImpl");
  private final BlobstoreWrapper mBlobstore;

  public AppManagementImpl(BlobstoreWrapper blobstore) {
    mBlobstore = blobstore;
  }

  @Override
  public void addOrChangeApp(AppStoreItem app) {
    app.setUpdateAndPublishTime();
    ofy().save().entity(app).now();
  }

  @Override
  public Optional<AppStoreItem> getAppById(String id) {
    return Optional.fromNullable(ofy().load().key(AppStoreItem.key(id)).now());
  }

  @Override
  public boolean addScreenshot(String id, String blobKey) {
    Optional<AppStoreItem> appOpt = getAppById(id);
    if (!appOpt.isPresent()) {
      LOG.warning("App not found for adding screenshot: " + id);
      return false;
    }
    appOpt.get().screenshotsBlobKeys.add(blobKey);
    addOrChangeApp(appOpt.get());
    return true;
  }

  @Override
  public boolean removeScreenshot(String id, String blobKey) {
    // First delete the blob itself.
    mBlobstore.deleteBlob(blobKey);

    // Then remove the blob from the app that referenced it.
    Optional<AppStoreItem> appOpt = getAppById(id);
    if (!appOpt.isPresent()) {
      LOG.warning("App not found for adding screenshot: " + id);
      return false;
    }
    if (!appOpt.get().screenshotsBlobKeys.remove(blobKey)) {
      LOG.warning("Screenshot with the given key was not found: " + blobKey);
      return false;
    }
    addOrChangeApp(appOpt.get());
    return true;
  }

  @Override
  public List<AppStoreItem> getAllApps() {
    return ofy().load().type(AppStoreItem.class).list();
  }

  @Override
  public void removeApp(String id) {
    ofy().delete().key(AppStoreItem.key(id)).now();

    // FIXME: Delete screenshots + disk images.
  }

  @Override
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

  @Override
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

  @Override
  public Optional<Author> getAuthorById(long id) {
    return Optional.fromNullable(ofy().load().key(Author.key(id)).now());
  }
}