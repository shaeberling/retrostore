package org.retrostore.rpc.api;

import com.google.gson.Gson;
import com.google.protobuf.ByteString;
import org.retrostore.client.common.DownloadSystemStateApiParams;
import org.retrostore.client.common.proto.ApiResponseDownloadSystemState;
import org.retrostore.client.common.proto.Trs80Model;
import org.retrostore.data.xray.StateManagement;
import org.retrostore.data.xray.SystemState;
import org.retrostore.request.RequestData;
import org.retrostore.request.Response;
import org.retrostore.rpc.internal.ApiCall;

import java.util.Optional;
import java.util.logging.Level;
import java.util.logging.Logger;

public class DownloadStateApiCall implements ApiCall {
  private static final Logger log = Logger.getLogger("DownloadStateApiCall");

  private final StateManagement mStateManagement;

  public DownloadStateApiCall(StateManagement stateManagement) {
    mStateManagement = stateManagement;
  }

  @Override
  public String getName() {
    return "downloadState";
  }

  @Override
  public Response call(RequestData params) {
    ApiResponseDownloadSystemState.Builder response = ApiResponseDownloadSystemState.newBuilder();
    DownloadSystemStateApiParams apiParams = parseParams(params.getBody());

    if (apiParams == null || apiParams.token <= 0) {
      String errMsg = "Illegal params. Ensure 'token' is > 0.";
      log.warning(errMsg);
      response.setSuccess(false);
      response.setMessage(errMsg);
      return responder -> responder.respondProto(response.build());
    }

    Optional<SystemState> systemState = mStateManagement.getSystemState(apiParams.token);
    if (!systemState.isPresent()) {
      String errMsg =
          String.format("Cannot find system state with given token '%d'", apiParams.token);
      log.warning(errMsg);
      response.setSuccess(false);
      response.setMessage(errMsg);
      return responder -> responder.respondProto(response.build());
    }
    SystemState state = systemState.get();
    response.setSuccess(true);
    response.setSystemState(convertToProto(state));
    return responder -> responder.respondProto(response.build());
  }

  private static org.retrostore.client.common.proto.SystemState convertToProto(SystemState state) {
    org.retrostore.client.common.proto.SystemState.Builder proto =
        org.retrostore.client.common.proto.SystemState.newBuilder();

    // MODEL
    switch (state.model) {
      default:
      case MODEL_I:
        proto.setModel(Trs80Model.MODEL_I);
        break;
      case MODEL_III:
        proto.setModel(Trs80Model.MODEL_III);
        break;
      case MODEL_4:
        proto.setModel(Trs80Model.MODEL_4);
        break;
      case MODEL_4P:
        proto.setModel(Trs80Model.MODEL_4P);
        break;
    }

    // REGISTERS
    org.retrostore.client.common.proto.SystemState.Registers.Builder registersProto =
        org.retrostore.client.common.proto.SystemState.Registers.newBuilder();
    registersProto.setIx(state.registers.ix);
    registersProto.setIy(state.registers.iy);
    registersProto.setPc(state.registers.pc);
    registersProto.setSp(state.registers.sp);
    registersProto.setAf(state.registers.af);
    registersProto.setBc(state.registers.bc);
    registersProto.setDe(state.registers.de);
    registersProto.setHl(state.registers.hl);
    registersProto.setAfPrime(state.registers.af_prime);
    registersProto.setBcPrime(state.registers.bc_prime);
    registersProto.setDePrime(state.registers.de_prime);
    registersProto.setHlPrime(state.registers.hl_prime);
    registersProto.setI(state.registers.i);
    registersProto.setR1(state.registers.r_1);
    registersProto.setR2(state.registers.r_2);
    proto.setRegisters(registersProto);

    // MEMORY REGIONS
    for (SystemState.MemoryRegion region : state.memoryRegions) {
      org.retrostore.client.common.proto.SystemState.MemoryRegion.Builder regionProto =
          org.retrostore.client.common.proto.SystemState.MemoryRegion.newBuilder();
      regionProto.setStart(region.start);
      regionProto.setData(ByteString.copyFrom(region.data));
      proto.addMemoryRegions(regionProto);
    }

    return proto.build();
  }

  private DownloadSystemStateApiParams parseParams(String params) {
    try {
      return (new Gson()).fromJson(params, DownloadSystemStateApiParams.class);
    } catch (Exception ex) {
      log.log(Level.WARNING, "Cannot parse params", ex);
      return null;
    }
  }
}
