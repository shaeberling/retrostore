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

import org.retrostore.client.common.proto.App;
import org.retrostore.client.common.proto.MediaImage;

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
        RetrostoreClientImpl.get("n/a", "https://www.retrostore.org/api/%s", false);
    List<App> items = retrostore.fetchApps(0, 5);
    System.out.println(String.format("Got %d items.", items.size()));

    String anAppId = null;
    for (App item : items) {
      anAppId = item.getId();
      System.out.println(item.getName());
      List<MediaImage> mediaImages = retrostore.fetchMediaImages(item.getId());
      for (MediaImage mediaImage : mediaImages) {
        System.out.println(" -Media Image: " + mediaImage.getFilename());
        System.out.println(" -Media Type : " + mediaImage.getType().name());
        System.out.println(" -Media Size : " + mediaImage.getData().size());
      }
    }

    if (anAppId != null) {
      App app = retrostore.getApp(anAppId);
      if (app != null) {
        System.out.println("Yep, got the single app: " + app.getName());
      } else {
        System.out.println("Nope, could not get app");
      }
    }
  }
}
