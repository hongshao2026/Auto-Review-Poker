#include "../../native/hrc_mtt.hpp"
#include <chrono>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>

std::vector<double> vector(const std::string& text) {
    std::vector<double> values;
    std::istringstream stream(text);
    std::string token;
    while (std::getline(stream, token, ',')) values.push_back(std::stod(token));
    return values;
}

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    std::ifstream input(argv[1]);
    if (!input) return 3;
    std::cout << std::setprecision(17);
    std::string line;
    while (std::getline(input, line)) {
        if (line.empty()) continue;
        if (line.back() == '\r') line.pop_back();
        std::istringstream row(line);
        std::string id, local, prizes, outside;
        std::getline(row,id,'\t'); std::getline(row,local,'\t');
        std::getline(row,prizes,'\t'); std::getline(row,outside,'\t');
        const auto start = std::chrono::steady_clock::now();
        try {
            auto values = hrc_mtt::equities(vector(local),vector(prizes),vector(outside));
            auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();
            std::cout << "{\"id\":\"" << id << "\",\"values\":[";
            for (std::size_t i=0;i<values.size();++i) std::cout << (i ? "," : "") << values[i];
            std::cout << "],\"nanoseconds\":" << elapsed << "}\n";
        } catch (const std::exception& error) {
            std::cout << "{\"id\":\"" << id << "\",\"error\":\"" << error.what() << "\"}\n";
        }
    }
}
