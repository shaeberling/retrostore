/*
 *  Copyright 2018, Sascha Häberling
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

package org.retrostore.data.card;

import com.googlecode.objectify.Key;
import com.googlecode.objectify.annotation.Cache;
import com.googlecode.objectify.annotation.Entity;
import com.googlecode.objectify.annotation.Id;
import com.googlecode.objectify.annotation.Index;

@Entity
@Cache
public class RetroCardFirmware {

  @Id
  public String id;

  @Index
  public int revision;

  @Index
  public int version;

  /** Will become a GAE blob structure. */
  public byte[] data;

  RetroCardFirmware() {
  }

  public RetroCardFirmware(int revision, int version, byte[] data) {
    this.id = createId(revision, version);
    this.revision = revision;
    this.version = version;
    this.data = data;
  }

  public static Key<RetroCardFirmware> key(int revision, int version) {
    return Key.create(RetroCardFirmware.class, createId(revision, version));
  }

  private static String createId(int revision, int version) {
    return String.format("%d-%d", revision, version);
  }


}
