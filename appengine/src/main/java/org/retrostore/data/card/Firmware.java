package org.retrostore.data.card;

import com.googlecode.objectify.Key;

public interface Firmware {
  String getId();
  int getRevision();
  int getVersion();
  byte[] getData();

  interface Creator<T extends Firmware> {
    T create(int revision, int version, byte[] data);
    Key<T> createKey(int revision, int version);
    Class<T> getDataClass();
  }
}
