/*
 * Copyright 2017, Sascha Häberling
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *        http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.retrostore.rpc.internal;

import com.google.gson.Gson;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.zip.GZIPOutputStream;

import static com.google.common.base.Preconditions.checkNotNull;

/**
 * Serializes the data to JSON.
 */
public class WireMessageJsonImpl implements WireMessage {
  private final Object mObject;

  public WireMessageJsonImpl(Object object) {
    mObject = checkNotNull(object);
  }

  @Override
  public byte[] toWireFormat(boolean gzip) throws IOException {
    byte[] serialized = (new Gson()).toJson(mObject).getBytes();
    if (gzip) {
      ByteArrayOutputStream bos = new ByteArrayOutputStream();
      GZIPOutputStream gos = new GZIPOutputStream(bos);
      gos.write(serialized);
      gos.close();
      bos.close();
      return bos.toByteArray();
    }
    return serialized;
  }
}
