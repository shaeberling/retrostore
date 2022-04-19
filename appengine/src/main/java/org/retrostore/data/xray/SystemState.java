package org.retrostore.data.xray;

import com.googlecode.objectify.Key;
import com.googlecode.objectify.annotation.Cache;
import com.googlecode.objectify.annotation.Entity;
import com.googlecode.objectify.annotation.Id;
import com.googlecode.objectify.annotation.Index;
import org.retrostore.data.app.AppStoreItem;

import java.util.ArrayList;
import java.util.List;

import static com.google.common.base.Preconditions.checkNotNull;

/** The state of a TRS system, including registers and memory. */
@Entity
@Cache
public final class SystemState {
  public static final class Registers {
    public int ix;
    public int iy;
    public int pc;
    public int sp;
    public int af;
    public int bc;
    public int de;
    public int hl;
    public int af_prime;
    public int bc_prime;
    public int de_prime;
    public int hl_prime;
    public int i;
    public int r_1;
    public int r_2;
  }

  public static final class MemoryRegion {
    public int start;
    public byte[] data;
  }

  public enum Model {
    MODEL_I("Model I"),
    MODEL_III("Model III"),
    MODEL_4("Model 4"),
    MODEL_4P("Model 4P");

    private final String readableName;

    Model(String readableName) {
      this.readableName = checkNotNull(readableName);
    }

    @Override
    public String toString() {
      return readableName;
    }
  }

  /** Create a key for a SystemState based on its unique token. */
  public static Key<SystemState> key(Long token) {
    return Key.create(SystemState.class, token);
  }

  @Id public long token;

  @Index public long addTimestamp = System.currentTimeMillis();

  public Registers registers = new Registers();
  public List<MemoryRegion> memoryRegions = new ArrayList<>();
  public Model model;
}
