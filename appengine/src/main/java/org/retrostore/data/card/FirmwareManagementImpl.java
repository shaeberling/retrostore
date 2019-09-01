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

import java.util.List;
import java.util.Optional;
import java.util.logging.Level;
import java.util.logging.Logger;

import static com.googlecode.objectify.ObjectifyService.ofy;

/** Default implementation for the {@link FirmwareManagement} interface. */
public class FirmwareManagementImpl<T extends Firmware> implements FirmwareManagement {
  private static final Logger LOG = Logger.getLogger("FirmwareManagement");
  private final Firmware.Creator<T> creator;

  protected FirmwareManagementImpl(Firmware.Creator<T> creator) {
    this.creator = creator;
  }

  @Override
  public int getLatestVersionOf(int revision) {
    // Get all entries for the given revision, sort them by version and return the highest
    // version number.
    try {
      List<T> firmwares =
          ofy()
              .load()
              .type(creator.getDataClass())
              .filter("revision == ", revision)
              .order("-version")
              .list();
      if (firmwares.isEmpty()) {
        return 0;
      }
      return firmwares.get(0).getVersion();
    } catch (DatastoreNeedIndexException e) {
      LOG.log(Level.SEVERE, "No index for firmware found.", e);
      return 0;
    }
  }

  @Override
  public int addFirmwareVersion(int revision, byte[] data) {
    int version = getLatestVersionOf(revision) + 1;
    T firmware = creator.create(revision, version, data);
    ofy().save().entity(firmware).now();
    return version;
  }

  @Override
  public Optional<byte[]> getFirmware(int revision, int version) {
    Optional<T> firmware =
        Optional.ofNullable(ofy().load().key(creator.createKey(revision, version)).now());
    return firmware.map(Firmware::getData);
  }

  @Override
  public String getProductName() {
    if (creator.getDataClass() == TrsIoFirmware.class) {
      return "TRS-IO";
    } else if (creator.getDataClass() == RetroCardFirmware.class) {
      return "RetroStore Card";
    }
    return "Unknown product";
  }

  public static class FirmwareManagementCreator implements Creator {

    @Override
    public FirmwareManagement createTrsIoManagement() {
      return new FirmwareManagementImpl<>(TrsIoFirmware.creator());
    }

    @Override
    public FirmwareManagement createRetrocardManagement() {
      return new FirmwareManagementImpl<>(RetroCardFirmware.creator());
    }
  }
}
