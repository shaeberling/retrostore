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

package org.retrostore;

import org.retrostore.client.common.proto.App;

import java.util.List;
import java.util.concurrent.Future;

/**
 * Common Retrostore client interface.
 */
public interface RetrostoreClient {
  /**
   * Fetches a number of Retrostore app items. Blocks until results are received.
   *
   * @param start the index at which to start.
   * @param num   the number of app items to fetch (max).
   * @return A future which will provide a list of the items requested or an error, if something
   * went wrong.
   */
  List<App> fetchApps(int start, int num) throws ApiException;

  /**
   * Fetches a number of Retrostore app items. Returns immediately.
   *
   * @param start the index at which to start.
   * @param num   the number of app items to fetch (max).
   * @return A future which will provide a list of the items requested or an error, if something
   * went wrong.
   */
  Future<List<App>> fetchAppsAsync(int start, int num);
}
