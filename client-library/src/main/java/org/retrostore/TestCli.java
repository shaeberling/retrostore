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

package org.retrostore;

import org.retrostore.client.common.RetrostoreAppItem;

import java.io.IOException;
import java.util.List;

/**
 * A CLI to test the retrostore API.
 */
public class TestCli {
  // https://test-dot-trs-80.appspot.com

  public static void main(String[] args) throws ApiException, IOException {
    System.out.println("Testing the RetrostoreClient.");

    RetrostoreClientImpl retrostore =
        RetrostoreClientImpl.get("n/a", "http://localhost:8888/api/%s", false);
    List<RetrostoreAppItem> items = retrostore.fetchApps(0, 1);
    System.out.println(String.format("Got %d items.", items.size()));

    for (RetrostoreAppItem item : items) {
      System.out.println(item.name);
      System.out.println("Num media images: " + item.mediaImages.size());
      for (RetrostoreAppItem.MediaImage image : item.mediaImages) {
        System.out.println("Media image name: " + image.filename);
        System.out.println("Media image size: " + image.data.length);
      }
    }
  }
}
