#include "retrostore.h"

#include "Arduino.h"
#include <WiFi.h>
#include <string>

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

namespace {
// Returns the length (in bytes) of the content in this HTTP response.
int GetHttpResponseContentLength(uint8_t* http_response) {
  // First we need to find the content length which we get in the header.
  string buffer_str((const char*)http_response);
  string content_length_key = "Content-Length: ";
  int start_pos = buffer_str.find(content_length_key) + content_length_key.size();
  if (start_pos < 0) {
    Serial.println("Cannot find 'Content-Length:' marker.");
    return -1;
  }
  int end_pos = buffer_str.find("\r\n", start_pos);
  if (end_pos < 0) {
    Serial.println("Cannot find end of content-lenth value.");
    return -1;
  }

  if (start_pos >= end_pos) {
    Serial.println("start >= end for content-length value range.");
    return -1;
  }
  auto content_length_str = buffer_str.substr(start_pos, end_pos - start_pos);
  return atoi(content_length_str.c_str());
}



}  // namespace

RetroStore::RetroStore()
    : host_(DEFAULT_HOST), port_(DEFAULT_PORT) {
}

RetroStore::RetroStore(const string& host, int port)
    : host_(host), port_(port) {
}

void RetroStore::PrintVersion() {
  Serial.println("RetroStore v0.0.5");
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
    Serial.println("ERROR: Fetch buffer too small: " + String(BUFFER_SIZE));
    return false;
  }
  Serial.println("SUCCESS: Read " + String(message_length) + " bytes.");
  Serial.println("Closing connection");
  client.stop();

  // Extract content from HTTP response.
  int content_length = GetHttpResponseContentLength(buffer);
  uint8_t message[content_length];
  for (int i = message_length - 1, j = content_length - 1; j >= 0; --i, --j) {
    message[j] = buffer[i]; 
  }

  // Decode the protocol buffer message.
  ApiResponseApps response = ApiResponseApps_init_zero;
  pb_istream_t stream = pb_istream_from_buffer(message, content_length);
  bool status = pb_decode(&stream, ApiResponseApps_fields, &response);

  if (!status) {
    Serial.println("ERROR: Decoding of message failed: " + String(PB_GET_ERROR(&stream)));
    return false;
  }
  Serial.println("SUCCESS: Message decoded! :-)");

  if (!response.success) {
    Serial.println("Server reported an ERROR: " + String(response.message));
    return false;
  }

  return true;
}

}  // namespace retrostore