// Deterministic interface acceptance only: no planner construction or solve entry.
#include "probe.hpp"
#include <iostream>
#include <ompl/config.h>

using namespace auv6dr;

static Json evaluate(const Json &request) {
    const std::string mode = request.at("mode");
    if (mode != "inspect" && mode != "replay")
        throw std::invalid_argument("Only deterministic inspect/replay modes are permitted");
    const auto geometry = auv6c::geometry(request.at("scenario"));
    auto state = decode_state(request.at("scenario").at("initial"));
    auv6c::Counters counts;
    const auto si = auv6dr::information(geometry, counts);
    const auto initial = state_status(si, state, geometry);
    Json result = {{"adapter", policy(si)},
                   {"ompl_version", OMPL_VERSION},
                   {"mode", mode},
                   {"initial", initial},
                   {"trace", Json::array()},
                   {"reason", initial["model_reason"]},
                   {"accepted_intervals", 0},
                   {"agreement", true},
                   {"new_planning_searches", 0}};
    const bool expected_source =
        initial["model_valid"].get<bool>() && initial["geometry_valid"].get<bool>();
    const bool admitted =
        initial["mapping_performed"].get<bool>() && initial["si_is_valid"].get<bool>();
    result["agreement"] = admitted == expected_source;
    if (initial["model_valid"].get<bool>())
        result["reason"] = initial["geometry_reason"];
    if (admitted != expected_source)
        result["reason"] = "interface_disagreement";
    if (mode == "replay" && admitted) {
        std::size_t index = 0;
        unsigned accepted_total = 0;
        bool stop = false;
        for (const auto &segment : request.at("controls")) {
            if (stop)
                break;
            const auv6b::Control control{decode_number(segment.at("yaw_rate_rad_s")),
                                         decode_number(segment.at("pitch_rate_rad_s"))};
            for (unsigned step = 0; step < auv6c::steps(segment.at("duration_s")); ++step) {
                auto row = interval_status(si, state, control, geometry);
                row["interval_index"] = index;
                row["time_start_s"] = index * 0.1;
                row["time_end_s"] = (index + 1) * 0.1;
                result["trace"].push_back(row);
                ++index;
                if (!row["agreement"].get<bool>()) {
                    result["agreement"] = false;
                    result["reason"] = "interface_disagreement";
                    stop = true;
                    break;
                }
                if (row["accepted_steps"].is_null() || row["accepted_steps"] != 1) {
                    result["reason"] = row["frozen_interval_reason"];
                    stop = true;
                    break;
                }
                ++accepted_total;
                state = decode_state(row["returned_state"]);
            }
        }
        result["accepted_intervals"] = accepted_total;
    }
    result["last_accepted_state"] = state_values(state);
    result["propagator_calls"] = counts.calls;
    result["state_validity_calls"] = counts.state_checks;
    result["rejection_counts"] = counts.rejections;
    return result;
}

static int run(const std::filesystem::path &input, const std::filesystem::path &output) {
    try {
        std::ifstream source(input);
        Json request;
        source >> request;
        const auto result = evaluate(request);
        std::ofstream target(output);
        target << result.dump(2) << '\n';
        if (!target)
            throw std::runtime_error("Cannot write acceptance evidence");
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}

#ifdef _WIN32
int wmain(int argc, wchar_t **argv) { return argc == 3 ? run(argv[1], argv[2]) : 2; }
#else
int main(int argc, char **argv) { return argc == 3 ? run(argv[1], argv[2]) : 2; }
#endif
