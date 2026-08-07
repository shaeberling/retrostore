/*
 * Copyright 2026, Sascha Häberling
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

package org.retrostore.rpc.api;

import com.google.protobuf.ByteString;
import org.junit.Test;
import org.retrostore.client.common.proto.SystemState;
import org.retrostore.client.common.proto.UploadSystemStateParams;
import org.retrostore.data.xray.StateManagement;
import org.retrostore.request.RequestData;

import java.lang.reflect.Proxy;
import java.util.Collections;
import java.util.Optional;

import static com.google.common.truth.Truth.assertThat;

public final class UploadStateApiCallTest {
  @Test
  public void acceptsAggregatePayloadLargerThanOneFirestoreDocument() {
    byte[] regionBytes = new byte[999_999];
    SystemState state =
        SystemState.newBuilder()
            .addMemoryRegions(
                SystemState.MemoryRegion.newBuilder()
                    .setStart(0)
                    .setLength(regionBytes.length)
                    .setData(ByteString.copyFrom(regionBytes)))
            .addMemoryRegions(
                SystemState.MemoryRegion.newBuilder()
                    .setStart(1)
                    .setLength(regionBytes.length)
                    .setData(ByteString.copyFrom(regionBytes)))
            .build();
    byte[] body = UploadSystemStateParams.newBuilder().setState(state).build().toByteArray();
    assertThat(body.length).isEqualTo(2_000_028);
    assertThat(body.length).isGreaterThan(1_048_576);

    CapturingStateManagement storage = new CapturingStateManagement();
    new UploadStateApiCall(storage).call(requestWithBody(body));

    assertThat(storage.state).isNotNull();
    assertThat(storage.state.memoryRegions).hasSize(2);
    assertThat(storage.state.memoryRegions.get(0).data).hasLength(999_999);
    assertThat(storage.state.memoryRegions.get(1).data).hasLength(999_999);
  }

  private static RequestData requestWithBody(byte[] body) {
    return (RequestData)
        Proxy.newProxyInstance(
            RequestData.class.getClassLoader(),
            new Class<?>[] {RequestData.class},
            (proxy, method, args) -> {
              switch (method.getName()) {
                case "getRawBody":
                  return body;
                case "getType":
                  return RequestData.Type.POST;
                case "getInt":
                case "getLong":
                case "getString":
                  return Optional.empty();
                case "getFiles":
                  return Collections.emptyList();
                case "getBlobKeys":
                  return Collections.emptyMap();
                default:
                  return "";
              }
            });
  }

  private static final class CapturingStateManagement implements StateManagement {
    org.retrostore.data.xray.SystemState state;

    @Override
    public long addSystemState(org.retrostore.data.xray.SystemState state) {
      this.state = state;
      return 123;
    }

    @Override
    public Optional<org.retrostore.data.xray.SystemState> getSystemState(long token) {
      return Optional.empty();
    }
  }
}
