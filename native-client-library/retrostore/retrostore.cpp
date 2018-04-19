#include "retrostore.h"

#include "Arduino.h"
#include <WiFi.h>

#include "rs_proto_api.pb.h"
#include "pb_decode.h"
#include "pb_encode.h"

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
  Serial.println("RetroStore v0.0.3");
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
  size_t message_length = client.read(buffer, BUFFER_SIZE);
  if (message_length >= BUFFER_SIZE) {
    Serial.print("ERROR: Fetch buffer too small: " + String(BUFFER_SIZE));
    return false;
  }
  Serial.print("SUCCESS: Read" + String(message_length) + " bytes.");
  Serial.println("Closing connection");
  client.stop();

  // Decode the protocol buffer message.
  ApiResponseApps response = ApiResponseApps_init_zero;

  // TODO: Extract response body from HTTP response.

  pb_istream_t stream = pb_istream_from_buffer(buffer, message_length);
  bool status = pb_decode_delimited(&stream, ApiResponseApps_fields, &response);

  if (!status) {
    Serial.println("ERROR: Decoding of message failed: " + String(PB_GET_ERROR(&stream)));
    Serial.println("Message as string: " + String((const char*)buffer));
    return false;
  }
  Serial.println("SUCCESS: Message decoded! :-)");

  return true;
}

}  // namespace retrostore