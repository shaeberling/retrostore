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

import static com.google.common.base.Preconditions.checkNotNull;

/**
 * Default implementation for the BlobStore wrapper.
 */
public class BlobstoreWrapperImpl implements BlobstoreWrapper {
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
    byte[] bytes = mBlobstoreService.fetchData(
        new BlobKey(key), 0, BlobstoreService.MAX_BLOB_FETCH_SIZE - 1);
    return bytes;
  }

  @Override
  public void deleteBlob(String key) {
    mBlobstoreService.delete(new BlobKey(key));
  }
}
