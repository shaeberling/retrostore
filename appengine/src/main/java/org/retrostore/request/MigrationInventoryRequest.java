/*
 * Copyright 2026, Sascha Häberling
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

package org.retrostore.request;

import org.retrostore.data.user.UserAccountType;
import org.retrostore.data.user.UserService;

import java.util.Objects;
import java.util.function.Supplier;
import java.util.logging.Level;
import java.util.logging.Logger;

/** Serves the admin-only, read-only bundled-services migration inventory. */
public final class MigrationInventoryRequest implements Request {
  public static final String PATH = "/internal/migration/bundled-services-inventory";

  private static final Logger LOG = Logger.getLogger("MigrationInventoryRequest");
  private final Supplier<?> mReportSupplier;

  public MigrationInventoryRequest(Supplier<?> reportSupplier) {
    mReportSupplier = Objects.requireNonNull(reportSupplier);
  }

  @Override
  public boolean serveUrl(RequestData requestData, Responder responder, UserService userService) {
    if (!PATH.equals(requestData.getUrl())) {
      return false;
    }
    if (userService.getForCurrentUser() != UserAccountType.ADMIN) {
      responder.respondForbidden("You need to be an admin");
      return true;
    }
    if (requestData.getType() != RequestData.Type.GET) {
      responder.respondBadRequest("The inventory operation only accepts GET");
      return true;
    }

    try {
      responder.respondJsonNoStore(mReportSupplier.get());
    } catch (RuntimeException e) {
      LOG.log(Level.SEVERE, "Cannot build bundled-services migration inventory.", e);
      responder.respondInternalServerError("Inventory failed");
    }
    return true;
  }
}
