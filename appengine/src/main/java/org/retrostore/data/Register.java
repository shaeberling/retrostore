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

package org.retrostore.data;

import com.googlecode.objectify.ObjectifyService;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.data.app.Author;
import org.retrostore.data.app.MediaImage;
import org.retrostore.data.card.RetroCardFirmware;
import org.retrostore.data.card.TrsIoFirmware;
import org.retrostore.data.user.RetroStoreUser;

/**
 * Call this to ensure all data classes are registered.
 */
public class Register {
  private static boolean isRegistered = false;

  public static void ensureRegistered() {
    if (!isRegistered) {
      ObjectifyService.register(AppStoreItem.class);
      ObjectifyService.register(Author.class);
      ObjectifyService.register(MediaImage.class);
      ObjectifyService.register(RetroCardFirmware.class);
      ObjectifyService.register(RetroStoreUser.class);
      ObjectifyService.register(TrsIoFirmware.class);
      isRegistered = true;
    }
  }
}
