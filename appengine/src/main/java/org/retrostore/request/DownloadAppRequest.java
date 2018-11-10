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
    if (!appId.isPresent()) {
      responder.respondBadRequest("'appId' missing.");
    } else {
      Optional<AppStoreItem> app = mAppManagement.getAppById(appId.get());
      Optional<byte[]> zipFile = createZipFile(appId.get());

      if (!app.isPresent() || !zipFile.isPresent()) {
        responder.respondBadRequest("Cannot find app with ID " + appId.get());
      } else {
        String appName = app.get().listing.name;
        String filename = appName.replaceAll(" ", "_").replace(".", "_").replaceAll(",", "_");
        responder.respondDownload(zipFile.get(), String.format("%s.zip", filename),
            Responder.ContentType.ZIP);
      }
    }
    return true;
  }

  private Optional<byte[]> createZipFile(String appId) {
    Map<Long, MediaImage> mediaImages = mAppManagement.getMediaImagesForApp(appId);
    if (mediaImages.values().isEmpty()) {
      return Optional.of(new byte[0]);
    }

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
      LOG.severe("Error trying to create ZIP file.");
      return Optional.empty();
    }
  }
}
