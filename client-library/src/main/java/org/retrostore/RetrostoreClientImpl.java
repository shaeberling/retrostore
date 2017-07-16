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

import com.google.common.util.concurrent.SettableFuture;
import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;
import org.retrostore.client.common.ApiResponse;
import org.retrostore.client.common.ListAppsApiParams;
import org.retrostore.client.common.RetrostoreAppItem;
import org.retrostore.net.UrlFetcher;
import org.retrostore.net.UrlFetcherImpl;

import java.io.IOException;
import java.util.List;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

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

  public static RetrostoreClientImpl get(String apiKey, String serverUrl, boolean enableGzip) {
    // Use default URL fetcher and executor.
    return new RetrostoreClientImpl(apiKey, serverUrl, enableGzip, new UrlFetcherImpl(),
        Executors.newSingleThreadExecutor());
  }

  @Override
  public Future<List<RetrostoreAppItem>> fetchAppsAsync(final int start, final int num) {
    final SettableFuture<List<RetrostoreAppItem>> future = SettableFuture.create();
    mExecutor.execute(new Runnable() {
      @Override
      public void run() {
        try {
          future.set(fetchApps(start, num));
        } catch (Exception ex) {
          future.setException(ex);
        }
      }
    });
    return future;
  }

  @Override
  public List<RetrostoreAppItem> fetchApps(int start, int num) throws ApiException {
    ListAppsApiParams params = new ListAppsApiParams(start, num);
    String url = String.format(mServerUrl, "listApps");
    try {
      byte[] bytes = mUrlFetcher.fetchUrl(url, params);
      String data = new String(bytes);

      TypeToken<ApiResponse<RetrostoreAppItem>> type = new
          TypeToken<ApiResponse<RetrostoreAppItem>>() {
          };
      ApiResponse<RetrostoreAppItem> apiResponse = new Gson().fromJson(data, type.getType());
      if (!apiResponse.success) {
        throw new ApiException(String.format(
            "Server reported error: '%s'", apiResponse.errorMessage));
      }
      return apiResponse.items;
    } catch (IOException e) {
      throw new ApiException("Unable to make request to server.", e);
    }
  }
}
