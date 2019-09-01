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

package org.retrostore.request;

import org.retrostore.data.card.FirmwareManagement;
import org.retrostore.data.user.UserAccountType;
import org.retrostore.data.user.UserService;
import org.retrostore.resources.ResourceLoader;
import org.retrostore.util.NumUtil;

import java.util.Optional;

/**
 * Handles a variety of requests: - GET to /trs-io will return the HTML interface to upload new
 * firmware. - GET to /trs-io/[revision]/version returns the latest version for this revision. - GET
 * to /trs-io/[revision]/firmware return the latest firmware data for the revision. - POST to
 * /trs-io?revision=[...] will upload a new firmware and increment the version.
 *
 * <p>To support requests for the older RetroCard, al requests will be serves through /card.
 */
public final class RetroCardRequests {
  private static final String PATH_SERVE_RETROCARD = "/card";
  private static final String PATH_SERVE_TRSIO = "/trs-io";
  private static final String REQ_VERSION = "version";
  private static final String REQ_FIRMWARE = "firmware";
  private static final String PARAM_REVISION = "revision";
  private static final String HTML_PATH = "WEB-INF/html/retrocard.html.inc";

  public static class AdminFrontendRequest implements Request {
    private final ResourceLoader mResourceLoader;
    private final FirmwareManagement.Creator mManagementCreator;

    public AdminFrontendRequest(
        ResourceLoader resourceLoader, FirmwareManagement.Creator managementCreator) {
      mResourceLoader = resourceLoader;
      mManagementCreator = managementCreator;
    }

    @Override
    public boolean serveUrl(RequestData requestData, Responder responder, UserService userService) {
      String url = requestData.getUrl();
      if (!url.equals(PATH_SERVE_RETROCARD) && !url.equals(PATH_SERVE_TRSIO)) {
        return false;
      }
      // Depending on the URL we choose a different manager.
      FirmwareManagement management =
          url.startsWith(PATH_SERVE_RETROCARD)
              ? mManagementCreator.createRetrocardManagement()
              : mManagementCreator.createTrsIoManagement();

      handleSiteRequest(requestData, responder, userService, management);
      return true;
    }

    private void handleSiteRequest(
        RequestData requestData,
        Responder responder,
        UserService userService,
        FirmwareManagement management) {
      if (userService.getForCurrentUser() != UserAccountType.ADMIN) {
        responder.respondForbidden("You must be an admin to access this tool.");
        return;
      }

      if (requestData.getFiles().size() > 1) {
        responder.respondBadRequest("Upload a single file only.");
        return;
      }

      // If there are files in this request it means that a new firmware has been uploaded.
      if (requestData.getFiles().size() == 1) {
        Optional<Integer> revision = requestData.getInt(PARAM_REVISION);
        if (!revision.isPresent()) {
          responder.respondBadRequest("File upload is missing 'revision' parameter.");
        } else {
          int newVersion =
              management.addFirmwareVersion(revision.get(), requestData.getFiles().get(0).content);
          responder.respond(
              String.format(
                  "Firmware for revision %d added successfully as version" + " %d",
                  revision.get(), newVersion),
              Responder.ContentType.PLAIN);
        }
      } else {
        // Serve the HTML interface to upload new firmware.
        Optional<byte[]> htmlBytes = mResourceLoader.load(HTML_PATH);
        if (!htmlBytes.isPresent()) {
          responder.respondNotFound();
        } else {
          String html =
              new String(htmlBytes.get()).replace("<!--PRODUCT-->", management.getProductName());
          responder.respond(html, Responder.ContentType.HTML);
        }
      }
    }
  }

  /**
   * Handles the requests that do not need to be authenticated and will return the firmware and
   * version data.
   */
  public static class ApiRequest implements Request {
    private final FirmwareManagement.Creator mManagementCreator;

    public ApiRequest(FirmwareManagement.Creator managementCreator) {
      mManagementCreator = managementCreator;
    }

    @Override
    public boolean serveUrl(RequestData requestData, Responder responder, UserService userService) {
      // URL needs to start with the path but may not be exaclty it, since that request is served
      // by the frontend request above.
      String url = requestData.getUrl();
      if ((!url.startsWith(PATH_SERVE_TRSIO) && !url.startsWith(PATH_SERVE_RETROCARD))
          || url.equals(PATH_SERVE_TRSIO)
          || url.equals(PATH_SERVE_RETROCARD)) {
        return false;
      }

      // Depending on the URL we choose a different manager.
      FirmwareManagement management =
          url.startsWith(PATH_SERVE_RETROCARD)
              ? mManagementCreator.createRetrocardManagement()
              : mManagementCreator.createTrsIoManagement();

      // Other than the main /card request, the other two are getting the latest version and
      // firmware for a revision. The URL is in the form of /card/[revision]/{version/firmware}
      // so it must have three parts to it.
      // Remove leading '/' to do a clean split.
      String[] urlParts = url.substring(1).split("/");
      if (urlParts.length != 3) {
        responder.respondBadRequest("Invalid URL format.");
        return true;
      }

      Optional<Integer> revisionOpt = NumUtil.parseInteger(urlParts[1]);
      if (!revisionOpt.isPresent()) {
        responder.respondBadRequest(String.format("Revision is not a number: '%s'.", urlParts[1]));
        return true;
      }
      final int revision = revisionOpt.get();
      String request = urlParts[2];
      int latestVersion = management.getLatestVersionOf(revision);
      if (REQ_VERSION.equals(request)) {
        responder.respond(String.valueOf(latestVersion), Responder.ContentType.PLAIN);
      } else if (REQ_FIRMWARE.equals(request)) {
        Optional<byte[]> firmware = management.getFirmware(revision, latestVersion);
        if (!firmware.isPresent()) {
          responder.respondBadRequest("Cannot find firmware data.");
        } else {
          responder.respond(firmware.get(), Responder.ContentType.BYTES);
        }
      } else {
        responder.respondBadRequest(String.format("Unknown request: '%s'.", request));
      }
      return true;
    }
  }
}
