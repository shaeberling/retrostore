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

package org.retrostore.request;

/**
 * Resolves content types.
 */
final class ContentType {
  /** Return a content type depending on the filename. */
  static Responder.ContentType fromFilename(String filename) {
    if (filename.endsWith(".html")) {
      return Responder.ContentType.HTML;
    } else if (filename.endsWith(".css")) {
      return Responder.ContentType.CSS;
    } else if (filename.endsWith(".js")) {
      return Responder.ContentType.JS;
    } else if (filename.endsWith(".json")) {
      return Responder.ContentType.JSON;
    } else if (filename.endsWith(".jpeg")) {
      return Responder.ContentType.JPEG;
    } else if (filename.endsWith(".png")) {
      return Responder.ContentType.PNG;
    } else {
      return Responder.ContentType.PLAIN;
    }
  }
}
