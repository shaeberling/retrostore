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

package org.retrostore.rpc.api;

import com.google.common.base.Optional;
import org.retrostore.client.common.proto.App;
import org.retrostore.client.common.proto.Trs80Extension;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.data.app.Author;
import org.retrostore.resources.ImageServiceWrapper;

class ApiHelper {
  private final AppManagement mAppManagement;
  private final ImageServiceWrapper mImageService;

  ApiHelper(AppManagement appManagement, ImageServiceWrapper imageService) {
    mAppManagement = appManagement;
    mImageService = imageService;
  }

  App.Builder convert(AppStoreItem app) {
    App.Builder appBuilder = App.newBuilder();
    appBuilder.setId(app.id);
    appBuilder.setName(app.listing.name);
    appBuilder.setVersion(app.listing.versionString);
    appBuilder.setDescription(app.listing.description);
    appBuilder.setReleaseYear(app.listing.releaseYear);
    Optional<Author> author = mAppManagement.getAuthorById(app.listing.authorId);
    if (author.isPresent()) {
      appBuilder.setAuthor(author.get().name);
    }

    // Set the TRS80 related parameters.
    Trs80Extension.Builder trsExtension = Trs80Extension.newBuilder();
    switch (app.trs80Extension.model) {
      default:
      case MODEL_I:
        trsExtension.setModel(Trs80Extension.Trs80Model.MODEL_I);
        break;
      case MODEL_III:
        trsExtension.setModel(Trs80Extension.Trs80Model.MODEL_III);
        break;
      case MODEL_4:
        trsExtension.setModel(Trs80Extension.Trs80Model.MODEL_4);
        break;
      case MODEL_4P:
        trsExtension.setModel(Trs80Extension.Trs80Model.MODEL_4P);
        break;
    }

    for (String blobKey : app.screenshotsBlobKeys) {
      appBuilder.addScreenshotUrl(mImageService.getServingUrl(blobKey).or(""));
    }
    appBuilder.setExtTrs80(trsExtension);
    return appBuilder;
  }
}
