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

package org.retrostore.request;

import org.junit.Test;
import org.retrostore.data.user.UserAccountType;
import org.retrostore.data.user.UserService;

import java.lang.reflect.Proxy;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;

import javax.servlet.http.HttpServletResponse;

import static com.google.common.truth.Truth.assertThat;

public final class MigrationInventoryRequestTest {
  @Test
  public void ignoresUnrelatedPaths() {
    AtomicInteger calls = new AtomicInteger();
    MigrationInventoryRequest request =
        new MigrationInventoryRequest(
            () -> {
              calls.incrementAndGet();
              return new Object();
            });

    boolean served =
        request.serveUrl(
            new StubRequestData("/api/listApps", RequestData.Type.GET),
            new RecordingResponder(),
            new StubUserService(UserAccountType.ADMIN));

    assertThat(served).isFalse();
    assertThat(calls.get()).isEqualTo(0);
  }

  @Test
  public void requiresRetroStoreAdminRole() {
    RecordingResponder responder = new RecordingResponder();
    MigrationInventoryRequest request = new MigrationInventoryRequest(Object::new);

    boolean served =
        request.serveUrl(
            new StubRequestData(MigrationInventoryRequest.PATH, RequestData.Type.GET),
            responder,
            new StubUserService(UserAccountType.PUBLISHER));

    assertThat(served).isTrue();
    assertThat(responder.forbidden).isEqualTo("You need to be an admin");
    assertThat(responder.json).isNull();
  }

  @Test
  public void unauthenticatedRequestReachesInventoryAuthorization() {
    StubRequestData requestData =
        new StubRequestData(MigrationInventoryRequest.PATH, RequestData.Type.GET);
    StubUserService userService = new StubUserService(UserAccountType.NOT_LOGGED_IN);
    RecordingResponder responder = new RecordingResponder();

    boolean interceptedByLogin =
        new LoginRequest().serveUrl(requestData, responder, userService);
    boolean servedByInventory =
        new MigrationInventoryRequest(Object::new)
            .serveUrl(requestData, responder, userService);

    assertThat(interceptedByLogin).isFalse();
    assertThat(servedByInventory).isTrue();
    assertThat(responder.forbidden).isEqualTo("You need to be an admin");
    assertThat(responder.json).isNull();
  }

  @Test
  public void onlyAcceptsGet() {
    AtomicInteger calls = new AtomicInteger();
    RecordingResponder responder = new RecordingResponder();
    MigrationInventoryRequest request =
        new MigrationInventoryRequest(
            () -> {
              calls.incrementAndGet();
              return new Object();
            });

    request.serveUrl(
        new StubRequestData(MigrationInventoryRequest.PATH, RequestData.Type.POST),
        responder,
        new StubUserService(UserAccountType.ADMIN));

    assertThat(responder.badRequest).isEqualTo("The inventory operation only accepts GET");
    assertThat(calls.get()).isEqualTo(0);
  }

  @Test
  public void returnsNonCacheableJsonToAdmin() {
    Object report = new Object();
    RecordingResponder responder = new RecordingResponder();
    MigrationInventoryRequest request = new MigrationInventoryRequest(() -> report);

    boolean served =
        request.serveUrl(
            new StubRequestData(MigrationInventoryRequest.PATH, RequestData.Type.GET),
            responder,
            new StubUserService(UserAccountType.ADMIN));

    assertThat(served).isTrue();
    assertThat(responder.json).isSameInstanceAs(report);
    assertThat(responder.internalError).isNull();
  }

  @Test
  public void hidesInventoryFailureDetails() {
    RecordingResponder responder = new RecordingResponder();
    MigrationInventoryRequest request =
        new MigrationInventoryRequest(
            () -> {
              throw new IllegalStateException("sensitive detail");
            });

    request.serveUrl(
        new StubRequestData(MigrationInventoryRequest.PATH, RequestData.Type.GET),
        responder,
        new StubUserService(UserAccountType.ADMIN));

    assertThat(responder.internalError).isEqualTo("Inventory failed");
    assertThat(responder.json).isNull();
  }

  private static final class RecordingResponder extends Responder {
    String forbidden;
    String badRequest;
    String internalError;
    Object json;

    RecordingResponder() {
      super(unusedResponse(), null);
    }

    @Override
    public void respondForbidden(String content) {
      forbidden = content;
    }

    @Override
    public void respondBadRequest(String content) {
      badRequest = content;
    }

    @Override
    public void respondInternalServerError(String content) {
      internalError = content;
    }

    @Override
    public void respondJsonNoStore(Object object) {
      json = object;
    }
  }

  private static HttpServletResponse unusedResponse() {
    return (HttpServletResponse)
        Proxy.newProxyInstance(
            HttpServletResponse.class.getClassLoader(),
            new Class<?>[] {HttpServletResponse.class},
            (proxy, method, args) -> {
              Class<?> returnType = method.getReturnType();
              if (returnType == boolean.class) {
                return false;
              }
              if (returnType == int.class) {
                return 0;
              }
              if (returnType == long.class) {
                return 0L;
              }
              return null;
            });
  }

  private static final class StubUserService implements UserService {
    private final UserAccountType mAccountType;

    StubUserService(UserAccountType accountType) {
      mAccountType = accountType;
    }

    @Override
    public boolean systemHasAdmin() {
      return true;
    }

    @Override
    public UserAccountType getForCurrentUser() {
      return mAccountType;
    }

    @Override
    public String createLoginURL(String url) {
      return url;
    }
  }

  private static final class StubRequestData implements RequestData {
    private final String mUrl;
    private final Type mType;

    StubRequestData(String url, Type type) {
      mUrl = url;
      mType = type;
    }

    @Override
    public Type getType() {
      return mType;
    }

    @Override
    public String getUrl() {
      return mUrl;
    }

    @Override
    public String getRootUrl() {
      return "https://example.test";
    }

    @Override
    public Optional<Integer> getInt(String name) {
      return Optional.empty();
    }

    @Override
    public Optional<Long> getLong(String name) {
      return Optional.empty();
    }

    @Override
    public Optional<String> getString(String name) {
      return Optional.empty();
    }

    @Override
    public String getBody() {
      return "";
    }

    @Override
    public byte[] getRawBody() {
      return new byte[0];
    }

    @Override
    public String getCookieRaw() {
      return "";
    }

    @Override
    public List<UploadFile> getFiles() {
      return Collections.emptyList();
    }

    @Override
    public Map<String, List<String>> getBlobKeys() {
      return Collections.emptyMap();
    }
  }
}
