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

package org.retrostore.data;

import org.retrostore.request.Responder.ContentType;

/**
 * Wrapper around Blobstore that can easily be faked.
 */
public interface BlobstoreWrapper {
  /** Creates a URL that can be uploaded to via POST. */
  String createUploadUrl(String forwardUrl);

  /** Loads a blob's raw data. */
  byte[] loadBlob(String key);

  /** Deletes a blob if it exists. */
  void deleteBlob(String key);

  /**
   * Adds a screenshot to the blobstore for the app with the given ID.
   *
   * @param appId       the ID of the app to add the screenshot for
   * @param data        the raw data of the screenshot file
   * @param contentType the type of the image data
   * @param cookie      the complete cookie from the original request. This is necessary so that our
   *                    internal add request can use the same authentication as the original
   *                    requester. Not setting this will make the call fail.
   */
  void addScreenshot(String appId, byte[] data, ContentType contentType, String cookie);
}
