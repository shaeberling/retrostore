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

import org.retrostore.data.user.UserService;

/**
 * We use ping requests to check that the AppEngine instance is alive. This is the class that
 * handles these requests.
 */
public class PingRequest implements Request {
  private static final String PATH_SERVE = "/ping";

  @Override
  public boolean serveUrl(RequestData requestData, Responder responder, UserService userService) {
    if (!PATH_SERVE.equals(requestData.getUrl())) {
      return false;
    }
    responder.respond("OK", Responder.ContentType.PLAIN);
    return true;
  }
}
