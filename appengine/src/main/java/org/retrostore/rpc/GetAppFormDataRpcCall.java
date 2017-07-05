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

import com.google.common.collect.ImmutableList;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.data.app.Author;
import org.retrostore.data.user.UserAccountType;
import org.retrostore.request.Responder;
import org.retrostore.rpc.internal.RpcCall;
import org.retrostore.rpc.internal.RpcParameters;
import org.retrostore.util.DropdownValueForClient;

import java.util.ArrayList;
import java.util.List;

/**
 * Receives data to be used to fill in the app management forms.
 */
public class GetAppFormDataRpcCall implements RpcCall<RpcParameters> {
  private final AppManagement mAppManagement;

  public GetAppFormDataRpcCall(AppManagement appManagement) {
    mAppManagement = appManagement;
  }

  private static class AppFormData {
    List<DropdownValueForClient> existingAppAuthors = new ArrayList<>();
    List<DropdownValueForClient> appListingCategories = new ArrayList<>();
    List<DropdownValueForClient> trsModels = new ArrayList<>();
    List<DropdownValueForClient> keyboardLayouts = new ArrayList<>();
    List<DropdownValueForClient> characterColors = new ArrayList<>();
  }

  @Override
  public String getName() {
    return "getAppFormData";
  }

  @Override
  public boolean isPermitted(UserAccountType type) {
    return type != UserAccountType.NO_ACCOUNT && type != UserAccountType.NOT_LOGGED_IN;
  }

  @Override
  public void call(RpcParameters params, Responder responder) {
    AppFormData appFormData = new AppFormData();

    appFormData.existingAppAuthors = forAuthors(mAppManagement.listAuthors());
    appFormData.appListingCategories =
        DropdownValueForClient.from(AppStoreItem.ListingCategory.values());
    appFormData.trsModels = DropdownValueForClient.from(AppStoreItem.Model.values());
    appFormData.keyboardLayouts = DropdownValueForClient.from(AppStoreItem.KeyboardLayout.values());
    appFormData.characterColors = DropdownValueForClient.from(AppStoreItem.CharacterColor.values());

    responder.respondObject(appFormData);
  }

  private static List<DropdownValueForClient> forAuthors(List<Author> authors) {
    ImmutableList.Builder<DropdownValueForClient> builder = ImmutableList.builder();
    for (Author author : authors) {
      builder.add(new DropdownValueForClient(String.valueOf(author.id), author.name));
    }
    return builder.build();
  }
}
