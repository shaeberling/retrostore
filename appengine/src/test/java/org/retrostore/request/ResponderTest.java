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

import java.io.ByteArrayOutputStream;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

import javax.servlet.ServletOutputStream;
import javax.servlet.WriteListener;
import javax.servlet.http.HttpServletResponse;

import static com.google.common.truth.Truth.assertThat;
import static org.junit.Assert.assertThrows;

public final class ResponderTest {
  @Test
  public void noStoreJsonSetsHeadersAndSerializesBody() {
    ResponseCapture capture = new ResponseCapture();
    HttpServletResponse response =
        (HttpServletResponse)
            Proxy.newProxyInstance(
                HttpServletResponse.class.getClassLoader(),
                new Class<?>[] {HttpServletResponse.class},
                capture);

    new Responder(response, null).respondJsonNoStore(Collections.singletonMap("count", 3));

    capture.writer.flush();
    assertThat(capture.contentType).isEqualTo("application/json");
    assertThat(capture.headers.get("Cache-Control")).isEqualTo("no-store");
    assertThat(capture.headers.get("Pragma")).isEqualTo("no-cache");
    assertThat(capture.content.toString()).isEqualTo("{\"count\":3}");
  }

  @Test
  public void sensitiveDownloadIsPrivateAttachmentWithoutCors() {
    ResponseCapture capture = new ResponseCapture();
    HttpServletResponse response = capture.response();

    new Responder(response, null)
        .respondSensitiveDownload(
            output -> output.write("secret".getBytes(StandardCharsets.UTF_8)),
            "retrostore-catalog-export.zip",
            Responder.ContentType.ZIP);

    assertThat(capture.contentType).isEqualTo("application/zip");
    assertThat(capture.headers.get("Cache-Control"))
        .isEqualTo("no-store, private, max-age=0");
    assertThat(capture.headers.get("Pragma")).isEqualTo("no-cache");
    assertThat(capture.headers.get("X-Content-Type-Options")).isEqualTo("nosniff");
    assertThat(capture.headers.get("Content-Disposition"))
        .isEqualTo("attachment; filename=\"retrostore-catalog-export.zip\"");
    assertThat(capture.headers).doesNotContainKey("Access-Control-Allow-Origin");
    assertThat(capture.binary.toByteArray())
        .isEqualTo("secret".getBytes(StandardCharsets.UTF_8));
  }

  @Test
  public void sensitiveDownloadRejectsUnsafeFilenameBeforeWritingHeaders() {
    ResponseCapture capture = new ResponseCapture();
    Responder responder = new Responder(capture.response(), null);

    IllegalArgumentException error =
        assertThrows(
            IllegalArgumentException.class,
            () ->
                responder.respondSensitiveDownload(
                    output -> output.write(1), "bad\".zip", Responder.ContentType.ZIP));

    assertThat(error).hasMessageThat().contains("unsafe characters");
    assertThat(capture.headers).isEmpty();
  }

  private static final class ResponseCapture implements InvocationHandler {
    final Map<String, String> headers = new HashMap<>();
    final StringWriter content = new StringWriter();
    final PrintWriter writer = new PrintWriter(content);
    final ByteArrayOutputStream binary = new ByteArrayOutputStream();
    final ServletOutputStream output =
        new ServletOutputStream() {
          @Override
          public boolean isReady() {
            return true;
          }

          @Override
          public void setWriteListener(WriteListener listener) {}

          @Override
          public void write(int value) {
            binary.write(value);
          }
        };
    String contentType;

    HttpServletResponse response() {
      return (HttpServletResponse)
          Proxy.newProxyInstance(
              HttpServletResponse.class.getClassLoader(),
              new Class<?>[] {HttpServletResponse.class},
              this);
    }

    @Override
    public Object invoke(Object proxy, Method method, Object[] args) {
      if (method.getName().equals("setHeader")) {
        headers.put((String) args[0], (String) args[1]);
      } else if (method.getName().equals("setContentType")) {
        contentType = (String) args[0];
      } else if (method.getName().equals("getWriter")) {
        return writer;
      } else if (method.getName().equals("getOutputStream")) {
        return output;
      }

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
    }
  }
}
