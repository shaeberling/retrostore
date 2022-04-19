package org.retrostore.client.common;

/**
 * Parameters used for the downloadState API call.
 */
public class DownloadSystemStateApiParams {
  public final long token;

  public DownloadSystemStateApiParams(long token) {
    this.token = token;
  }
}
