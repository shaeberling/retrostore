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

package org.retrostore.data.app;

import com.google.common.base.Preconditions;
import com.google.common.base.Strings;
import com.googlecode.objectify.Key;
import com.googlecode.objectify.annotation.Cache;
import com.googlecode.objectify.annotation.Entity;
import com.googlecode.objectify.annotation.Id;
import com.googlecode.objectify.annotation.Index;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

import static com.google.common.base.Preconditions.checkNotNull;

/**
 * An app store item (TPK) such as a game or application.
 */
@Entity
@Cache
public class AppStoreItem {
  /** Types of platform the app store item is intended for. */
  public enum Platform {
    TRS80("TRS-80");

    private final String readableName;

    Platform(String readableName) {
      this.readableName = checkNotNull(readableName);
    }

    @Override
    public String toString() {
      return readableName;
    }
  }

  public enum Model {
    MODEL_I("Model I"),
    MODEL_III("Model III"),
    MODEL_4("Model 4"),
    MODEL_4P("Model 4P");

    private final String readableName;

    Model(String readableName) {
      this.readableName = checkNotNull(readableName);
    }

    @Override
    public String toString() {
      return readableName;
    }
  }

  public enum ListingCategory {
    GAME("Game"),
    GAME_ARCADE("Game/Arcade"),
    OFFICE("Office"),
    OTHER("Other");

    private final String readableName;

    ListingCategory(String readableName) {
      this.readableName = readableName;
    }

    @Override
    public String toString() {
      return readableName;
    }
  }

  /**
   * Trs80Extension data (for TRS-80 specifically).
   */
  public static class Trs80Extension {
    public Model model;

    // Disk 1-4 + cassette (type/extension + data)
    // These are IDs for the media images.
    public long[] disk = new long[4];
    public long cassette;
    public long command;
  }

  /**
   * Listing data.
   */
  public static class Listing {
    public String name;
    public String versionString;
    public String description;
    public Set<ListingCategory> categories = new HashSet<>();
    public long firstPublishTime;
    public long lastUpdateTime;
    public long authorId;
    public String publisherEmail;
    public int releaseYear;
  }

  /**
   * Create a key for ann AppStoreItem based on its unique ID.
   */
  public static Key<AppStoreItem> key(String id) {
    return Key.create(AppStoreItem.class, id);
  }

  public AppStoreItem() {
    // Generate a new ID for this app.
    id = UUID.randomUUID().toString();
  }

  public AppStoreItem(String newId) {
    Preconditions.checkArgument(!Strings.isNullOrEmpty(newId), "ID may not be empty.");
    id = newId;
  }

  @Id
  public String id;

  @Index
  public Platform platform = Platform.TRS80;

  /** Listing information, relevant for all apps. */
  public Listing listing = new Listing();

  /** The blobkeys of the screenshots to serve. */
  public List<String> screenshotsBlobKeys = new ArrayList<>();

  // Platform-specific extensions go here...
  public Trs80Extension trs80Extension = new Trs80Extension();


  void setUpdateAndPublishTime() {
    // Ensure the times are set correctly.
    final long now = System.currentTimeMillis();
    if (listing.firstPublishTime <= 0) {
      listing.firstPublishTime = now;
    }
    listing.lastUpdateTime = now;
  }
}
