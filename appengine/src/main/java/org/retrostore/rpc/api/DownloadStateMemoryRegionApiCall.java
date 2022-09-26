package org.retrostore.rpc.api;

import com.google.protobuf.InvalidProtocolBufferException;
import org.retrostore.client.common.proto.DownloadSystemStateMemoryRegionParams;
import org.retrostore.data.xray.StateManagement;
import org.retrostore.data.xray.SystemState;
import org.retrostore.request.RequestData;
import org.retrostore.request.Responder;
import org.retrostore.request.Response;
import org.retrostore.rpc.internal.ApiCall;

import java.util.Optional;
import java.util.logging.Logger;

public class DownloadStateMemoryRegionApiCall implements ApiCall {
  private static final Logger log = Logger.getLogger("DownloadStateApiCall");

  private final StateManagement mStateManagement;

  public DownloadStateMemoryRegionApiCall(StateManagement stateManagement) {
    mStateManagement = stateManagement;
  }


  @Override
  public String getName() {
    return "downloadStateMemoryRegion";
  }

  @Override
  public Response call(RequestData data) {
    DownloadSystemStateMemoryRegionParams apiParams;
    try {
      apiParams = DownloadSystemStateMemoryRegionParams.parseFrom(data.getRawBody());
    } catch (InvalidProtocolBufferException e) {
      String errMsg = "Cannot parse ProtoBuf params: " + e.getMessage();
      log.warning(errMsg);
      return responder -> responder.respond(new byte[0], Responder.ContentType.BYTES);
    }

    if (apiParams == null || apiParams.getToken() <= 0) {
      String errMsg = "Illegal params. Ensure 'token' is > 0.";
      log.warning(errMsg);
      return responder -> responder.respond(new byte[0], Responder.ContentType.BYTES);
    }
    if (apiParams.getStart() <= 0) {
      String errMsg = "Illegal params. Ensure 'start' is > 0.";
      log.warning(errMsg);
      return responder -> responder.respond(new byte[0], Responder.ContentType.BYTES);
    }
    if (apiParams.getLength() <= 0 || apiParams.getLength() > 10 << 18) {
      String errMsg = "Illegal params. Ensure 'length' is > 0 and not too large.";
      log.warning(errMsg);
      return responder -> responder.respond(new byte[0], Responder.ContentType.BYTES);
    }

    Optional<SystemState> systemState = mStateManagement.getSystemState(apiParams.getToken());
    if (!systemState.isPresent()) {
      String errMsg =
          String.format("Cannot find system state with given token '%d'", apiParams.getToken());
      log.warning(errMsg);
      return responder -> responder.respond(new byte[0], Responder.ContentType.BYTES);
    }

    int startAddr = apiParams.getStart();
    int endAddr = apiParams.getStart() + apiParams.getLength() - 1;

    // Note that overlapping regions should not be a thing. This extraction handles it
    // gracefully though as it simply overwrites the data.
    byte[] result = new byte[apiParams.getLength()];
    for (SystemState.MemoryRegion region : systemState.get().memoryRegions) {
      int regionLength = region.data.length;
      int regionEnd = region.start + regionLength - 1;
      // Check of the region overlaps with the request. (either start or end of the region must
      // lie within the requested region.
      if ((region.start >= startAddr && region.start <= endAddr) ||
          (regionEnd >= startAddr && regionEnd <= endAddr)) {
        int startCopy = Math.max(startAddr, region.start);
        int endCopy = Math.min(endAddr, regionEnd);

        System.arraycopy(region.data, startCopy - region.start, result, startCopy - startAddr,
            endCopy + 1 - startCopy);
    }

      // If the region has an overlap with the requested range, write that portion.
      for (int i = region.start; i >= startAddr && i <= endAddr && i - region.start < region.data.length; ++i) {
        result[i - startAddr] = region.data[i - region.start];
      }
    }
    return responder -> responder.respond(result, Responder.ContentType.BYTES);
  }
}
