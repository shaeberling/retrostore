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

import com.google.appengine.api.users.UserServiceFactory;
import com.google.common.base.Strings;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.user.UserManagement;
import org.retrostore.data.user.UserService;
import org.retrostore.data.user.UserServiceImpl;
import org.retrostore.request.EnsureAdminExistsRequest;
import org.retrostore.request.LoginRequest;
import org.retrostore.request.PolymerRequest;
import org.retrostore.request.Request;
import org.retrostore.request.RequestDataImpl;
import org.retrostore.request.Responder;
import org.retrostore.resources.DefaultResourceLoader;
import org.retrostore.resources.PolymerDebugLoader;
import org.retrostore.resources.ResourceLoader;
import org.retrostore.rpc.internal.RpcCallRequest;

import javax.servlet.ServletException;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.logging.Logger;

/**
 * Enables adding/removing of users.
 */
public class MainServlet extends RetroStoreServlet {
  private static final Logger LOG = Logger.getLogger("MainServlet");

  private static com.google.appengine.api.users.UserService sUserService =
      UserServiceFactory.getUserService();
  private static UserManagement sUserManagement = new UserManagement(sUserService);
  private static AppManagement sAppManagement = new AppManagement();
  private static UserService sAccountTypeProvider =
      new UserServiceImpl(sUserManagement, sUserService);
  private static DefaultResourceLoader sDefaultResourceLoader = new DefaultResourceLoader();

  private static List<Request> sRequestServers;

  static {
    sRequestServers = new ArrayList<>();
    sRequestServers.add(new LoginRequest());
    sRequestServers.add(new EnsureAdminExistsRequest(sUserManagement));
    sRequestServers.add(new RpcCallRequest(sUserManagement, sAppManagement));
    sRequestServers.add(new PolymerRequest(getResourceLoader()));
    // Note: Add more request servers here. Keep in mind that this is in priority-order.
  }

  private static ResourceLoader getResourceLoader() {
    String polymerDebugServer = System.getProperty("retrostore.debug.polymer");
    if (Strings.isNullOrEmpty(polymerDebugServer)) {
      return sDefaultResourceLoader;
    } else {
      LOG.info(
          String.format("Initializing Polymer debug loader with URL: '%s'", polymerDebugServer));
      return new PolymerDebugLoader(polymerDebugServer, sDefaultResourceLoader);
    }
  }

  @Override
  protected void doGet(HttpServletRequest req, HttpServletResponse resp)
      throws ServletException, IOException {
    serveMainHtml(req, resp);
  }

  @Override
  protected void doPost(HttpServletRequest req, HttpServletResponse resp)
      throws ServletException, IOException {
    serveMainHtml(req, resp);
  }

  private void serveMainHtml(HttpServletRequest req, HttpServletResponse resp)
      throws ServletException, IOException {
    Responder responder = new Responder(resp);
    for (Request server : sRequestServers) {
      if (server.serveUrl(new RequestDataImpl(req), responder, sAccountTypeProvider)) {
        return;
      }
    }
    resp.sendError(HttpServletResponse.SC_NOT_FOUND);
  }
}
