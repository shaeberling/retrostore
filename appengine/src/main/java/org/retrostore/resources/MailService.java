/*
 *  Copyright 2017, Sascha Häberling
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *         http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 */

package org.retrostore.resources;

/**
 * Classes implementing this interface can send e-mails.
 */
public interface MailService {
  /**
   * Send an e-mail.
   *  @param to      a list of recipients.
   * @param subject the subject of the e-mail.
   * @param message the message of the e-mail.
   */
  boolean sendEmail(String[] to, String subject, String message);
}
