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

package org.retrostore.request;

import com.google.common.base.Optional;

/**
 * Interface for the request data.
 */
public interface RequestData {
  /** The URL of the request. */
  String getUrl();

  /** Returns an parameter value as an int, if it exists. */
  Optional<Integer> getInt(String name);

  /** Returns an parameter value as an long, if it exists. */
  Optional<Long> getLong(String name);

  /** Returns a parameter value as a string, if it exists. */
  Optional<String> getString(String name);

  /** If one was sent, this will contains the body content. */
  String getBody();

  /** Get the body of the request as bytes. */
  byte[] getRawBody();

  /** For POST upload requests, this return the name of the uploaded file. */
  Optional<String> getFilename();
}
