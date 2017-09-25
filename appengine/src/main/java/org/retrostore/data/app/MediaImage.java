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

import com.googlecode.objectify.annotation.Cache;
import com.googlecode.objectify.annotation.Entity;
import com.googlecode.objectify.annotation.Id;
import com.googlecode.objectify.annotation.Index;

/**
 * A media image that could e.g. contain disk or cassette data.
 */
@Entity
@Cache
public class MediaImage {
  @Id
  public Long id;

  @Index
  public String appId;

  /** The timestamp of when this image was uploaded. */
  public long uploadTime;
  /**
   * The filename, including the extension. Some emulator use parts of the filename to determine how
   * to handle it.
   */
  public String filename;
  /** An optional note for this image to describe it. */
  public String description;
  /** Will become a GAE blob structure. */
  public byte[] data;

}
