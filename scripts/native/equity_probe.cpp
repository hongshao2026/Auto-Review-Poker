// Standalone text-protocol fixture for hrc_equity.hpp; no original solver input.
#include "../../native/hrc_equity.hpp"
#include <chrono>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>

using namespace hrc_equity;
std::vector<std::string> split(const std::string& s, char delimiter) {
    std::vector<std::string> result;
    std::size_t first = 0, next;
    do { next = s.find(delimiter, first); result.push_back(s.substr(first, next - first)); first = next + 1; } while (next != std::string::npos);
    return result;
}
std::vector<double> numbers(const std::string& s) {
    std::vector<double> result;
    if (s.empty() || s == "-") return result;
    for (const auto& part : split(s, ',')) result.push_back(std::stod(part));
    return result;
}
std::vector<std::int64_t> integers(const std::string& s) {
    std::vector<std::int64_t> result;
    if (s.empty() || s == "-") return result;
    for (const auto& part : split(s, ',')) result.push_back(std::stoll(part));
    return result;
}
std::string quoted(const std::string& s) {
    std::string r = "\"";
    for (char c : s) { if (c == '\\' || c == '"') r += '\\'; if (c == '\n') r += "\\n"; else if (c == '\r') r += "\\r"; else if (c == '\t') r += "\\t"; else r += c; }
    return r + '"';
}
template<class T> void array(const T& values, std::size_t n) {
    std::cout << '[';
    for (std::size_t i = 0; i < n; ++i) { if (i) std::cout << ','; std::cout << values[i]; }
    std::cout << ']';
}
int main() {
    std::cout << std::setprecision(17);
    for (std::string line; std::getline(std::cin, line);) {
        if (line.empty()) continue;
        auto p = split(line, '\t');
        try {
            if (p.size() >= 2 && p[1] == "icm") {
                if (p.size() != 4) throw std::invalid_argument("ICM input needs 4 tab-separated fields");
                const auto result = icm_equities(numbers(p[2]), numbers(p[3]));
                std::cout << "{\"id\":" << quoted(p[0]) << ",\"total\":"; array(result, result.size()); std::cout << "}\n";
                continue;
            }
            if (p.size() != 14 || (p[1] != "terminal" && p[1] != "cache" && p[1] != "maskcache" && p[1] != "bench" && p[1] != "unusedstacks" && p[1] != "unusedmasks")) throw std::invalid_argument("Terminal input needs 14 tab-separated fields");
            EquityConfig c;
            c.mode = Mode(std::stoul(p[2])); c.bounty_mode = BountyMode(std::stoul(p[3]));
            c.initial_stacks = integers(p[4]); c.payouts = numbers(p[6]); c.bounties = numbers(p[7]);
            c.immediate_fraction = std::stod(p[8]); c.other_stacks = numbers(p[10]); c.other_bounties = numbers(p[11]);
            c.chip_unit = std::stod(p[12]); c.cache_capacity = std::stoull(p[13]);
            Chips final{}, initial{}; WinnerMasks winners{};
            const auto finals = integers(p[5]), masks = integers(p[9]);
            if (finals.size() != c.initial_stacks.size() || masks.size() != finals.size() || finals.size() > MAX_PLAYERS)
                throw std::invalid_argument("Terminal vectors must match the player count");
            std::copy(finals.begin(), finals.end(), final.begin());
            std::copy(c.initial_stacks.begin(), c.initial_stacks.end(), initial.begin());
            for (std::size_t i = 0; i < masks.size(); ++i) {
                if (masks[i] < 0 || masks[i] > 65535) throw std::invalid_argument("Winner mask must fit uint16");
                winners[i] = std::uint16_t(masks[i]);
            }
            // This explicitly labelled test callback uses exact all-field ICM
            // (<=10 total players); it is not the production MTT backend.
            MttEvaluator fixture;
            if (c.mode == Mode::MTT) fixture = [](const std::vector<double>& live, const std::vector<double>& payouts, const std::vector<double>& other) {
                auto combined = live; combined.insert(combined.end(), other.begin(), other.end());
                auto values = icm_equities(combined, payouts); values.resize(live.size()); return values;
            };
            Calculator calculator(c, fixture);
            auto result = calculator.compute_terminal(final, winners);
            calculator.compute_terminal(final, winners);
            if (p[1] == "unusedstacks" || p[1] == "unusedmasks") {
                if (finals.size() == MAX_PLAYERS) throw std::invalid_argument("Unused-seat probe requires a vacant seat");
                // These keys hash to the already populated slot: unused seats
                // are not hashed, but must still participate in full equality.
                if (p[1] == "unusedstacks") final[finals.size()] = 1;
                else winners[finals.size()] = 1;
                calculator.compute_terminal(final, winners);
                throw std::runtime_error("Invalid unused seat unexpectedly accepted");
            }
            if (p[1] == "cache") { calculator.compute_terminal(initial); result = calculator.compute_terminal(final, winners); }
            Values alternate{};
            if (p[1] == "maskcache") {
                auto changed = winners;
                for (std::size_t i = 0; i < finals.size(); ++i) if (!finals[i]) {
                    changed[i] = std::uint16_t(winners[i] & std::uint16_t(-winners[i])); break;
                }
                alternate = calculator.compute_terminal(final, changed).total;
                result = calculator.compute_terminal(final, winners);
            }
            double seconds = 0; std::uint64_t repetitions = 0; volatile double checksum = 0;
            if (p[1] == "bench") {
                repetitions = c.cache_capacity ? 1000000 : 10000;
                auto start = std::chrono::steady_clock::now();
                for (std::uint64_t i = 0; i < repetitions; ++i) checksum += calculator.compute_terminal(final, winners).total[i % finals.size()];
                seconds = std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
            }
            std::cout << "{\"id\":" << quoted(p[0]) << ",\"total\":"; array(result.total, finals.size());
            std::cout << ",\"baseline\":"; array(calculator.baseline().total, finals.size());
            std::cout << ",\"immediate_prizes\":"; array(result.immediate_prizes, finals.size());
            std::cout << ",\"immediate_bounties\":"; array(result.immediate_bounties, finals.size());
            std::cout << ",\"remaining_bounties\":"; array(result.remaining_bounties, finals.size());
            std::cout << ",\"future_equities\":"; array(result.future_equities, finals.size());
            const auto& stats = calculator.cache_stats();
            std::cout << ",\"cache_hits\":" << stats.hits << ",\"cache_misses\":" << stats.misses << ",\"cache_collisions\":" << stats.collisions;
            if (c.mode == Mode::MTT) std::cout << ",\"mtt_test_callback\":\"exact_combined_field_at_most_10\"";
            if (p[1] == "maskcache") { std::cout << ",\"alternate_total\":"; array(alternate, finals.size()); }
            if (p[1] == "bench") std::cout << ",\"repetitions\":" << repetitions << ",\"seconds\":" << seconds << ",\"checksum\":" << checksum;
            std::cout << "}\n";
        } catch (const std::exception& e) {
            std::cout << "{\"id\":" << quoted(p.empty() ? "" : p[0]) << ",\"error\":" << quoted(e.what()) << "}\n";
        }
    }
}
