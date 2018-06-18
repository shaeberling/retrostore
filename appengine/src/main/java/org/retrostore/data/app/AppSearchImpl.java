/*
 *  Copyright 2018, Sascha Häberling
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

package org.retrostore.data.app;

import com.google.appengine.api.search.Document;
import com.google.appengine.api.search.Field;
import com.google.appengine.api.search.Index;
import com.google.appengine.api.search.IndexSpec;
import com.google.appengine.api.search.PutException;
import com.google.appengine.api.search.Results;
import com.google.appengine.api.search.ScoredDocument;
import com.google.appengine.api.search.SearchService;
import com.google.appengine.api.search.StatusCode;

import java.util.ArrayList;
import java.util.List;
import java.util.logging.Logger;

public class AppSearchImpl implements AppSearch {
  private static final Logger LOG = Logger.getLogger("AppSearch");
  private static final String INDEX_NAME = "AppStoreItem";
  private final Index mIndex;

  public AppSearchImpl(SearchService searchService) {
    IndexSpec indexSpec = IndexSpec.newBuilder().setName(INDEX_NAME).build();
    mIndex = searchService.getIndex(indexSpec);
  }

  @Override
  public void refreshIndex(List<AppStoreItem> items) {
    // TODO: We should look into deleting old documents.
    List<Document> docs = new ArrayList<>(items.size());
    for (AppStoreItem item : items) {
      docs.add(appToDoc(item));
    }
    putDocuments(docs.toArray(new Document[0]));
  }

  @Override
  public void addOrUpdate(AppStoreItem item) {
    putDocuments(appToDoc(item));
  }

  @Override
  public void remove(String appId) {
    mIndex.delete(appId);
  }

  @Override
  public List<String> search(String query) {
    Results<ScoredDocument> results = mIndex.search(query);
    List<String> appIds = new ArrayList<>();
    for (ScoredDocument doc : results) {
      appIds.add(doc.getId());
    }
    return appIds;
  }

  private static Document appToDoc(AppStoreItem item) {
    AppStoreItem.Listing listing = item.listing;
    return Document.newBuilder().setId(item.id)
        .addField(Field.newBuilder()
            .setName("name")
            .setText(listing.name))
        .addField(Field.newBuilder()
            .setName("description")
            .setText(listing.description))
        .build();
  }

  private boolean putDocuments(Document... document) {
    LOG.info("Putting document into search index.");
    final int maxRetry = 3;
    int attempts = 0;
    int delay = 2;
    while (true) {
      try {
        mIndex.put(document);
      } catch (PutException e) {
        if (StatusCode.TRANSIENT_ERROR.equals(e.getOperationResult().getCode())
            && ++attempts < maxRetry) { // retrying
          try {
            Thread.sleep(delay * 1000);
          } catch (InterruptedException ignore) {
            return false;
          }
          LOG.warning("PUT failed, backing off to retry.");
          // Exponential backoff.
          delay *= 2;
          continue;
        } else {
          LOG.severe("PUT failed repeadetly, giving up.");
          return false;
        }
      }
      break;
    }
    return true;
  }
}
