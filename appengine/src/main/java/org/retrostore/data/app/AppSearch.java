/*
 *  Copyright 2018, Sascha Häberling
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

package org.retrostore.data.app;

import java.util.List;

/**
 * Classes implementing this interface offer a way to search through apps.
 */
public interface AppSearch {

  /**
   * Update the index with the given items.
   */
  void refreshIndex(List<AppStoreItem> items);

  /**
   * Adds or updates an item in the search index.
   */
  void addOrUpdate(AppStoreItem item);

  /**
   * Removes an item from the search index.
   */
  void remove(String appId);

  /**
   * Perform a search.
   *
   * @param query the search query.
   * @return A list of appIds that match the query.
   */
  List<String> search(String query);

}
