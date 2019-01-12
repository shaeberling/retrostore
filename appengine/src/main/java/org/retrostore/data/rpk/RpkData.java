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

package org.retrostore.data.rpk;

/**
 * An RPK is a RetroStore Package which typically comes in JSON form and makes it easy to ex- and
 * import data from the RetroStore.
 */
public class RpkData {
  public AppData app = new AppData();
  public Publisher publisher = new Publisher();
  public TrsExtension trs = new TrsExtension();

  public static class AppData {
    public String id;
    public String version;
    public String name;
    public String description;
    public String author;
    public String year_published;
    public String categories;
    public String platform;
    public MediaImage[] screenshot = new MediaImage[0];
  }

  public static class Publisher {
    public String first_name;
    public String last_name;
    public String email;
  }

  public static class TrsExtension {
    public String model;
    public Image image = new Image();
  }

  public static class Image {
    public MediaImage[] disk = new MediaImage[0];
    public MediaImage cmd = new MediaImage();
    public MediaImage cas = new MediaImage();
    public MediaImage bas = new MediaImage();
  }

  public static class MediaImage {
    public String ext;
    public String content;
  }
}
