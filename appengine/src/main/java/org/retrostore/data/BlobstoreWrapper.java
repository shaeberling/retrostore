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

  /** Adds a screenshot to the blobstore for the app with the given ID.. */
  void addScreenshot(String appId, byte[] data, ContentType contentType);
}
