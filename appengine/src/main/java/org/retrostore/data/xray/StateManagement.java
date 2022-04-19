package org.retrostore.data.xray;

import java.util.Optional;

/** Functionality to manage system states. */
public interface StateManagement {
  /**
   * Persists the given state.
   *
   * @param state the state to persist.
   * @return A unique identifier that can later be used to retrieve the state.
   */
  long addSystemState(SystemState state);

  /**
   * Retrieves the system state given a token. This token is obtained when adding a system state.
   */
  Optional<SystemState> getSystemState(long token);
}
