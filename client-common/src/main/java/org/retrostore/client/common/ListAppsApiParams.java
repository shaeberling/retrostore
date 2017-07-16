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

/**
 * Parameters used for the ListApps API call.
 */
public class ListAppsApiParams {
  /** Start index of the first item to return. */
  public final int start;

  /** The maximum number of items to return/ */
  public final int num;

  /** Needed for GSON instantiation. */
  public ListAppsApiParams() {
    this.start = 0;
    this.num = 0;
  }

  public ListAppsApiParams(int start, int num) {
    this.start = start;
    this.num = num;
  }
}
