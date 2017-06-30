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

package org.retrostore.util;

import com.google.common.collect.ImmutableList;

import java.util.Collection;
import java.util.List;

/**
 * Can be used to send to the client in serialized form, representing value and its name.
 */
public class DropdownValueForClient {
  public final String value;
  public final String name;

  public DropdownValueForClient(String value, String name) {
    this.value = value;
    this.name = name;
  }

  public static List<DropdownValueForClient> from(Enum[] enums) {
    ImmutableList.Builder<DropdownValueForClient> builder = ImmutableList.builder();
    for (Enum e : enums) {
      builder.add(from(e));
    }
    return builder.build();
  }

  public static DropdownValueForClient from(Enum e) {
    return new DropdownValueForClient(e.name(), e.toString());
  }
}
