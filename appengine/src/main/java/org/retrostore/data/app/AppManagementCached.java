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
import com.google.common.base.Preconditions;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * A caching layer for app management, with the same interface.
 */
public class AppManagementCached implements AppManagement {
  /** A real app management implementation. */
  private final AppManagement mAppManagement;

  /** TODO: Handle sorting. */
  private final Map<Long, AppStoreItem> mAppCacheById;
  private final Map<Long, Author> mAuthorCacheById;

  public AppManagementCached(AppManagement appManagement) {
    mAppManagement = Preconditions.checkNotNull(appManagement);
    mAppCacheById = new HashMap<>();
    mAuthorCacheById = new HashMap<>();

    // Important: Update cache at the beginning so we can then keep it updates throoughout with
    // incremental updates only.
    updateAppCache();
  }

  @Override
  public void addOrChangeApp(AppStoreItem app) {
    mAppManagement.addOrChangeApp(app);
    mAppCacheById.put(app.id, app);
  }

  @Override
  public Optional<AppStoreItem> getAppById(long id) {
    if (mAppCacheById.containsKey(id)) {
      return Optional.of(mAppCacheById.get(id));
    }

    Optional<AppStoreItem> appOpt = mAppManagement.getAppById(id);
    if (appOpt.isPresent()) {
      mAppCacheById.put(appOpt.get().id, appOpt.get());
    }
    return appOpt;
  }

  @Override
  public boolean addScreenshot(long appId, String blobKey) {
    boolean success = mAppManagement.addScreenshot(appId, blobKey);
    updateAppCacheItem(appId);
    return success;
  }

  @Override
  public boolean removeScreenshot(long appId, String blobKey) {
    boolean success = mAppManagement.removeScreenshot(appId, blobKey);
    updateAppCacheItem(appId);
    return success;
  }

  @Override
  public List<AppStoreItem> getAllApps() {
    return new ArrayList<>(mAppCacheById.values());
  }

  @Override
  public void removeApp(long id) {
    mAppManagement.removeApp(id);
    mAppCacheById.remove(id);
  }

  @Override
  public long ensureAuthorExists(String name) {
    long id = mAppManagement.ensureAuthorExists(name);
    updateAuthorCache();
    return id;
  }

  @Override
  public List<Author> listAuthors() {
    if (mAuthorCacheById.isEmpty()) {
      updateAuthorCache();
    }
    return new ArrayList<>(mAuthorCacheById.values());
  }

  @Override
  public Optional<Author> getAuthorById(long id) {
    if (mAuthorCacheById.isEmpty()) {
      updateAuthorCache();
    }
    return Optional.fromNullable(mAuthorCacheById.get(id));
  }

  private void updateAppCacheItem(long id) {
    Optional<AppStoreItem> appOpt = mAppManagement.getAppById(id);
    if (!appOpt.isPresent()) {
      return;
    }
    AppStoreItem app = appOpt.get();
    mAppCacheById.put(app.id, app);
  }

  private void updateAppCache() {
    List<AppStoreItem> apps = mAppManagement.getAllApps();
    for (AppStoreItem app : apps) {
      mAppCacheById.put(app.id, app);
    }
  }

  private void updateAuthorCache() {
    List<Author> authors = mAppManagement.listAuthors();
    mAuthorCacheById.clear();
    for (Author author : authors) {
      mAuthorCacheById.put(author.id, author);
    }
  }
}
