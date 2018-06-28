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

package org.retrostore.rpc;

import org.retrostore.data.app.AppManagement;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.data.user.UserAccountType;
import org.retrostore.request.Responder;
import org.retrostore.rpc.internal.RpcCall;
import org.retrostore.rpc.internal.RpcParameters;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;

/**
 * Returns a list of apps from the datastore.
 */
public class AppListRpcCall implements RpcCall<RpcParameters> {
  private final AppManagement mAppManagement;

  public AppListRpcCall(AppManagement appManagement) {
    mAppManagement = appManagement;
  }

  @Override
  public String getName() {
    return "applist";
  }

  @Override
  public boolean isPermitted(UserAccountType type) {
    return type != UserAccountType.NO_ACCOUNT && type != UserAccountType.NOT_LOGGED_IN;
  }

  @Override
  public void call(RpcParameters params, Responder responder) {
    List<AppStoreItem> allApps = mAppManagement.getAllApps();

    List<AppStoreItem> listingApps = new ArrayList<>(allApps.size());
    // We should probably add a new class here which contains only the stuff we need. For now we
    // simply remove what we don't want to send, i.e. the disk contents.
    for (AppStoreItem app : allApps) {
      AppStoreItem listingApp = new AppStoreItem();
      listingApp.id = app.id;
      listingApp.listing = app.listing;
      listingApp.trs80Extension.model = app.trs80Extension.model;

      listingApps.add(listingApp);
    }

    listingApps.sort((o1, o2) -> {
      if (o1 == null || o1.listing == null || o1.listing.name == null ||
          o2 == null || o2.listing == null) {
        return 0;
      }
      return o1.listing.name.compareTo(o2.listing.name);
    });
    responder.respondJson(listingApps);
  }
}
