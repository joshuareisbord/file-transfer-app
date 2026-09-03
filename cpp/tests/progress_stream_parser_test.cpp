#include <chrono>
#include <iostream>
#include <thread>
#include <vector>

// ProgressStreamParser is intentionally private to the transfer implementation.
// Including the implementation keeps this focused regression test out of the
// production API and the default build path.
#include "../src/transfer.cpp"

int main() {
    using namespace std::chrono_literals;

    std::vector<work_transfer::TransferProgress> events;
    work_transfer::ProgressStreamParser parser(
        "large-update.bin", 60'000'000'000ULL,
        [&events](const work_transfer::TransferProgress& progress) {
            events.push_back(progress);
        });

    constexpr std::string_view rounded_progress =
        "large-update.bin 20% 10GB 100MB/s 08:00 ETA\r";
    parser.feed(rounded_progress);

    // This test exercises real elapsed-time behavior because the defect is the
    // production five-second liveness boundary itself. Valid OpenSSH records
    // continue arriving while its human-readable byte field remains rounded.
    for (int sample = 0; sample < 6; ++sample) {
        std::this_thread::sleep_for(1s);
        parser.feed(rounded_progress);
        parser.tick();
    }

    for (const auto& event : events) {
        if (event.is_stalled) {
            std::cerr << "valid SCP progress records triggered a false stall\n";
            return 1;
        }
    }
    return 0;
}
