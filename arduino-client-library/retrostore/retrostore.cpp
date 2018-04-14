#include "retrostore.h"

#include "Arduino.h"
#include <WiFi.h>

namespace retrostore {

using std::string;

namespace {
const string DEFAULT_HOST = "retrostore.org";
// TODO: Secure, HTTPS(443). Use WiFiClientSecure.
const int DEFAULT_PORT = 80;
const string PATH_FETCH_APPS = "/api/listApps";
const string PATH_FETCH_MEDIA_IMAGES = "/api/fetchMediaImages";
// Just for testing, receives a JSON String without API.
const string PATH_JSON_LIST_APPS = "rpc?m=pubapplist";
}

RetroStore::RetroStore()
    : host_(DEFAULT_HOST), port_(DEFAULT_PORT) {
}

RetroStore::RetroStore(const string& host, int port)
    : host_(host), port_(port) {
}

void RetroStore::PrintVersion() {
  Serial.println("RetroStore v0.0.2");
}

bool RetroStore::FetchApps(int start, int num) {
  Serial.println("FetchApps())");
  return FetchUrl(DEFAULT_HOST, PATH_FETCH_APPS, DEFAULT_PORT);
}

void RetroStore::FetchMediaImages(const string& appId) {
  Serial.println("FetchMediaImages()");
}

// private

bool RetroStore::FetchUrl(const string& host_str,
                          const string& path_str,
                          const int port) {
  auto host = host_str.c_str();
  auto path = path_str.c_str();
  WiFiClient client;
  if (!client.connect(host, port)) {
    Serial.println("ERROR: Connection failed.");
    return false;
  }

  // Send request
  client.print((String)"GET /" + String(path) +" HTTP/1.1\r\n" +
               "Host: " + String(host) + "\r\n" +
               "Connection: close\r\n\r\n");
  unsigned long timeout = millis();
  while (client.available() == 0) {
    if (millis() - timeout > 5000) {
      Serial.println("ERROR: Connection timed out.");
      client.stop();
      return false;
    }
  }

  // Read response.
  const int BUFFER_SIZE = 4096;
  uint8_t buffer[BUFFER_SIZE];
  int read = client.read(buffer, BUFFER_SIZE);
  if (read >= BUFFER_SIZE) {
    Serial.print("ERROR: Fetch buffer too small: " + String(BUFFER_SIZE));
    return false;
  }
  Serial.print("SUCCESS: Read" + String(read) + " bytes.");
 
  Serial.println();
  Serial.println("Closing connection");
  client.stop();

  return true;
}

}  // namespace retrostore