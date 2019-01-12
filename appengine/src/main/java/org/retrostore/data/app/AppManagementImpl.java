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

import com.google.common.base.Preconditions;
import com.google.common.base.Strings;
import com.googlecode.objectify.Key;
import org.retrostore.data.BlobstoreWrapper;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.logging.Logger;

import static com.googlecode.objectify.ObjectifyService.ofy;

/**
 * Default app management implementation.
 */
public class AppManagementImpl implements AppManagement {
  private static final Logger LOG = Logger.getLogger("AppManagementImpl");
  private final BlobstoreWrapper mBlobstore;
  private final AppSearch mAppSearch;

  public AppManagementImpl(BlobstoreWrapper blobstore, AppSearch appSearch) {
    mBlobstore = blobstore;
    mAppSearch = appSearch;
  }

  @Override
  public void addOrChangeApp(AppStoreItem app) {
    app.setUpdateAndPublishTime();
    ofy().save().entity(app).now();
    mAppSearch.addOrUpdate(app);
  }

  @Override
  public Optional<AppStoreItem> getAppById(String id) {
    return Optional.ofNullable(ofy().load().key(AppStoreItem.key(id)).now());
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
  public long addMediaImage(String appId, String filename, byte[] data) {
    Preconditions.checkArgument(!Strings.isNullOrEmpty(appId));
    Preconditions.checkArgument(data.length > 0);

    MediaImage mediaImage = new MediaImage();
    mediaImage.appId = appId;
    mediaImage.filename = filename;
    mediaImage.data = data;
    mediaImage.uploadTime = System.currentTimeMillis();

    Key<MediaImage> key = ofy().save().entity(mediaImage).now();
    return key.getId();
  }

  @Override
  public Map<Long, MediaImage> getMediaImagesForApp(String appId) {
    Preconditions.checkArgument(!Strings.isNullOrEmpty(appId));
    List<MediaImage> media = ofy().load().type(MediaImage.class).filter("appId", appId).list();
    Map<Long, MediaImage> keyedResult = new HashMap<>(media.size());
    for (MediaImage mediaImage : media) {
      keyedResult.put(mediaImage.id, mediaImage);
    }
    return keyedResult;
  }

  @Override
  public void deleteMediaImage(long mediaId) {
    if (mediaId == 0) {
      return;
    }
    ofy().delete().key(MediaImage.key(mediaId)).now();
  }

  @Override
  public long[] deleteMediaImagesForApp(String appId) {
    Optional<AppStoreItem> appById = getAppById(appId);
    if (!appById.isPresent()) {
      return new long[0];
    }
    LOG.info("About to delete all media for app ID: " + appId);

    AppStoreItem.Trs80Extension trs80 = appById.get().trs80Extension;
    List<Key<MediaImage>> toDelete = new ArrayList<>();
    // Note, add delete routines for other platforms here.
    for (long id : trs80.disk) {
      if (id != 0) {
        toDelete.add(MediaImage.key(id));
      }
    }
    if (trs80.cassette != 0) {
      toDelete.add(MediaImage.key(trs80.cassette));
    }
    if (trs80.command != 0) {
      toDelete.add(MediaImage.key(trs80.command));
    }
    if (trs80.basic != 0) {
      toDelete.add(MediaImage.key(trs80.basic));
    }
    ofy().delete().keys(toDelete).now();
    LOG.info("Deleted " + toDelete.size() + " items.");

    long[] result = new long[toDelete.size()];
    for (int i = 0; i < result.length; ++i) {
      result[i] = toDelete.get(i).getId();
    }
    return result;
  }

  @Override
  public List<AppStoreItem> getAllApps() {
    return ofy().load().type(AppStoreItem.class).list();
  }

  @Override
  public List<String> searchApps(String query) {
    return mAppSearch.search(query);
  }

  @Override
  public void removeApp(String id) {
    // Note, call this before deleting the app. We need the app to get to its media IDs.
    deleteMediaImagesForApp(id);
    // FIXME: Delete screenshots.
    ofy().delete().key(AppStoreItem.key(id)).now();
    mAppSearch.remove(id);
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
    authors.sort(Comparator.comparing(o -> o.name));
    return authors;
  }

  @Override
  public Optional<Author> getAuthorById(long id) {
    return Optional.ofNullable(ofy().load().key(Author.key(id)).now());
  }
}
