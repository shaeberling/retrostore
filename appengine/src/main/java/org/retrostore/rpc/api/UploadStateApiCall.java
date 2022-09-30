package org.retrostore.rpc.api;

import com.google.protobuf.InvalidProtocolBufferException;
import org.retrostore.client.common.proto.ApiResponseUploadSystemState;
import org.retrostore.client.common.proto.SystemState;
import org.retrostore.client.common.proto.UploadSystemStateParams;
import org.retrostore.data.xray.StateManagement;
import org.retrostore.request.RequestData;
import org.retrostore.request.Response;
import org.retrostore.rpc.internal.ApiCall;

import java.util.logging.Logger;

/** Uploads state from an emulator or real TRS system. */
public class UploadStateApiCall implements ApiCall {
  private static final Logger log = Logger.getLogger("UploadStateApiCall");

  private final StateManagement mStateManagement;

  public UploadStateApiCall(StateManagement stateManagement) {
    mStateManagement = stateManagement;
  }

  @Override
  public String getName() {
    return "uploadState";
  }

  @Override
  public Response call(RequestData params) {
    ApiResponseUploadSystemState.Builder response = ApiResponseUploadSystemState.newBuilder();
    UploadSystemStateParams apiParams;
    try {
      apiParams = UploadSystemStateParams.parseFrom(params.getRawBody());
    } catch (InvalidProtocolBufferException e) {
      String errMsg = "Cannot parse ProtoBuf params: " + e.getMessage();
      log.warning(errMsg);
      response.setSuccess(false);
      response.setMessage(errMsg);
      return responder -> responder.respondProto(response.build());
    }

    SystemState systemState = apiParams.getState();
    if (!isStateValid(systemState)) {
      response.setSuccess(false);
      response.setMessage("Uploaded state is invalid");
    } else {
      long token = mStateManagement.addSystemState(convertFromProto(systemState));
      response.setSuccess(true);
      response.setToken(token);
    }
    return responder -> responder.respondProto(response.build());
  }

  /** Return whether the given state is valid. */
  private boolean isStateValid(SystemState state) {
    return state.getMemoryRegionsList()
        .stream()
        .allMatch(UploadStateApiCall::isRegionValid);
  }

  /** Return whether the given region is valid. */
  private static boolean isRegionValid(SystemState.MemoryRegion region) {
    final int MAX_SIZE = 1000000;
    boolean valid = region.getStart() >= 0 && region.getStart() < MAX_SIZE
        && region.getLength() < MAX_SIZE
        && region.getData().toByteArray().length < MAX_SIZE;
    if (!valid) {
      log.warning("===== Region is invalid: =====");
      log.warning("Start        : " + region.getStart());
      log.warning("Length       : " + region.getLength());
      log.warning("Bytes Length : " + region.getData().toByteArray().length);
    }
    return valid;
  }

  private static org.retrostore.data.xray.SystemState convertFromProto(SystemState proto) {
    org.retrostore.data.xray.SystemState state = new org.retrostore.data.xray.SystemState();

    switch (proto.getModel()) {
      case UNRECOGNIZED:
      case UNKNOWN_MODEL:
        log.warning("Unknown model");
        break;
      case MODEL_I:
        state.model = org.retrostore.data.xray.SystemState.Model.MODEL_I;
        break;
      case MODEL_III:
        state.model = org.retrostore.data.xray.SystemState.Model.MODEL_III;
        break;
      case MODEL_4:
        state.model = org.retrostore.data.xray.SystemState.Model.MODEL_4;
        break;
      case MODEL_4P:
        state.model = org.retrostore.data.xray.SystemState.Model.MODEL_4P;
        break;
    }


    org.retrostore.data.xray.SystemState.Registers registers =
        new org.retrostore.data.xray.SystemState.Registers();
    SystemState.Registers protoRegisters = proto.getRegisters();

    registers.ix = protoRegisters.getIx();
    registers.iy = protoRegisters.getIy();
    registers.pc = protoRegisters.getPc();
    registers.sp = protoRegisters.getSp();
    registers.af = protoRegisters.getAf();
    registers.bc = protoRegisters.getBc();
    registers.de = protoRegisters.getDe();
    registers.hl = protoRegisters.getHl();
    registers.af_prime = protoRegisters.getAfPrime();
    registers.bc_prime = protoRegisters.getBcPrime();
    registers.de_prime = protoRegisters.getDePrime();
    registers.hl_prime = protoRegisters.getHlPrime();
    registers.i = protoRegisters.getI();
    registers.r_1 = protoRegisters.getR1();
    registers.r_2 = protoRegisters.getR2();
    state.registers = registers;

    for (SystemState.MemoryRegion protoRegion : proto.getMemoryRegionsList()) {
      org.retrostore.data.xray.SystemState.MemoryRegion region =
          new org.retrostore.data.xray.SystemState.MemoryRegion();
      region.start = protoRegion.getStart();
      region.data = protoRegion.getData().toByteArray();
      state.memoryRegions.add(region);
    }

    return state;
  }
}
