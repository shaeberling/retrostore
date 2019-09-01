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

import java.util.Optional;

/**
 * Manages RetorCard data such as firmware.
 */
public interface FirmwareManagement {

  /** Returns the latest version of the card with the given revision. */
  int getLatestVersionOf(int revision);

  /**
   * Adds a new firmware for the given revision.
   *
   * @param revision the hardware revision. If no version exists yet for this revision, version 1
   *                 will be created.
   * @param data     the data of the firmware to upload.
   * @return The version of the new firmware.
   */
  int addFirmwareVersion(int revision, byte[] data);

  /**
   * Returns the firmware data.
   *
   * @param revision the hardware revision to get the firmware for.
   * @param version  the version of the firmware for this revision to get.
   * @return The firmware data, if the given version for the given revision exists.
   */
  Optional<byte[]> getFirmware(int revision, int version);

  /**
   * @return the name of the product this firmware is for, e.g. "TRS-IO" or "RetroStore Card".
   */
  String getProductName();

  // TODO: Do we need delete sometime?

  interface Creator {
    FirmwareManagement createTrsIoManagement();
    FirmwareManagement createRetrocardManagement();
  }
}
