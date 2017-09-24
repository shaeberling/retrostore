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

package org.retrostore.data;

import com.google.appengine.api.blobstore.BlobKey;
import com.google.appengine.api.blobstore.BlobstoreService;
import com.google.common.base.Preconditions;
import com.google.common.base.Strings;
import org.apache.http.HttpEntity;
import org.apache.http.HttpResponse;
import org.apache.http.client.HttpClient;
import org.apache.http.client.methods.HttpPost;
import org.apache.http.entity.ContentType;
import org.apache.http.entity.mime.HttpMultipartMode;
import org.apache.http.entity.mime.MultipartEntityBuilder;
import org.apache.http.entity.mime.content.ByteArrayBody;
import org.apache.http.entity.mime.content.FileBody;
import org.apache.http.impl.client.HttpClientBuilder;
import org.retrostore.request.Responder;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.logging.Level;
import java.util.logging.Logger;

import static com.google.common.base.Preconditions.checkNotNull;

/**
 * Default implementation for the BlobStore wrapper.
 */
public class BlobstoreWrapperImpl implements BlobstoreWrapper {
  private static final Logger LOG = Logger.getLogger("Blobstore");

  private final BlobstoreService mBlobstoreService;

  public BlobstoreWrapperImpl(BlobstoreService blobstoreService) {
    mBlobstoreService = checkNotNull(blobstoreService);
  }

  @Override
  public String createUploadUrl(String forwardUrl) {
    return mBlobstoreService.createUploadUrl(forwardUrl);
  }

  @Override
  public byte[] loadBlob(String key) {
    return mBlobstoreService.fetchData(
        new BlobKey(key), 0, BlobstoreService.MAX_BLOB_FETCH_SIZE - 1);
  }

  @Override
  public void deleteBlob(String key) {
    mBlobstoreService.delete(new BlobKey(key));
  }

  @Override
  public void addScreenshot(String appId, byte[] data, Responder.ContentType contentType,
                            String cookie) {
    Preconditions.checkArgument(!Strings.isNullOrEmpty(appId), "'appId' missing");
    Preconditions.checkArgument(data != null && data.length > 0, "'data' is empty");
    Preconditions.checkNotNull(contentType, "'contentType' missing");
    Preconditions.checkArgument(!Strings.isNullOrEmpty(cookie), "'cookie' missing");

    LOG.info(String.format("About to add a screenshot blob of size %d with type %s.",
        data.length, contentType.str));

    final String PATH_UPLOAD = "/screenshotUpload";
    String forwardTo = PATH_UPLOAD + "?appId=" + appId;

    LOG.info("Forward to: " + forwardTo);
    String uploadUrl = createUploadUrl(forwardTo);
    LOG.info("UploadUrl: " + uploadUrl);

    // It is important that we set the cookie so that we're authenticated. We do not allow
    // anonymous requests to upload screenshots.
    HttpPost post = new HttpPost(uploadUrl);
    post.setHeader("Cookie", cookie);

    MultipartEntityBuilder builder = MultipartEntityBuilder.create();
    builder.setMode(HttpMultipartMode.BROWSER_COMPATIBLE);
    // Note we need to use the deprecated constructor so we can use our content type.
    builder.addPart("file", new ByteArrayBody(data, contentType.str, "screenshot"));

    HttpEntity entity = builder.build();
    post.setEntity(entity);

    HttpClient client = HttpClientBuilder.create().build();
    try {
      LOG.info("POST constructed. About to make request!");
      HttpResponse response = client.execute(post);
      LOG.info("Request succeeded!");
      ByteArrayOutputStream out = new ByteArrayOutputStream();
      response.getEntity().writeTo(out);
      LOG.info(new String(out.toByteArray(), "UTF-8"));

    } catch (IOException e) {
      LOG.log(Level.SEVERE, "Cannot make POST request.", e);
    }
  }
}
