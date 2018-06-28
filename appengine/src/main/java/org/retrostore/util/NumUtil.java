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

import com.google.common.base.Strings;

import java.util.Optional;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Utility funcitons for handling numbers.
 */
public class NumUtil {
  private static final Logger LOG = Logger.getLogger("NumUtil");

  /**
   * Parses a long value from a string.
   *
   * @param longStr the long value as a string.
   * @return The long value, or absent if the string could not be parsed.
   */
  public static Optional<Long> parseLong(String longStr) {
    if (Strings.isNullOrEmpty(longStr)) {
      return Optional.empty();
    }
    try {
      return Optional.of(Long.parseLong(longStr));
    } catch (NumberFormatException ex) {
      LOG.log(Level.SEVERE, "Cannot parse integer", ex);
      return Optional.empty();
    }
  }

  public static Optional<Long> parseLong(Optional<String> longStr) {
    if (!longStr.isPresent()) {
      return Optional.empty();
    }
    return parseLong(longStr.get());
  }

  /**
   * Parses a int value from a string.
   *
   * @param intStr the int value as a string.
   * @return The int value, or absent if the string could not be parsed.
   */
  public static Optional<Integer> parseInteger(String intStr) {
    if (Strings.isNullOrEmpty(intStr)) {
      return Optional.empty();
    }
    try {
      return Optional.of(Integer.parseInt(intStr));
    } catch (NumberFormatException ex) {
      LOG.log(Level.SEVERE, "Cannot parse integer", ex);
      return Optional.empty();
    }
  }
}
