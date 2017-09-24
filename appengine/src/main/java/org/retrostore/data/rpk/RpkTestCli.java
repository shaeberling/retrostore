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

import com.google.gson.Gson;

import java.io.File;
import java.io.FileNotFoundException;
import java.io.FileReader;

/**
 * A CLI to test reading RPKs and TPKS.
 */
public class RpkTestCli {
  public static void main(String[] args) throws FileNotFoundException {
    if (args.length < 1) {
      throw new RuntimeException("Argument missing.");
    }

    File rpkFile = new File(args[0]);
    if (!rpkFile.exists() || !rpkFile.isFile()) {
      throw new RuntimeException("Not a file.");
    }
    if (!rpkFile.canRead()) {
      throw new RuntimeException("File is not readable.");
    }

    FileReader reader = new FileReader(rpkFile);
    RpkData rpkData = new Gson().fromJson(reader, RpkData.class);

    System.out.println("Go an RPK data item, yay.");

    System.out.println("---------- App ----------");
    System.out.println("ID: " + rpkData.app.id);
    System.out.println("Version: " + rpkData.app.version);
    System.out.println("Name: " + rpkData.app.name);
    System.out.println("Descr: " + rpkData.app.description);
    System.out.println("Author: " + rpkData.app.author);
    System.out.println("Published: " + rpkData.app.year_published);
    System.out.println("Author: " + rpkData.app.categories);
    System.out.println("Screenshot Num: " + rpkData.app.screenshot.length);
    for (RpkData.MediaImage screenshot : rpkData.app.screenshot) {
      System.out.println("  - Ext    : " + screenshot.ext);
      System.out.println("  - Content: " + screenshot.content);
    }
    System.out.println("Platform: " + rpkData.app.platform);
    System.out.println("---------- Submitter ----------");
    System.out.println("Name : " + rpkData.submitter.name);
    System.out.println("EMail: " + rpkData.submitter.email);
    System.out.println("---------- TRS Ext ----------");
    System.out.println("Model: " + rpkData.trs.model);
    System.out.println("Disk Num: " + rpkData.trs.image.disk.length);
    for (RpkData.MediaImage disk : rpkData.trs.image.disk) {
      System.out.println("  - Ext    : " + disk.ext);
      System.out.println("  - Content: " + disk.content);
    }
    System.out.println("Cmd: ");
    System.out.println("  - Ext    : " + rpkData.trs.image.cmd.ext);
    System.out.println("  - Content: " + rpkData.trs.image.cmd.content);
  }
}
