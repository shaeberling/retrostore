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

package org.retrostore.net;

import com.google.common.io.ByteStreams;
import com.google.gson.Gson;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URL;
import java.net.URLConnection;

/**
 * Default UrlFetcher implementation.
 */
public class UrlFetcherImpl implements UrlFetcher {
  @Override
  public byte[] fetchUrl(String urlStr, byte[] body) throws IOException {
    URLConnection connection = new URL(urlStr).openConnection();
    connection.setDoOutput(true);
    connection.setDoInput(true);

    OutputStream out = connection.getOutputStream();
    out.write(body);
    out.close();

    InputStream inputStream = connection.getInputStream();
    byte[] content = ByteStreams.toByteArray(inputStream);
    inputStream.close();
    return content;
  }

  @Override
  public byte[] fetchUrl(String url, Object obj) throws IOException {
    return fetchUrl(url, (new Gson().toJson(obj)).getBytes());
  }
}
