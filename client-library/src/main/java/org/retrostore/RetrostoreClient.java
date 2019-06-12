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
import org.retrostore.client.common.proto.MediaImage;
import org.retrostore.client.common.proto.MediaType;

import java.util.List;
import java.util.Set;

/**
 * Common Retrostore client interface.
 */
public interface RetrostoreClient {
  /**
   * Fetches data about the RetroStore app item with the given ID.
   *
   * @param appId the ID of the app
   * @return the app data for the app if it exists, otherwise null.
   * @throws ApiException
   */
  App getApp(String appId) throws ApiException;

  /**
   * Fetches a number of RetroStore app items. Blocks until results are received.
   *
   * @param start the index at which to start.
   * @param num   the number of app items to fetch (max).
   * @return A list of the items requested or an error, if something
   * went wrong.
   */
  List<App> fetchApps(int start, int num) throws ApiException;

  /**
   * Like {@link #fetchApps(int, int)} but adds options.
   */
  List<App> fetchApps(int start, int num, String searchQuery, Set<MediaType> hasMediaTypes)
      throws ApiException;

  /**
   * Fetches the media images for the app with the given ID.
   *
   * @param appId the ID of the app for which to fetch the media images.
   * @return A list of all the media images fetched for this app.
   */
  List<MediaImage> fetchMediaImages(String appId) throws ApiException;
}
