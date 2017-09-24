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

import com.google.appengine.api.images.Image;
import com.google.appengine.api.images.ImagesServiceFactory;
import com.google.common.base.Optional;
import org.retrostore.data.BlobstoreWrapper;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.user.UserService;
import org.retrostore.resources.ImageServiceWrapper;

import java.util.List;
import java.util.Map;
import java.util.logging.Level;
import java.util.logging.Logger;

import static com.google.common.base.Preconditions.checkNotNull;

/**
 * Serves screenshots and receives uploaded screenshots to store them.
 */
public class ScreenshotRequest implements Request {
  private static final Logger LOG = Logger.getLogger("ScrnshtReq");
  private static final String PATH_SERVE = "/screenshotServe";
  private static final String PATH_UPLOAD = "/screenshotUpload";
  private static final String PATH_UPLOAD_URL = "/screenshotUrlForUpload";
  private static final String PARAM_KEY = "key";
  private static final int SCREENSHOT_SIZE = 800;
  private final BlobstoreWrapper mBlobStore;
  private final AppManagement mAppManagement;
  private final ImageServiceWrapper mImageService;

  public ScreenshotRequest(BlobstoreWrapper blobStore,
                           AppManagement appManagement,
                           ImageServiceWrapper imageService) {
    mBlobStore = checkNotNull(blobStore);
    mAppManagement = checkNotNull(appManagement);
    mImageService = imageService;
  }

  @Override
  public boolean serveUrl(RequestData requestData, Responder responder, UserService userService) {
    String url = requestData.getUrl();
    if (!url.startsWith(PATH_SERVE) &&
        !url.startsWith(PATH_UPLOAD) &&
        !url.startsWith(PATH_UPLOAD_URL)) {
      return false;
    }

    // Depending on the request URL, we either serve the screenshot or handle an upload and
    // store request.
    if (url.startsWith(PATH_SERVE)) {
      serveScreenshot(requestData, responder);
    } else if (url.startsWith(PATH_UPLOAD)) {
      uploadScreenshot(requestData, responder);
    } else if (url.startsWith(PATH_UPLOAD_URL)) {
      uploadScreenshotUrl(requestData, responder);
    }
    return true;
  }

  private void serveScreenshot(RequestData requestData, Responder responder) {
    Optional<String> blobKeyOpt = requestData.getString(PARAM_KEY);
    if (!blobKeyOpt.isPresent()) {
      LOG.warning("No 'key' present for serving screenshot.");
      return;
    }
    responder.respondRedirect(mImageService.getServingUrl(blobKeyOpt.get(), SCREENSHOT_SIZE));
  }

  private void uploadScreenshotUrl(RequestData requestData, Responder responder) {
    Optional<Long> appIdOpt = requestData.getLong("appId");
    if (!appIdOpt.isPresent()) {
      final String msg = "'appId' missing from uploadScreenshotUrl request.";
      LOG.log(Level.SEVERE, msg);
      responder.respondBadRequest(msg);
      return;
    }
    responder.respondJson(mBlobStore.createUploadUrl(PATH_UPLOAD + "?appId=" + appIdOpt.get()));
  }

  private void uploadScreenshot(RequestData requestData, Responder responder) {
    Optional<String> appIdOpt = requestData.getString("appId");
    if (!appIdOpt.isPresent()) {
      final String msg = "'appId' missing from post-upload URL.";
      LOG.log(Level.SEVERE, msg);
      responder.respondBadRequest(msg);
      return;
    }
    String appId = appIdOpt.get();

    Map<String, List<String>> blobKeys = requestData.getBlobKeys();
    if (blobKeys.isEmpty()) {
      LOG.warning("No blob keys found in screenshot upload request.");
      responder.respondBadRequest("Blob keys missing");
      return;
    }
    for (String filename : blobKeys.keySet()) {
      String key = blobKeys.get(filename).get(0);
      LOG.info(String.format(
          "Found key '%s' for filename '%s' and appId '%s'.", key, filename, appIdOpt.get()));
      if (isValidImage(key)) {
        mAppManagement.addScreenshot(appId, key);
      } else {
        // Delete the blob if it's not a valid image.
        mBlobStore.deleteBlob(key);
      }
    }
  }

  /** Check of the blob with the given key is a valid image. */
  private boolean isValidImage(String key) {
    byte[] imageData = mBlobStore.loadBlob(key);
    LOG.info("Uploaded data size: " + imageData.length);
    if (imageData.length == 0) {
      return false;
    }
    Image image = ImagesServiceFactory.makeImage(imageData);
    try {
      if (image == null || image.getWidth() == 0 || image.getHeight() == 0) {
        LOG.warning("No valid image found for blob key: " + key);
        return false;
      }
    } catch (IllegalArgumentException ex) {
      LOG.warning("Not an image: " + key);
      return false;
    }
    return true;
  }

//  private Optional<String> compressScreenshot(String blobKeyStr) {
//    // FIXME: Hide this behind an interface.
//    byte[] imageData = mBlobStore.loadBlob(blobKeyStr);
//    LOG.info("Image data loaded: " + imageData.length);
//    if (imageData.length == 0) {
//      return Optional.absent();
//    }
//
//    Image image = ImagesServiceFactory.makeImage(imageData);
//    if (image == null || image.getWidth() == 0 || image.getHeight() == 0) {
//      LOG.warning("No image found for blob key: " + blobKeyStr);
//      return Optional.absent();
//    }
//
//    // Set up resize and compression params.
//    int width = image.getWidth();
//    int height = image.getHeight();
//    if (width > height && width > MAX_IMG_SIZE) {
//      height = (int) (height * (MAX_IMG_SIZE / (double) width));
//      width = MAX_IMG_SIZE;
//    } else if (height > width && height > MAX_IMG_SIZE) {
//      width = (int) (width * (MAX_IMG_SIZE / (double) height));
//      height = MAX_IMG_SIZE;
//    }
//    Transform transform = ImagesServiceFactory.makeResize(width, height);
//    OutputSettings settings = new OutputSettings(ImagesService.OutputEncoding.JPEG);
//    settings.setQuality(JPEG_QUALITY);
//    try {
//      // Attempt to resize and compress the image.
//      Image newImage = ImagesServiceFactory.getImagesService().applyTransform(
//          transform, image, settings);
//
//      // Store the new image data in blobstore and return the blob key.
//      return mBlobStore.storeJpegInBlobstore(newImage.getImageData());
//    } catch (IllegalArgumentException | ImagesServiceFailureException ex) {
//      LOG.log(Level.SEVERE, "Unable to compress/resize image.", ex);
//      return Optional.absent();
//    }
//  }
}
