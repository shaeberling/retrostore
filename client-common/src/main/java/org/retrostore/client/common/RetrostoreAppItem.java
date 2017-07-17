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

package org.retrostore.client.common;

import java.util.List;

/** A Retrostore app item. */
public class RetrostoreAppItem {
  /** A media image such as a disk or casette image. */
  public static final class MediaImage {
    /** The types for a media image. */
    public enum Type {
      DISK,
      CASETTE
    }

    public MediaImage(Type type, String filename, byte[] data, long uploadTime, String description) {
      this.type = type;
      this.filename = filename;
      this.data = data;
      this.uploadTime = uploadTime;
      this.description = description;
    }

    /** The type of this media image. */
    public final Type type;
    /** The file name of this media image. */
    public final String filename;
    /** The actual data of this media image. */
    public final byte[] data;
    /** When the image was uploaded. */
    public final long uploadTime;
    /** An optional description of this media image describing its contents. */
    public final String description;
  }

  /** The ID to uniquely identify an app. */
  public long id;
  /** The name of the app. */
  public String name;
  /** The human readable version of this app. */
  public String version;
  /** The description of this app. */
  public String description;
  /** URLS to screenshots. */
  public String[] screenshotUrls;
  /** The media images included with this app. */
  public List<MediaImage> mediaImages;

}

