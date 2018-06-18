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

import java.util.ArrayList;
import java.util.List;

/**
 * Parameters used for the ListApps API call.
 * <p>
 * IMPORTANT: The names of the members in this class make up the API. They need to be matched
 * 100% in the JSON sent to the server. So change this with care. You might create
 * incompatibilities with older clients.
 */
public class ListAppsApiParams {
  /** Start index of the first item to return. */
  public final int start;

  /** The maximum number of items to return/ */
  public final int num;

  /** Search query looking through title, description etc. */
  public final String query;

  /** Query filters for TRS80 items. */
  public final Trs80Params trs80 = new Trs80Params();

  /** Needed for GSON instantiation. */
  public ListAppsApiParams() {
    this.start = 0;
    this.num = 0;
    this.query = "";
  }

  public ListAppsApiParams(int start, int num) {
    this.start = start;
    this.num = num;
    this.query = "";
  }

  public ListAppsApiParams(int start, int num, String query, List<String> trs80MediaTypes) {
    this.start = start;
    this.num = num;
    this.query = query;
    if (trs80MediaTypes != null) {
      this.trs80.mediaTypes.addAll(trs80MediaTypes);
    }
  }

  /** Query options for TRS80 items. */
  public static class Trs80Params {
    /** Results must have the given media types. */
    public final List<String> mediaTypes = new ArrayList<>();
  }
}
