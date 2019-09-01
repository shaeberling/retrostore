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

/** Is stores firmware for TRS-IO (and not RetroCard). */
@Entity
@Cache
public class TrsIoFirmware implements Firmware {

  @Id public String id;

  @Index public int revision;

  @Index public int version;

  /** Will become a GAE blob structure. */
  public byte[] data;

  TrsIoFirmware() {}

  public TrsIoFirmware(int revision, int version, byte[] data) {
    this.id = createId(revision, version);
    this.revision = revision;
    this.version = version;
    this.data = data;
  }

  @Override
  public String getId() {
    return id;
  }

  @Override
  public int getRevision() {
    return revision;
  }

  @Override
  public int getVersion() {
    return version;
  }

  @Override
  public byte[] getData() {
    return data;
  }

  public static Creator<TrsIoFirmware> creator() {
    return new Creator<TrsIoFirmware>() {
      @Override
      public TrsIoFirmware create(int revision, int version, byte[] data) {
        return new TrsIoFirmware(revision, version, data);
      }

      @Override
      public Key<TrsIoFirmware> createKey(int revision, int version) {
        return Key.create(TrsIoFirmware.class, createId(revision, version));
      }

      @Override
      public Class<TrsIoFirmware> getDataClass() {
        return TrsIoFirmware.class;
      }
    };
  }

  private static String createId(int revision, int version) {
    return String.format("%d-%d", revision, version);
  }
}
