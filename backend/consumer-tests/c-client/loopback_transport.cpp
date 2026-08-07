#include "utils.h"

#include <cerrno>
#include <cstdlib>

bool connect_server(int* fd) {
  const char* port_text = std::getenv("RETROSTORE_CANDIDATE_PORT");
  if (port_text == nullptr) {
    return false;
  }
  char* end = nullptr;
  errno = 0;
  const long port = std::strtol(port_text, &end, 10);
  if (errno != 0 || end == port_text || *end != '\0' || port <= 0 || port > 65535) {
    return false;
  }

  *fd = socket(AF_INET, SOCK_STREAM, 0);
  if (*fd < 0) {
    return false;
  }

  sockaddr_in address = {};
  address.sin_family = AF_INET;
  address.sin_port = htons(static_cast<uint16_t>(port));
  address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  return connect(*fd, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0;
}

bool skip_to_body(int fd) {
  char buffer[3];
  while (true) {
    if (recv(fd, buffer, 1, MSG_WAITALL) != 1) {
      return false;
    }
    if (buffer[0] != '\r') {
      continue;
    }
    if (recv(fd, buffer, 3, MSG_WAITALL) != 3) {
      return false;
    }
    if (buffer[0] == '\n' && buffer[1] == '\r' && buffer[2] == '\n') {
      return true;
    }
  }
}
