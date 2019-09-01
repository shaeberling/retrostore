package org.retrostore.request;

import org.retrostore.data.app.AppManagement;
import org.retrostore.data.app.AppStoreItem;
import org.retrostore.data.app.MediaImage;
import org.retrostore.data.user.UserService;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.Map;
import java.util.Optional;
import java.util.logging.Logger;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/**
 * Serves a bundle that contains the files for an app.
 */
public class DownloadAppRequest implements Request {
  private static final Logger LOG = Logger.getLogger("DownloadAppReq");
  private final AppManagement mAppManagement;

  public DownloadAppRequest(AppManagement appManagement) {
    mAppManagement = appManagement;
  }

  @Override
  public boolean serveUrl(RequestData requestData, Responder responder, UserService userService) {
    if (!requestData.getUrl().startsWith("/downloadapp")) {
      return false;
    }
    if (requestData.getType() != RequestData.Type.GET) {
      return false;
    }
    Optional<String> appId = requestData.getString("appId");
    Optional<String> type = requestData.getString("type");

    if (!appId.isPresent()) {
      responder.respondBadRequest("'appId' missing.");
    } else {
      Optional<AppStoreItem> app = mAppManagement.getAppById(appId.get());
      Optional<byte[]> data = createData(appId.get(), type.orElse(null));

      if (!app.isPresent() || !data.isPresent()) {
        responder.respondBadRequest("Cannot find app with ID " + appId.get());
      } else {
        if (type.isPresent()) {
          responder.respond(data.get(), Responder.ContentType.BYTES);
        } else {
          String appName = app.get().listing.name;
          String filename = appName.replaceAll(" ", "_").replace(".", "_").replaceAll(",", "_");
          responder.respondDownload(data.get(), String.format("%s.zip", filename),
              Responder.ContentType.ZIP);
        }
      }
    }
    return true;
  }

  private Optional<byte[]> createData(String appId, String type) {
    Map<Long, MediaImage> mediaImages = mAppManagement.getMediaImagesForApp(appId);
    if (mediaImages.values().isEmpty()) {
      return Optional.of(new byte[0]);
    }
    if (type == null) {
      try {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        ZipOutputStream zipOs = new ZipOutputStream(out);

        for (MediaImage media : mediaImages.values()) {
          zipOs.putNextEntry(new ZipEntry(media.filename));
          zipOs.write(media.data);
          zipOs.closeEntry();
        }
        zipOs.close();
        return Optional.of(out.toByteArray());
      } catch (IOException ex) {
        LOG.severe("Error trying to creator ZIP file.");
        return Optional.empty();
      }
    } else {
      for (MediaImage media : mediaImages.values()) {
        if (media.filename.toLowerCase().endsWith(String.format(".%s", type.toLowerCase()))) {
          return Optional.of(media.data);
        }
      }
      LOG.warning(String.format("Cannot find media of type %s for app %s", type, appId));
      return Optional.empty();
    }
  }
}
