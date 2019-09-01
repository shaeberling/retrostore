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

package org.retrostore;

import com.google.appengine.api.blobstore.BlobstoreService;
import com.google.appengine.api.blobstore.BlobstoreServiceFactory;
import com.google.appengine.api.images.ImagesService;
import com.google.appengine.api.images.ImagesServiceFactory;
import com.google.appengine.api.memcache.MemcacheServiceFactory;
import com.google.appengine.api.search.SearchService;
import com.google.appengine.api.search.SearchServiceFactory;
import com.google.appengine.api.users.UserServiceFactory;
import com.google.common.base.Strings;
import com.google.common.collect.ImmutableList;
import org.retrostore.data.BlobstoreWrapper;
import org.retrostore.data.BlobstoreWrapperImpl;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.app.AppManagementCached;
import org.retrostore.data.app.AppManagementImpl;
import org.retrostore.data.app.AppSearch;
import org.retrostore.data.app.AppSearchImpl;
import org.retrostore.data.card.FirmwareManagement;
import org.retrostore.data.card.FirmwareManagementImpl;
import org.retrostore.data.user.UserManagement;
import org.retrostore.data.user.UserService;
import org.retrostore.data.user.UserServiceImpl;
import org.retrostore.request.Cache;
import org.retrostore.request.DownloadAppRequest;
import org.retrostore.request.EnsureAdminExistsRequest;
import org.retrostore.request.FaviconRequest;
import org.retrostore.request.ForwardingRequest;
import org.retrostore.request.ImportRpkRequest;
import org.retrostore.request.LoginRequest;
import org.retrostore.request.PingRequest;
import org.retrostore.request.PolymerRequest;
import org.retrostore.request.PublicSiteRequest;
import org.retrostore.request.ReportAppRequest;
import org.retrostore.request.Request;
import org.retrostore.request.RequestData;
import org.retrostore.request.RequestData.Type;
import org.retrostore.request.RequestDataImpl;
import org.retrostore.request.Responder;
import org.retrostore.request.RetroCardRequests;
import org.retrostore.request.ScreenshotRequest;
import org.retrostore.request.StaticFileRequest;
import org.retrostore.request.TwoLayerCacheImpl;
import org.retrostore.request.UpdateDataRequest;
import org.retrostore.resources.CachingImageService;
import org.retrostore.resources.DefaultResourceLoader;
import org.retrostore.resources.ImageServiceWrapper;
import org.retrostore.resources.ImageServiceWrapperImpl;
import org.retrostore.resources.MailService;
import org.retrostore.resources.MailServiceImpl;
import org.retrostore.resources.MemcacheWrapper;
import org.retrostore.resources.MemcacheWrapperImpl;
import org.retrostore.resources.PolymerDebugLoader;
import org.retrostore.resources.ResourceLoader;
import org.retrostore.rpc.internal.ApiRequest;
import org.retrostore.rpc.internal.PostUploadRequest;
import org.retrostore.rpc.internal.RpcCallRequest;

import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.List;
import java.util.logging.Logger;

/** Enables adding/removing of users. */
public class MainServlet extends RetroStoreServlet {
  private static final Logger LOG = Logger.getLogger("MainServlet");

  private static final Object sModuleLock = new Object();
  private static Modules sModules;
  private static List<Request> sRequestServers;

  /** All global modules needed throughout the application. */
  static class Modules {
    com.google.appengine.api.users.UserService userService = UserServiceFactory.getUserService();
    BlobstoreService blobstoreService = BlobstoreServiceFactory.getBlobstoreService();
    BlobstoreWrapper blobstoreWrapper = new BlobstoreWrapperImpl(blobstoreService);
    UserManagement userManagement = new UserManagement(userService);
    SearchService searchService = SearchServiceFactory.getSearchService();
    AppSearch appSearch = new AppSearchImpl(searchService);
    AppManagement appManagement =
        new AppManagementCached(new AppManagementImpl(blobstoreWrapper, appSearch));
    UserService accountTypeProvider = new UserServiceImpl(userManagement, userService);
    ImagesService imagesService = ImagesServiceFactory.getImagesService();
    MemcacheWrapper memcache = new MemcacheWrapperImpl(MemcacheServiceFactory.getMemcacheService());
    ImageServiceWrapper imgServWrapper =
        new CachingImageService(new ImageServiceWrapperImpl(imagesService), memcache);
    Cache cache = new TwoLayerCacheImpl(memcache);
    DefaultResourceLoader defaultResourceLoader = new DefaultResourceLoader(cache);
    MailService mailService = new MailServiceImpl();
    FirmwareManagement.Creator firmwareManagementCreator =
        new FirmwareManagementImpl.FirmwareManagementCreator();
  }

  private static List<Request> createRequests(Modules m) {
    return ImmutableList.of(
        new FaviconRequest(m.defaultResourceLoader),
        new PingRequest(),
        new ForwardingRequest(),
        new PublicSiteRequest(m.defaultResourceLoader),
        new ReportAppRequest(
            m.defaultResourceLoader, m.appManagement, m.imgServWrapper, m.mailService),
        new DownloadAppRequest(m.appManagement),
        new RetroCardRequests.ApiRequest(m.firmwareManagementCreator),

        // Every request above this line does not require a logged in user.
        new LoginRequest(),
        new EnsureAdminExistsRequest(m.userManagement),
        new RetroCardRequests.AdminFrontendRequest(
            getResourceLoader(m), m.firmwareManagementCreator),
        new ImportRpkRequest(
            (getResourceLoader(m)), m.appManagement, m.userManagement, m.blobstoreWrapper),
        new RpcCallRequest(m.userManagement, m.appManagement, m.imgServWrapper),
        new ScreenshotRequest(m.blobstoreWrapper, m.appManagement, m.imgServWrapper),
        new PolymerRequest(getResourceLoader(m)),
        new StaticFileRequest(m.defaultResourceLoader),
        new PostUploadRequest(m.appManagement),
        new ApiRequest(m.appManagement, m.imgServWrapper),
        new UpdateDataRequest(m.appSearch, m.appManagement)
        // Note: Add more request servers here. Keep in mind that this is in priority-order.
        );
  }

  private static ResourceLoader getResourceLoader(Modules m) {
    String polymerDebugServer = System.getProperty("retrostore.debug.polymer");
    if (Strings.isNullOrEmpty(polymerDebugServer)) {
      return m.defaultResourceLoader;
    } else {
      LOG.info(
          String.format("Initializing Polymer debug loader with URL: '%s'", polymerDebugServer));
      return new PolymerDebugLoader(polymerDebugServer, m.defaultResourceLoader);
    }
  }

  @Override
  protected void doGet(HttpServletRequest req, HttpServletResponse resp) throws IOException {
    serveMainHtml(req, resp, Type.GET);
  }

  @Override
  protected void doPost(HttpServletRequest req, HttpServletResponse resp) throws IOException {
    serveMainHtml(req, resp, Type.POST);
  }

  private void serveMainHtml(HttpServletRequest req, HttpServletResponse resp, Type type)
      throws IOException {
    synchronized (sModuleLock) {
      if (sModules == null) {
        sModules = new Modules();
      }
      if (sRequestServers == null) {
        sRequestServers = createRequests(sModules);
      }
    }

    RequestData requestData = RequestDataImpl.create(req, type, sModules.blobstoreService);
    Responder responder = new Responder(resp, sModules.blobstoreService);
    for (Request server : sRequestServers) {
      if (server.serveUrl(requestData, responder, sModules.accountTypeProvider)) {
        return;
      }
    }
    resp.sendError(HttpServletResponse.SC_NOT_FOUND);
  }
}
