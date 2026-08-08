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

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.lang.reflect.Proxy;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;

import javax.servlet.http.HttpServletResponse;

import static com.google.common.truth.Truth.assertThat;

public final class MigrationFirmwareExportRequestTest {
  @Test
  public void disabledRouteIsHiddenBeforeAuthorization() {
    RecordingResponder responder = new RecordingResponder();
    AtomicInteger calls = new AtomicInteger();

    request(false, calls)
        .serveUrl(validRequest(), responder, new StubUserService(UserAccountType.NOT_LOGGED_IN));

    assertThat(responder.notFound).isTrue();
    assertThat(responder.forbidden).isNull();
    assertThat(calls.get()).isEqualTo(0);
  }

  @Test
  public void routeRequiresAdminGetAndExactConfirmation() {
    RecordingResponder unauthorized = new RecordingResponder();
    RecordingResponder post = new RecordingResponder();
    RecordingResponder unconfirmed = new RecordingResponder();
    AtomicInteger calls = new AtomicInteger();

    request(true, calls)
        .serveUrl(validRequest(), unauthorized, new StubUserService(UserAccountType.PUBLISHER));
    request(true, calls)
        .serveUrl(
            new StubRequestData(MigrationFirmwareExportRequest.PATH, RequestData.Type.POST)
                .withConfirmation(),
            post,
            new StubUserService(UserAccountType.ADMIN));
    request(true, calls)
        .serveUrl(
            new StubRequestData(MigrationFirmwareExportRequest.PATH, RequestData.Type.GET),
            unconfirmed,
            new StubUserService(UserAccountType.ADMIN));

    assertThat(unauthorized.forbidden).isEqualTo("You need to be an admin");
    assertThat(post.badRequest).isEqualTo("The firmware export operation only accepts GET");
    assertThat(unconfirmed.badRequest).isEqualTo("Firmware export confirmation is required");
    assertThat(calls.get()).isEqualTo(0);
  }

  @Test
  public void unauthenticatedRouteBypassesHtmlLoginAndReachesAuthorization() {
    StubRequestData requestData = validRequest();
    StubUserService userService = new StubUserService(UserAccountType.NOT_LOGGED_IN);
    RecordingResponder responder = new RecordingResponder();

    boolean intercepted = new LoginRequest().serveUrl(requestData, responder, userService);
    boolean served = request(true, new AtomicInteger()).serveUrl(requestData, responder, userService);

    assertThat(intercepted).isFalse();
    assertThat(served).isTrue();
    assertThat(responder.forbidden).isEqualTo("You need to be an admin");
  }

  @Test
  public void streamsSensitiveFirmwareZipAndHidesFailures() {
    RecordingResponder success = new RecordingResponder();
    AtomicInteger calls = new AtomicInteger();
    request(true, calls)
        .serveUrl(validRequest(), success, new StubUserService(UserAccountType.ADMIN));

    assertThat(success.download).isEqualTo("archive".getBytes(StandardCharsets.UTF_8));
    assertThat(success.filename).isEqualTo(MigrationFirmwareExportRequest.FILENAME);
    assertThat(success.contentType).isEqualTo(Responder.ContentType.ZIP);
    assertThat(calls.get()).isEqualTo(1);

    RecordingResponder failure = new RecordingResponder();
    new MigrationFirmwareExportRequest(
            () -> true,
            () -> {
              throw new IllegalStateException("sensitive detail");
            })
        .serveUrl(validRequest(), failure, new StubUserService(UserAccountType.ADMIN));
    assertThat(failure.internalError).isEqualTo("Firmware export failed");
    assertThat(failure.download).isNull();
  }

  private static MigrationFirmwareExportRequest request(boolean enabled, AtomicInteger calls) {
    return new MigrationFirmwareExportRequest(
        () -> enabled,
        () -> {
          calls.incrementAndGet();
          return output -> output.write("archive".getBytes(StandardCharsets.UTF_8));
        });
  }

  private static StubRequestData validRequest() {
    return new StubRequestData(MigrationFirmwareExportRequest.PATH, RequestData.Type.GET)
        .withConfirmation();
  }

  private static final class RecordingResponder extends Responder {
    String forbidden;
    String badRequest;
    String internalError;
    boolean notFound;
    byte[] download;
    String filename;
    ContentType contentType;

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
    public void respondNotFound() {
      notFound = true;
    }

    @Override
    public void respondSensitiveDownload(
        DownloadWriter writer, String name, ContentType type) {
      ByteArrayOutputStream output = new ByteArrayOutputStream();
      try {
        writer.write(output);
      } catch (IOException error) {
        throw new AssertionError(error);
      }
      download = output.toByteArray();
      filename = name;
      contentType = type;
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
    private final Map<String, String> mStrings = new HashMap<>();

    StubRequestData(String url, Type type) {
      mUrl = url;
      mType = type;
    }

    StubRequestData withConfirmation() {
      mStrings.put(
          MigrationFirmwareExportRequest.CONFIRMATION_PARAMETER,
          MigrationFirmwareExportRequest.CONFIRMATION_VALUE);
      return this;
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
      return Optional.ofNullable(mStrings.get(name));
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
