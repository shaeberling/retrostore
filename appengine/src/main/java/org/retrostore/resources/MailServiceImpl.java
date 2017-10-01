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

import javax.mail.Message;
import javax.mail.MessagingException;
import javax.mail.Session;
import javax.mail.Transport;
import javax.mail.internet.InternetAddress;
import javax.mail.internet.MimeMessage;
import java.io.UnsupportedEncodingException;
import java.util.Properties;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Default implementation of the mail service.
 */
public class MailServiceImpl implements MailService {
  private static final Logger LOG = Logger.getLogger("MailService");

  /** Important: This address needs to be set in the cloud console to be allowed to send. */
  private static final String FROM_EMAIL = "saschah@gmail.com";
  private static final String FROM_NAME = "RetroStore";

  @Override
  public boolean sendEmail(String[] to, String subject, String message) {
    Properties props = new Properties();
    Session session = Session.getDefaultInstance(props, null);

    try {
      Message msg = new MimeMessage(session);
      msg.setFrom(new InternetAddress(FROM_EMAIL, FROM_NAME));
      for (String recipient : to) {
        msg.addRecipient(Message.RecipientType.TO, new InternetAddress(recipient));
      }
      msg.setSubject(subject);
      msg.setText(message);
      Transport.send(msg);
      return true;
    } catch (MessagingException | UnsupportedEncodingException e) {
      LOG.log(Level.SEVERE, "Cannot send e-mail.", e);
      return false;
    }
  }
}
