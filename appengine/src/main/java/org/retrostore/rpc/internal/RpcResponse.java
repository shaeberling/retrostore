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

package org.retrostore.rpc.internal;

import org.retrostore.request.Responder;

/**
 * Generic response sent back to the client for RPC requests;
 */
public class RpcResponse {
  /** Whether the request was a success. */
  public boolean success = false;

  /** A success or failure message, human-readable. */
  public String message = "";

  /** Optional response data. */
  public Object data = null;

  public static void respond(boolean success, String message, Responder responder) {
    RpcResponse response = new RpcResponse();
    response.success = success;
    response.message = message;
    responder.respondJson(response);
  }
}
