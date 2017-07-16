/*
 * Copyright 2017, Sascha Häberling
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *        http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.retrostore.client.common;

import com.google.common.collect.ImmutableList;

import java.util.List;

/**
 * A response wrapper for items returned by an API call.
 */
public class ApiResponse<T> {
  /** Whether the request was a success. */
  public final boolean success;
  /** Optionally and error message if success is false. */
  public final String errorMessage;
  /** Items returned by this response. */
  public final List<T> items;

  public ApiResponse(boolean success, String errorMessage, List<T> items) {
    this.success = success;
    this.errorMessage = errorMessage;
    this.items = ImmutableList.copyOf(items);
  }

  public ApiResponse(String errorMessage) {
    this.success = false;
    this.errorMessage = errorMessage;
    this.items = ImmutableList.of();

  }
}
