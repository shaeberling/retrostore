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

package org.retrostore;

import com.google.common.base.Preconditions;
import com.google.common.base.Strings;
import org.retrostore.client.common.FetchMediaImagesApiParams;
import org.retrostore.client.common.GetAppApiParams;
import org.retrostore.client.common.ListAppsApiParams;
import org.retrostore.client.common.proto.ApiResponseApps;
import org.retrostore.client.common.proto.ApiResponseMediaImages;
import org.retrostore.client.common.proto.App;
import org.retrostore.client.common.proto.MediaImage;
import org.retrostore.client.common.proto.MediaType;
import org.retrostore.net.UrlFetcher;
import org.retrostore.net.UrlFetcherImpl;

import java.io.IOException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

public class RetrostoreClientImpl implements RetrostoreClient {
  private static final String DEFAULT_SERVER_URL = "https://retrostore.org/api/%s";
  private static final boolean DEFAULT_GZIP_ENABLED = false;

  private final String mApiKey;
  private final String mServerUrl;
  private final boolean mEnableGzip;
  private final UrlFetcher mUrlFetcher;
  private final Executor mExecutor;

  RetrostoreClientImpl(String apiKey,
                       String serverUrl,
                       boolean enableGzip,
                       UrlFetcher urlFetcher,
                       Executor executor) {
    mApiKey = apiKey;
    mServerUrl = serverUrl;
    mEnableGzip = enableGzip;
    mUrlFetcher = urlFetcher;
    mExecutor = executor;
  }

  public static RetrostoreClientImpl getDefault(String apiKey) {
    return new RetrostoreClientImpl(apiKey, DEFAULT_SERVER_URL, DEFAULT_GZIP_ENABLED, new
        UrlFetcherImpl(), Executors.newSingleThreadExecutor());
  }

  @SuppressWarnings("WeakerAccess") // This is the public API.
  public static RetrostoreClientImpl get(String apiKey, String serverUrl, boolean enableGzip) {
    // Use default URL fetcher and executor.
    return new RetrostoreClientImpl(apiKey, serverUrl, enableGzip, new UrlFetcherImpl(),
        Executors.newSingleThreadExecutor());
  }

  @Override
  public App getApp(String appId) throws ApiException {
    Preconditions.checkArgument(!Strings.isNullOrEmpty(appId), "appId missing.");
    GetAppApiParams params = new GetAppApiParams(appId);
    String url = String.format(mServerUrl, "getApp");
    try {
      byte[] content = mUrlFetcher.fetchUrl(url, params);
      ApiResponseApps apiResponse = ApiResponseApps.parseFrom(content);

      if (!apiResponse.getSuccess()) {
        throw new ApiException(String.format(
            "Server reported error: '%s'", apiResponse.getMessage()));
      }
      if (apiResponse.getAppList().size() > 0) {
        return apiResponse.getAppList().get(0);
      } else {
        return null;
      }
    } catch (IOException e) {
      throw new ApiException("Unable to make request to server.", e);
    }
  }

  @Override
  public List<App> fetchApps(int start, int num) throws ApiException {
    return fetchApps(new ListAppsApiParams(start, num));
  }

  @Override
  public List<App> fetchApps(int start, int num, String searchQuery, Set<MediaType> hasMediaTypes)
      throws ApiException {
    if (hasMediaTypes == null) {
      hasMediaTypes = new HashSet<>();
    }
    List<String> mediaTypes = new ArrayList<>(hasMediaTypes.size());
    for (MediaType mediaType : hasMediaTypes) {
      mediaTypes.add(mediaType.name());
    }
    return fetchApps(new ListAppsApiParams(start, num, searchQuery, mediaTypes));
  }

  private List<App> fetchApps(ListAppsApiParams params) throws ApiException {
    String url = String.format(mServerUrl, "listApps");
    try {
      byte[] content = mUrlFetcher.fetchUrl(url, params);
      ApiResponseApps apiResponse = ApiResponseApps.parseFrom(content);

      if (!apiResponse.getSuccess()) {
        throw new ApiException(String.format(
            "Server reported error: '%s'", apiResponse.getMessage()));
      }
      return apiResponse.getAppList();
    } catch (IOException e) {
      throw new ApiException("Unable to make request to server.", e);
    }
  }

  @Override
  public List<MediaImage> fetchMediaImages(String appId) throws ApiException {
    FetchMediaImagesApiParams params = new FetchMediaImagesApiParams(appId);
    String url = String.format(mServerUrl, "fetchMediaImages");
    try {
      byte[] content = mUrlFetcher.fetchUrl(url, params);
      ApiResponseMediaImages apiResponse = ApiResponseMediaImages.parseFrom(content);

      if (!apiResponse.getSuccess()) {
        throw new ApiException(String.format(
            "Server reported error: '%s'", apiResponse.getMessage()));
      }
      return apiResponse.getMediaImageList();
    } catch (IOException e) {
      throw new ApiException("Unable to make request to server.", e);
    }
  }
}
