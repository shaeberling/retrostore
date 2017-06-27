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

import org.retrostore.data.user.UserAccountType;
import org.retrostore.request.Responder;

/**
 * Interface for all RPC calls.
 */
public interface RpcCall {
  /**
   * The name of the RPC method.
   */
  String getName();

  /**
   * Whether the current user is permitted to make this call.
   */
  boolean isPermitted(UserAccountType type);

  /**
   * Performs the RPC call.
   */
  void call(RpcParameters params, Responder responder);
}
