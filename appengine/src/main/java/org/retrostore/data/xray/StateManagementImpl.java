package org.retrostore.data.xray;

import com.google.appengine.repackaged.com.google.api.client.util.Sets;
import org.retrostore.resources.MemcacheWrapper;

import java.time.Duration;
import java.util.List;
import java.util.Optional;
import java.util.Random;
import java.util.Set;
import java.util.logging.Logger;

import static com.googlecode.objectify.ObjectifyService.ofy;

/** Default implementation for @{@link org.retrostore.data.xray.StateManagement}. */
public class StateManagementImpl implements StateManagement {
  private static final Logger log = Logger.getLogger("StateManagement");

  private static final long MAX_AGE = Duration.ofDays(7).toMillis();
  private static final String MEMCACHE_AVAILABLE_TOKENS_KEY = "AVAILABLE_STATE_TOKENS";
  private final MemcacheWrapper memcache;

  public StateManagementImpl(MemcacheWrapper memcache) {
    this.memcache = memcache;
  }

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
    Set<Long> availableTokens = getAvailableTokens();
    Long[] tokens = availableTokens.toArray(new Long[0]);
    long token = tokens[(new Random()).nextInt(tokens.length)];

    // Update the cached version by removing the newly minted token.
    availableTokens.remove(token);
    memcache.put(MEMCACHE_AVAILABLE_TOKENS_KEY, availableTokens);
    return token;
  }

  private Set<Long> getAvailableTokens() {
    Optional<Object> tokens = memcache.getObject(MEMCACHE_AVAILABLE_TOKENS_KEY);
    if (!tokens.isPresent() || ((Set<Long>) tokens.get()).isEmpty()) {
      log.info("Getting available tokens from storage.");
      return getAvailableTokensFromStorage();
    }
    Set<Long> availableTokens = (Set<Long>) tokens.get();
    log.info("Got available tokens from cache. Size: " + availableTokens.size());
    return availableTokens;
  }


  private Set<Long> getAvailableTokensFromStorage() {
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
    return availableTokens;
  }
}
