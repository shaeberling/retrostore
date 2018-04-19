#ifndef RetrosSore_h
#define RetroStore_h

#include <string>

namespace retrostore {

// API to communicate with the RetroStore server.
class RetroStore
{
  public:
    // Construct with default settings such as server.
    explicit RetroStore();
    // Use custom server.
    RetroStore(const std::string& host, int port);
    // Print version of the library.
    void PrintVersion();
    // Fetch metadata of retrostore apps from catalog.
    bool FetchApps(int start, int num);
    // Fetch media images for the app with the given ID.
    void FetchMediaImages(const std::string& appId);
  private:
    const std::string host_;
    const int port_;
    bool FetchUrl(const std::string& host,
                  const std::string& path,
                  const int port);
};

}  // namespace retrostore

#endif
