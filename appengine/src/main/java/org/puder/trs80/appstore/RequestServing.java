/*
 * Copyright 2017, Sascha Häberling
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

package org.puder.trs80.appstore;

import org.puder.trs80.appstore.data.user.UserService;

/**
 * Interface for serving requests of any kind.
 */
public interface RequestServing {
  /**
   * Attempts to serve the given request.
   *
   * @param request     the request to serve
   * @param responder   used to serve the request
   * @param userService informs the server about the account type of the currently logged-in user.
   * @return Whether the request has been served. If true, no other attempt should be made to serve this request, and
   * serving is to be considered complete.
   */
  boolean serveUrl(Request request, Responder responder, UserService userService);
}
