package org.retrostore.rpc.api;

import com.google.protobuf.InvalidProtocolBufferException;
import org.retrostore.client.common.proto.ApiResponseMediaImageRefs;
import org.retrostore.client.common.proto.ApiResponseMediaImages;
import org.retrostore.client.common.proto.DownloadSystemStateMemoryRegionParams;
import org.retrostore.client.common.proto.FetchMediaImageRegionParams;
import org.retrostore.client.common.proto.MediaImage;
import org.retrostore.client.common.proto.MediaImageRef;
import org.retrostore.data.app.AppManagement;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.data.xray.StateManagement;
import org.retrostore.data.xray.SystemState;
import org.retrostore.request.RequestData;
import org.retrostore.request.Responder;
import org.retrostore.request.Response;
import org.retrostore.rpc.internal.ApiCall;

import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.logging.Logger;

public class FetchMediaImageRegionApiCall implements ApiCall {
  private static final Logger log = Logger.getLogger("DownloadStateApiCall");
  private static final Map<String, byte[]> CACHE = new HashMap<>();

  private final FetchMediaImagesApiCall mediaImageCall;

  public FetchMediaImageRegionApiCall(AppManagement appManagement) {
    mediaImageCall = new FetchMediaImagesApiCall(appManagement);
  }

  @Override
  public String getName() {
    return "fetchMediaImageRegion";
  }

  @Override
  public Response call(RequestData data) {
    FetchMediaImageRegionParams apiParams;
    try {
      apiParams = FetchMediaImageRegionParams.parseFrom(data.getRawBody());
    } catch (InvalidProtocolBufferException e) {
      String errMsg = "Cannot parse ProtoBuf params: " + e.getMessage();
      log.warning(errMsg);
      return responder -> responder.respond(new byte[0], Responder.ContentType.BYTES);
    }


    if (apiParams == null || apiParams.getToken().isBlank()) {
      String errMsg = "Illegal params. Ensure 'token' is set.";
      log.warning(errMsg);
      return responder -> responder.respond(new byte[0], Responder.ContentType.BYTES);
    }
    String[] tokenSplit = apiParams.getToken().split("/");

    if (tokenSplit.length != 2 || tokenSplit[0].isBlank() || tokenSplit[1].isBlank()) {
      String errMsg = "Illegal params. Ensure 'token' has the right format.";
      log.warning(errMsg);
      return responder -> responder.respond(new byte[0], Responder.ContentType.BYTES);
    }
    String paramAppId = tokenSplit[0];
    String paramFileName = tokenSplit[1];


    if (apiParams.getStart() < 0) {
      log.warning("Illegal params. Ensure 'start' is > 0.");
      return responder -> responder.respond(new byte[0], Responder.ContentType.BYTES);
    }
    if (apiParams.getLength() <= 0 || apiParams.getLength() > 10 << 18) {
      log.warning("Illegal params. Ensure 'length' is > 0 and not too large.");
      return responder -> responder.respond(new byte[0], Responder.ContentType.BYTES);
    }

    // Check if the image is already in the runtime cache. If not, load it.
    if (!CACHE.containsKey(apiParams.getToken())) {
      FetchMediaImagesApiCall.Params mediaImageParams =
          new FetchMediaImagesApiCall.Params(paramAppId, Set.of());


      // Piggyback on top of the original media image fetch call, to avoid code duplication.
      ApiResponseMediaImages mediaImages = mediaImageCall.callInternal(mediaImageParams);

      // Return error if fetching the media images failed.
      if (!mediaImages.getSuccess()) {
        log.warning("Could not obtain media images.");
        return responder -> responder.respond(new byte[0], Responder.ContentType.BYTES);
      }

      // Convert all media images to references.
      for (MediaImage image : mediaImages.getMediaImageList()) {
        // Skip empty/UNKNOWN entries.
        if (image.getData().size() == 0) continue;

        if (image.getFilename().equals(paramFileName)) {
          CACHE.put(apiParams.getToken(), image.getData().toByteArray());
          break;
        }
      }
    }

    byte[] mediaImageBytes = CACHE.get(apiParams.getToken());

    // Ensure we don't copy beyond the actual size of the image.
    int maxLength = mediaImageBytes.length - apiParams.getStart();
    int len = Math.max(0, Math.min(maxLength, apiParams.getLength()));
    byte[] result = new byte[len];

    if (apiParams.getStart() <= mediaImageBytes.length) {
      System.arraycopy(mediaImageBytes, apiParams.getStart(), result, 0, len);
    }
    return responder -> responder.respond(result, Responder.ContentType.BYTES);
  }
}
