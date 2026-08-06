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

import java.io.PrintWriter;
import java.io.StringWriter;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

import javax.servlet.http.HttpServletResponse;

import static com.google.common.truth.Truth.assertThat;

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

  private static final class ResponseCapture implements InvocationHandler {
    final Map<String, String> headers = new HashMap<>();
    final StringWriter content = new StringWriter();
    final PrintWriter writer = new PrintWriter(content);
    String contentType;

    @Override
    public Object invoke(Object proxy, Method method, Object[] args) {
      if (method.getName().equals("setHeader")) {
        headers.put((String) args[0], (String) args[1]);
      } else if (method.getName().equals("setContentType")) {
        contentType = (String) args[0];
      } else if (method.getName().equals("getWriter")) {
        return writer;
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
