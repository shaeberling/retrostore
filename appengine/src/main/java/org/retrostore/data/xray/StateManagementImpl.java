package org.retrostore.data.xray;

import com.google.appengine.repackaged.com.google.api.client.util.Sets;

import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.logging.Logger;

import static com.googlecode.objectify.ObjectifyService.ofy;

/** Default implementation for @{@link org.retrostore.data.xray.StateManagement}. */
public class StateManagementImpl implements StateManagement {
  private static final Logger log = Logger.getLogger("StateManagement");

  private static final long MAX_AGE = Duration.ofDays(7).toMillis();

  @Override
  public long addSystemState(SystemState state) {
    // Get a random unused token between 100-999.
    // FIXME: Pick the oldest entry when all are taken!
    state.token = getUnusedToken();
    ofy().save().entity(state).now();
    return state.token;
  }

  @Override
  public Optional<SystemState> getSystemState(long token) {
    return Optional.ofNullable(ofy().load().key(SystemState.key(token)).now());
  }

  private long getUnusedToken() {
    Set<Long> availableTokens = Sets.newHashSet();
    for (int i = 100; i <= 999; ++i) {
      availableTokens.add((long) i);
    }
    List<SystemState> states = ofy().load().type(SystemState.class).list();
    for (SystemState s : states) {
      // Allow expired states to be overwritten.
      if ((System.currentTimeMillis() - s.addTimestamp) <= MAX_AGE) {
        availableTokens.remove(s.token);
      }
    }
    List<Long> tokens = new ArrayList<>(availableTokens);
    Collections.shuffle(tokens);
    return tokens.get(0);
  }
}
