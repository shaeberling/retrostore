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
import org.retrostore.data.ItemsViewUtil;
import org.retrostore.data.user.UserManagement;
import org.retrostore.data.user.UserService;
import org.retrostore.data.user.UserServiceImpl;
import org.retrostore.data.user.UserViewUtil;
import org.retrostore.request.EnsureAdminExistsRequest;
import org.retrostore.request.LoginRequest;
import org.retrostore.request.PolymerRequest;
import org.retrostore.request.Request;
import org.retrostore.request.RequestDataImpl;
import org.retrostore.request.Responder;
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

  private static final String REQUEST_REMOVE_USER = "removeUser";
  private static final String REQUEST_ADD_EDIT_USER = "addEditUser";
  private static final String REQUEST_CREATE_ACCOUNT = "createAccount";

  private static GfxServingUtil sGfxServingUtil = new GfxServingUtil();
  private static com.google.appengine.api.users.UserService sUserService =
      UserServiceFactory.getUserService();
  private static UserManagement sUserManagement = new UserManagement(sUserService);
  private static UserService sAccountTypeProvider =
      new UserServiceImpl(sUserManagement, sUserService);
  private static UserViewUtil sUserViewUtil = new UserViewUtil(sUserManagement);
  private static ItemsViewUtil sItemsViewUtil = new ItemsViewUtil();
  private static FileUtil sFileUtil = new FileUtil();

  private static List<Request> sRequestServers;

  static {
    sRequestServers = new ArrayList<>();
    sRequestServers.add(new LoginRequest());
    sRequestServers.add(new EnsureAdminExistsRequest(sUserManagement));
    sRequestServers.add(new RpcCallRequest(sUserManagement));
    sRequestServers.add(new PolymerRequest(sFileUtil));
    // Note: Add more request servers here. Keep in mind that this is in priority-order.
  }

  @Override
  protected void doGet(HttpServletRequest req, HttpServletResponse resp)
      throws ServletException, IOException {
    serveMainHtml(req, resp);
  }

  @Override
  protected void doPost(HttpServletRequest req, HttpServletResponse resp)
      throws ServletException, IOException {
    String requestParam = req.getParameter("request");

    // The following actions are only allowed for admin users.
    if (sUserManagement.isCurrentUserAdmin()) {
      if (REQUEST_ADD_EDIT_USER.equals(requestParam)) {
        sUserViewUtil.handleAddEditRequest(req, resp);
      } else if (REQUEST_REMOVE_USER.equals(requestParam)) {
        sUserViewUtil.handleRemoveRequest(req, resp);
      }
    }

    // Users create their own account, so no need for admin rights. Only the logged in user's
    // e-mail will be used.
    if (REQUEST_CREATE_ACCOUNT.equals(requestParam)) {
      sUserViewUtil.handleAccountCreateRequest(req, resp);
    }

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


//    LOG.info("Logout URL: " + sUserService.createLogoutURL(thisUrl));
//    Optional<String> loggedInEmail = sUserManagement.getLoggedInEmail();
//    Optional<RetroStoreUser> currentUser = sUserManagement.getCurrentUser();
//
//    // User needs to create an account first.
//    if (!currentUser.isPresent()) {
//      String content = Template.fromFile("WEB-INF/html/create_account.html")
//          .with("logged_in_email", loggedInEmail.get())
//          .render();
//      resp.getWriter().write(content);
//      return;
//    }
//
//    if ("/".equals(req.getRequestURI())) {
//      Template newItemTpl = sItemsViewUtil.fillNewItemView();
//      Template userManagementTpl = sUserManagement.isCurrentUserAdmin() ?
//          sUserViewUtil.fillUserManagementView(sUserManagement) : Template.empty();
//      String content = Template.fromFile("WEB-INF/html/index.html")
//          .withHtml("new_item_content", newItemTpl.render())
//          .withHtml("user_management_content", userManagementTpl.render())
//          .withHtml("logged_in_user", currentUser.get().firstName)
//          .render();
//      resp.getWriter().write(content);
//      return;
//    }
//
//    if (sGfxServingUtil.serve(req, resp)) {
//      return;
//    }
//
//    resp.setStatus(HttpServletResponse.SC_NOT_FOUND);
  }
}
