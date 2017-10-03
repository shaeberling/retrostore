/*
 *  Copyright 2017, Sascha Häberling
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

package org.retrostore.resources;

import com.google.common.base.Optional;

/**
 * Functionality around the image service.
 */
public interface ImageServiceWrapper {
  int DEFAULT_SCREENSHOT_SIZE = 800;

  /**
   * Returns a URL that serves the image with the given blob key.
   *
   * @param blobKey   the blob key of the image to serve.
   * @param imageSize the maximum size of the longest side.
   * @return The URL to serve the image in the given size.
   */
  Optional<String> getServingUrl(String blobKey, int imageSize);

  /**
   * Like {@link #getServingUrl(String, int)} but with a default size.
   */
  Optional<String> getServingUrl(String blobKey);
}
