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
import java.util.function.BooleanSupplier;
import java.util.function.Supplier;
import java.util.logging.Level;
import java.util.logging.Logger;

/** Serves a one-time, admin-only normalized catalog export from an isolated version. */
public final class MigrationCatalogExportRequest implements Request {
  public static final String PATH = "/internal/migration/catalog-export";
  public static final String CONFIRMATION_PARAMETER = "confirm";
  public static final String CONFIRMATION_VALUE = "download-sensitive-export";
  public static final String VERSION_PREFIX = "migration-export-";

  static final String FILENAME = "retrostore-catalog-export.zip";

  private static final Logger LOG = Logger.getLogger("MigrationCatalogExportRequest");
  private final BooleanSupplier mEnabled;
  private final Supplier<? extends Responder.DownloadWriter> mArchiveSupplier;

  public MigrationCatalogExportRequest(
      BooleanSupplier enabled, Supplier<? extends Responder.DownloadWriter> archiveSupplier) {
    mEnabled = Objects.requireNonNull(enabled);
    mArchiveSupplier = Objects.requireNonNull(archiveSupplier);
  }

  /** Returns whether this route may be exposed in the current App Engine environment. */
  public static boolean isEnabledEnvironment(String service, String version) {
    return "default".equals(service)
        && version != null
        && version.startsWith(VERSION_PREFIX)
        && version.length() > VERSION_PREFIX.length();
  }

  @Override
  public boolean serveUrl(RequestData requestData, Responder responder, UserService userService) {
    if (!PATH.equals(requestData.getUrl())) {
      return false;
    }
    if (!mEnabled.getAsBoolean()) {
      responder.respondNotFound();
      return true;
    }
    if (userService.getForCurrentUser() != UserAccountType.ADMIN) {
      responder.respondForbidden("You need to be an admin");
      return true;
    }
    if (requestData.getType() != RequestData.Type.GET) {
      responder.respondBadRequest("The catalog export operation only accepts GET");
      return true;
    }
    if (!CONFIRMATION_VALUE.equals(
        requestData.getString(CONFIRMATION_PARAMETER).orElse(""))) {
      responder.respondBadRequest("Catalog export confirmation is required");
      return true;
    }

    try {
      Responder.DownloadWriter archive = Objects.requireNonNull(mArchiveSupplier.get());
      responder.respondSensitiveDownload(archive, FILENAME, Responder.ContentType.ZIP);
    } catch (RuntimeException e) {
      LOG.log(Level.SEVERE, "Cannot create normalized catalog export.", e);
      responder.respondInternalServerError("Catalog export failed");
    }
    return true;
  }
}
