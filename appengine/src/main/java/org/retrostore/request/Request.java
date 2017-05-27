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

package org.retrostore.request;

import org.retrostore.data.user.UserService;

/**
 * Interface for serving requests of any kind.
 */
public interface Request {
  /**
   * Attempts to serve the given requestData.
   *
   * @param requestData the requestData to serve
   * @param responder   used to serve the requestData
   * @param userService informs the server about the account type of the currently logged-in user.
   * @return Whether the requestData has been served. If true, no other attempt should be made to
   * serve this requestData, and serving is to be considered complete.
   */
  boolean serveUrl(RequestData requestData, Responder responder, UserService userService);
}
