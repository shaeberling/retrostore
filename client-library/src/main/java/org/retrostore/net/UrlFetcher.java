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

package org.retrostore.net;

import java.io.IOException;

/**
 * Common interface for fetching URLs.
 */
public interface UrlFetcher {
  /**
   * Fetched the given URL.
   *
   * @param url  the URL to fetch.
   * @param body the body data to be sent.
   * @return The contents of the URL as a byte array.
   * @throws IOException Thrown of the URL could not be fetched. Contains information about what
   *                     happened.
   */
  byte[] fetchUrl(String url, byte[] body) throws IOException;

  byte[] fetchUrl(String url, Object obj) throws IOException;
}
