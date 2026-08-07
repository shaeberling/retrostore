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

public final class MigrationCatalogExportRequestTest {
  @Test
  public void ignoresUnrelatedPaths() {
    AtomicInteger calls = new AtomicInteger();
    MigrationCatalogExportRequest request = request(true, calls, "archive");

    boolean served =
        request.serveUrl(
            new StubRequestData("/api/listApps", RequestData.Type.GET),
            new RecordingResponder(),
            new StubUserService(UserAccountType.ADMIN));

    assertThat(served).isFalse();
    assertThat(calls.get()).isEqualTo(0);
  }

  @Test
  public void disabledVersionReturnsNotFoundBeforeAuthorization() {
    AtomicInteger calls = new AtomicInteger();
    RecordingResponder responder = new RecordingResponder();

    boolean served =
        request(false, calls, "archive")
            .serveUrl(
                validRequest(), responder, new StubUserService(UserAccountType.NOT_LOGGED_IN));

    assertThat(served).isTrue();
    assertThat(responder.notFound).isTrue();
    assertThat(responder.forbidden).isNull();
    assertThat(calls.get()).isEqualTo(0);
  }

  @Test
  public void environmentGateOnlyAllowsNamedDefaultServiceVersions() {
    assertThat(
            MigrationCatalogExportRequest.isEnabledEnvironment(
                "default", "migration-export-20260807"))
        .isTrue();
    assertThat(MigrationCatalogExportRequest.isEnabledEnvironment("default", "production"))
        .isFalse();
    assertThat(
            MigrationCatalogExportRequest.isEnabledEnvironment("admin", "migration-export-test"))
        .isFalse();
    assertThat(
            MigrationCatalogExportRequest.isEnabledEnvironment(
                "default", MigrationCatalogExportRequest.VERSION_PREFIX))
        .isFalse();
    assertThat(MigrationCatalogExportRequest.isEnabledEnvironment("default", null)).isFalse();
  }

  @Test
  public void requiresRetroStoreAdminRole() {
    AtomicInteger calls = new AtomicInteger();
    RecordingResponder responder = new RecordingResponder();

    request(true, calls, "archive")
        .serveUrl(validRequest(), responder, new StubUserService(UserAccountType.PUBLISHER));

    assertThat(responder.forbidden).isEqualTo("You need to be an admin");
    assertThat(responder.download).isNull();
    assertThat(calls.get()).isEqualTo(0);
  }

  @Test
  public void unauthenticatedRequestReachesExportAuthorization() {
    StubRequestData requestData = validRequest();
    StubUserService userService = new StubUserService(UserAccountType.NOT_LOGGED_IN);
    RecordingResponder responder = new RecordingResponder();

    boolean interceptedByLogin = new LoginRequest().serveUrl(requestData, responder, userService);
    boolean servedByExport = request(true, new AtomicInteger(), "archive")
        .serveUrl(requestData, responder, userService);

    assertThat(interceptedByLogin).isFalse();
    assertThat(servedByExport).isTrue();
    assertThat(responder.forbidden).isEqualTo("You need to be an admin");
  }

  @Test
  public void onlyAcceptsGet() {
    AtomicInteger calls = new AtomicInteger();
    RecordingResponder responder = new RecordingResponder();
    StubRequestData requestData =
        new StubRequestData(MigrationCatalogExportRequest.PATH, RequestData.Type.POST)
            .withConfirmation();

    request(true, calls, "archive")
        .serveUrl(requestData, responder, new StubUserService(UserAccountType.ADMIN));

    assertThat(responder.badRequest)
        .isEqualTo("The catalog export operation only accepts GET");
    assertThat(calls.get()).isEqualTo(0);
  }

  @Test
  public void requiresExactConfirmation() {
    AtomicInteger calls = new AtomicInteger();
    RecordingResponder responder = new RecordingResponder();

    request(true, calls, "archive")
        .serveUrl(
            new StubRequestData(MigrationCatalogExportRequest.PATH, RequestData.Type.GET),
            responder,
            new StubUserService(UserAccountType.ADMIN));

    assertThat(responder.badRequest).isEqualTo("Catalog export confirmation is required");
    assertThat(calls.get()).isEqualTo(0);
  }

  @Test
  public void streamsSensitiveZipToAdmin() {
    AtomicInteger calls = new AtomicInteger();
    RecordingResponder responder = new RecordingResponder();

    boolean served =
        request(true, calls, "archive")
            .serveUrl(validRequest(), responder, new StubUserService(UserAccountType.ADMIN));

    assertThat(served).isTrue();
    assertThat(calls.get()).isEqualTo(1);
    assertThat(responder.download).isEqualTo("archive".getBytes(StandardCharsets.UTF_8));
    assertThat(responder.filename).isEqualTo(MigrationCatalogExportRequest.FILENAME);
    assertThat(responder.contentType).isEqualTo(Responder.ContentType.ZIP);
    assertThat(responder.internalError).isNull();
  }

  @Test
  public void hidesExporterFailureDetails() {
    RecordingResponder responder = new RecordingResponder();
    MigrationCatalogExportRequest request =
        new MigrationCatalogExportRequest(
            () -> true,
            () -> {
              throw new IllegalStateException("sensitive detail");
            });

    request.serveUrl(validRequest(), responder, new StubUserService(UserAccountType.ADMIN));

    assertThat(responder.internalError).isEqualTo("Catalog export failed");
    assertThat(responder.download).isNull();
  }

  private static MigrationCatalogExportRequest request(
      boolean enabled, AtomicInteger calls, String content) {
    return new MigrationCatalogExportRequest(
        () -> enabled,
        () -> {
          calls.incrementAndGet();
          return output -> output.write(content.getBytes(StandardCharsets.UTF_8));
        });
  }

  private static StubRequestData validRequest() {
    return new StubRequestData(MigrationCatalogExportRequest.PATH, RequestData.Type.GET)
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
      } catch (IOException e) {
        throw new AssertionError(e);
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
          MigrationCatalogExportRequest.CONFIRMATION_PARAMETER,
          MigrationCatalogExportRequest.CONFIRMATION_VALUE);
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
