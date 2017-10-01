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

package org.retrostore.request;

import com.google.common.base.Optional;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.data.user.UserService;
import org.retrostore.resources.ImageServiceWrapper;
import org.retrostore.resources.MailService;
import org.retrostore.resources.ResourceLoader;
import org.retrostore.ui.Template;

import java.util.logging.Logger;

/**
 * Request to serve a form and collect data on users reporting apps.
 */
public class ReportAppRequest implements Request {
  private static final Logger LOG = Logger.getLogger("ReportAppReq");
  private static final String[] MAIL_TO = {"sascha@retrostore.org", "arno@retrostore.org",};
  private static final int SCREENSHOT_SIZE = 800;
  private final ResourceLoader mResourceLoader;
  private final AppManagement mAppManagement;
  private final ImageServiceWrapper mImageService;
  private final MailService mMailService;

  public ReportAppRequest(ResourceLoader resourceLoader,
                          AppManagement appManagement,
                          ImageServiceWrapper imageService,
                          MailService mailService) {
    mResourceLoader = resourceLoader;
    mAppManagement = appManagement;
    mImageService = imageService;
    mMailService = mailService;
  }

  @Override
  public boolean serveUrl(RequestData requestData, Responder responder, UserService userService) {
    if (!requestData.getUrl().startsWith("/reportapp")) {
      return false;
    }

    if (requestData.getType() == RequestData.Type.GET) {
      Optional<String> appId = requestData.getString("appId");
      if (!appId.isPresent()) {
        responder.respondBadRequest("'appId' missing.");
      } else {
        serveGet(appId.get(), responder);
      }
    } else {
      servePost(requestData, responder);
    }
    return true;
  }

  private void servePost(RequestData requestData, Responder responder) {
    Optional<String> appid = requestData.getString("appId");
    Optional<String> reporterName = requestData.getString("reporter_name");
    Optional<String> reporterEmail = requestData.getString("reporter_email");
    Optional<String> message = requestData.getString("message");

    if (!appid.isPresent() || appid.get().trim().isEmpty()) {
      responder.respondBadRequest("No appId given");
      return;
    }
    if (!reporterName.isPresent() || reporterName.get().trim().isEmpty()) {
      responder.respondBadRequest("You need to enter your name");
      return;
    }
    if (!reporterEmail.isPresent() || reporterEmail.get().trim().isEmpty()) {
      responder.respondBadRequest("You need to enter your email address");
      return;
    }
    if (!message.isPresent() || message.get().trim().isEmpty()) {
      responder.respondBadRequest("Your message cannot be empty.");
      return;
    }

    Optional<AppStoreItem> appOpt = mAppManagement.getAppById(appid.get());
    if (!appOpt.isPresent()) {
      responder.respondBadRequest("Cannot find app with the given ID..");
      return;
    }

    String emailMessage = " AppId            : " + appid.or("n/a") + "\n";
    emailMessage += " App Name         : " + appOpt.get().listing.name + "\n";
    emailMessage += " Reporter Name    : " + reporterName.or("n/a") + "\n";
    emailMessage += " Reporter Email   : " + reporterEmail.or("n/a") + "\n";
    emailMessage += " Message:\n" + message.or("n/a") + "\n";
    boolean success = mMailService.sendEmail(MAIL_TO, "New app report received", emailMessage);
    if (!success) {
      responder.respond("There was an error sending your message. Try again later.",
          Responder.ContentType.HTML);
    } else {
      responder.respond("Thank you, your message has been received.", Responder.ContentType.HTML);
      LOG.info("Report e-mail successfully sent.");
    }
  }

  private void serveGet(String appId, Responder responder) {
    Optional<AppStoreItem> appOpt = mAppManagement.getAppById(appId);
    if (!appOpt.isPresent()) {
      responder.respondBadRequest("App not found");
      return;
    }
    AppStoreItem app = appOpt.get();

    String screenshotUrl = "";
    if (app.screenshotsBlobKeys.size() > 0) {
      Optional<String> servingUrl =
          mImageService.getServingUrl(app.screenshotsBlobKeys.get(0), SCREENSHOT_SIZE);
      screenshotUrl = servingUrl.or("");
    }

    Optional<byte[]> html = mResourceLoader.load("WEB-INF/html/report_app.html.inc");
    if (!html.isPresent()) {
      responder.respondNotFound();
      return;
    }

    responder.respond(new Template(new String(html.get()))
        .with("appTitle", app.listing.name)
        .with("appId", app.id)
        .with("screenshotUrl", screenshotUrl)
        .render(), Responder.ContentType.HTML);
  }
}
