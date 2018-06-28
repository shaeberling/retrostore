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

import com.google.appengine.api.datastore.DatastoreNeedIndexException;
import com.google.common.base.Optional;

import java.util.List;
import java.util.logging.Level;
import java.util.logging.Logger;

import static com.googlecode.objectify.ObjectifyService.ofy;

/**
 * Default implementation for the {@link RetroCardManagement} interface.
 */
public class RetroCardManagementImpl implements RetroCardManagement {
  private static final Logger LOG = Logger.getLogger("RetroCardManagement");

  @Override
  public int getLatestVersionOf(int revision) {
    // Get all entries for the given revision, sort them by version and return the highest
    // version number.
    try {
      List<RetroCardFirmware> firmwares = ofy().load()
          .type(RetroCardFirmware.class)
          .filter("revision == ", revision)
          .order("-version")
          .list();
      if (firmwares.isEmpty()) {
        return 0;
      }
      return firmwares.get(0).version;
    } catch (DatastoreNeedIndexException e) {
      LOG.log(Level.SEVERE, "No index for firmware found.", e);
      return 0;
    }
  }

  @Override
  public int addFirmwareVersion(int revision, byte[] data) {
    int version = getLatestVersionOf(revision) + 1;
    RetroCardFirmware firmware = new RetroCardFirmware(revision, version, data);
    ofy().save().entity(firmware).now();
    return version;
  }

  @Override
  public Optional<byte[]> getFirmware(int revision, int version) {
    Optional<RetroCardFirmware> firmware = Optional.fromNullable(ofy().load()
        .key(RetroCardFirmware.key(revision, version)).now());
    if (firmware.isPresent()) {
      return Optional.fromNullable(firmware.get().data);
    }
    return Optional.absent();
  }
}
