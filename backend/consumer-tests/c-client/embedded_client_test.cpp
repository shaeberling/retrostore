#include "backend.h"

#include <cstdio>
#include <cstring>

namespace {

int fail(const char* message) {
  std::fprintf(stderr, "%s\n", message);
  return 1;
}

}  // namespace

int main() {
  set_query("");

  const char* title = get_app_title(0);
  if (std::strcmp(title, "Armored Patrol (Wayne Westmoreland and Terry Gilman)") != 0) {
    return fail("embedded listApps legacy JSON request or nanopb decode failed");
  }

  const char* details = get_app_details(0);
  if (std::strstr(details, "Armored Patrol\nAuthor: Wayne Westmoreland and Terry Gilman") == nullptr) {
    return fail("embedded getApp legacy JSON request or nanopb decode failed");
  }

  int type = 0;
  int size = 0;
  unsigned char* bytes = nullptr;
  int media_index = -1;
  for (int index = 0; index < 100; ++index) {
    const char* candidate_title = get_app_title(index);
    if (candidate_title == nullptr || candidate_title[0] == '\0') {
      break;
    }
    if (std::strcmp(candidate_title, "Space Invaders (Model I Edition) (Tim Walter)") == 0) {
      media_index = index;
      break;
    }
  }
  if (media_index < 0) {
    return fail("embedded paginated listApps did not find the reviewed media fixture");
  }
  if (!get_app_code(media_index, &type, &bytes, &size)) {
    return fail("embedded fetchMediaImages request failed");
  }
  if (type != 3 || size != 3477 || bytes == nullptr) {
    return fail("embedded fetchMediaImages returned the wrong command image");
  }
  const unsigned char expected_prefix[] = {
      0x01, 0x02, 0x00, 0x55, 0xf3, 0x31, 0xff, 0x7f,
      0xcd, 0x23, 0x56, 0x21, 0x15, 0x57, 0x11, 0x59,
  };
  if (std::memcmp(bytes, expected_prefix, sizeof(expected_prefix)) != 0) {
    return fail("embedded nanopb media payload differs from the reviewed fixture");
  }

  return 0;
}
