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

import com.google.appengine.api.blobstore.BlobInfo;
import com.google.appengine.api.blobstore.BlobstoreService;
import com.google.common.base.Charsets;
import com.google.common.base.Optional;
import com.google.common.collect.ImmutableMap;
import com.google.common.io.ByteStreams;
import com.google.common.io.CharStreams;
import org.apache.commons.fileupload.FileItemIterator;
import org.apache.commons.fileupload.FileItemStream;
import org.apache.commons.fileupload.FileUploadException;
import org.apache.commons.fileupload.servlet.ServletFileUpload;
import org.retrostore.util.NumUtil;

import javax.servlet.http.HttpServletRequest;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.logging.Level;
import java.util.logging.Logger;

import static com.google.common.base.Preconditions.checkNotNull;

/**
 * Default RequestData implementation based on an HttpServletRequest.
 */
public class RequestDataImpl implements RequestData {
  private static final Logger LOG = Logger.getLogger("RequestDataImpl");
  private final HttpServletRequest mRequest;
  private final Type mType;
  private final BlobProvider mBlobInfos;

  public static RequestData create(final HttpServletRequest request,
                                   Type type,
                                   final BlobstoreService blobstoreService) {
    BlobProvider blobProvider = new BlobProvider() {
      @Override
      public Map<String, List<BlobInfo>> getBlobs() {
        Map<String, List<BlobInfo>> blobInfos = blobstoreService.getBlobInfos(request);
        blobInfos = blobInfos != null ? blobInfos : new HashMap<String, List<BlobInfo>>();
        return ImmutableMap.copyOf(blobInfos);
      }
    };
    return new RequestDataImpl(request, type, blobProvider);

  }

  private RequestDataImpl(HttpServletRequest request, Type type, BlobProvider blobInfos) {
    mRequest = checkNotNull(request);
    mType = checkNotNull(type);
    mBlobInfos = blobInfos;
  }

  @Override
  public Type getType() {
    return mType;
  }

  @Override
  public String getUrl() {
    return mRequest.getRequestURI();
  }

  @Override
  public Optional<Integer> getInt(String name) {
    String value = getParameter(name);
    if (value == null) {
      return Optional.absent();
    }
    return NumUtil.parseInteger(value);
  }

  @Override
  public Optional<Long> getLong(String name) {
    String value = getParameter(name);
    if (value == null) {
      return Optional.absent();
    }
    return NumUtil.parseLong(value);
  }

  @Override
  public Optional<String> getString(String name) {
    return Optional.fromNullable(getParameter(name));
  }

  @Override
  public String getBody() {
    try {
      return CharStreams.toString(
          new InputStreamReader(mRequest.getInputStream(), Charsets.UTF_8));
    } catch (IOException ex) {
      LOG.warning(String.format("Could not read request body: '%s'.", ex.getMessage()));
      return "";
    }
  }

  @Override
  public byte[] getRawBody() {
    try {
      return ByteStreams.toByteArray(mRequest.getInputStream());
    } catch (IOException ex) {
      LOG.warning(String.format("Could not read request body: '%s'.", ex.getMessage()));
      return new byte[0];
    }
  }

  @Override
  public List<UploadFile> getFiles() {
    if (!ServletFileUpload.isMultipartContent(mRequest)) {
      return new ArrayList<>();
    }

    ServletFileUpload upload = new ServletFileUpload();
    try {
      List<UploadFile> files = new ArrayList<>();
      FileItemIterator itemIterator = upload.getItemIterator(mRequest);
      while (itemIterator.hasNext()) {
        FileItemStream file = itemIterator.next();
        ByteArrayOutputStream bytesOut = new ByteArrayOutputStream();
        ByteStreams.copy(file.openStream(), bytesOut);
        files.add(new UploadFile(file.getName(), bytesOut.toByteArray()));
      }
      return files;
    } catch (FileUploadException | IOException e) {
      LOG.log(Level.WARNING, "Cannot parse request for filename.", e);
      return new ArrayList<>();
    }
  }

  @Override
  public Map<String, List<String>> getBlobKeys() {
    Map<String, List<String>> blobKeys = new HashMap<>();
    for (String name : mBlobInfos.getBlobs().keySet()) {
      List<String> keys = new ArrayList<>();
      for (BlobInfo info : mBlobInfos.getBlobs().get(name)) {
        keys.add(info.getBlobKey().getKeyString());
      }
      blobKeys.put(name, keys);
    }
    return ImmutableMap.copyOf(blobKeys);
  }

  private String getParameter(String name) {
    return mRequest.getParameter(name);
  }

  interface BlobProvider {
    Map<String, List<BlobInfo>> getBlobs();
  }

}
