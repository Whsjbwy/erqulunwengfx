// Read-only diagnosis: reuse the exact frozen propagator and official SI.
#include "adapter.hpp"
#include <iostream>

using namespace auv6c;

static Json inspect(const auv6b::State &state, const auv6b::Control &control,
                    const auv6b::Geometry &g) {
    Counters counts;
    auto si = information(g, counts);
    const auto direct = auv6b::check_interval(state, control, 0.1, g);
    ob::ScopedState<> from(si->getStateSpace()), to(si->getStateSpace()),
        candidate(si->getStateSpace());
    write_state(from.get(), state);
    write_state(candidate.get(), direct.following);
    auto *input = si->allocControl();
    input->as<oc::RealVectorControlSpace::ControlType>()->values[0] = control.yaw_rate;
    input->as<oc::RealVectorControlSpace::ControlType>()->values[1] = control.pitch_rate;
    const auto accepted = si->propagateWhileValid(from.get(), input, 1, to.get());
    si->freeControl(input);
    const bool bounds = si->getStateSpace()->satisfiesBounds(candidate.get());
    const auto compound = si->getStateSpace()->as<ob::CompoundStateSpace>();
    const auto *parts = candidate.get()->as<ob::CompoundStateSpace::StateType>();
    return {{"direct_interval_valid", direct.verdict.valid},
            {"direct_reason", direct.verdict.reason},
            {"actual_accepted_steps", accepted},
            {"expected_accepted_steps", unsigned(direct.verdict.valid)},
            {"mismatch_detected", accepted != unsigned(direct.verdict.valid)},
            {"candidate_space_bounds", bounds},
            {"position_subspace_bounds", compound->getSubspace(0)->satisfiesBounds(
                                             parts->as<ob::RealVectorStateSpace::StateType>(0))},
            {"yaw_subspace_bounds",
             compound->getSubspace(1)->satisfiesBounds(parts->as<ob::SO2StateSpace::StateType>(1))},
            {"pitch_subspace_bounds", compound->getSubspace(2)->satisfiesBounds(
                                          parts->as<ob::RealVectorStateSpace::StateType>(2))},
            {"candidate_si_valid", si->isValid(candidate.get())},
            {"candidate_model_valid", auv6b::validate_state(direct.following).valid},
            {"candidate_point_geometry_valid",
             g.segment(direct.following.position, direct.following.position).valid},
            {"source_state", pack(state)},
            {"candidate_state", pack(direct.following)},
            {"returned_state", pack(read_state(to.get()))},
            {"pitch_limit_rad", auv6b::pitch_limit},
            {"candidate_pitch_minus_limit_rad", direct.following.pitch - auv6b::pitch_limit},
            {"model_pitch_tolerance_rad", auv6b::pitch_tolerance},
            {"machine_epsilon", std::numeric_limits<double>::epsilon()},
            {"continuous_geometry_relaxed", false}};
}

static Json diagnose(const Json &request) {
    const auto g = geometry(request.at("scenario"));
    auto state = unpack(request.at("scenario").at("initial"));
    std::uint64_t interval = 0;
    for (const auto &segment : request.at("controls")) {
        const auv6b::Control control{segment.at("yaw_rate_rad_s"), segment.at("pitch_rate_rad_s")};
        for (unsigned step = 0; step < steps(segment.at("duration_s")); ++step) {
            auto result = inspect(state, control, g);
            result["interval_index"] = interval;
            result["time_start_s"] = interval * 0.1;
            if (result.at("mismatch_detected").get<bool>() ||
                !result.at("direct_interval_valid").get<bool>())
                return result;
            state = auv6b::integrate(state, control, 0.1);
            ++interval;
        }
    }
    return {{"mismatch_detected", false}, {"checked_intervals", interval}};
}

static int run(const std::filesystem::path &input, const std::filesystem::path &output) {
    try {
        if (input == "--self-test") {
            auto grid = std::make_shared<auv6b::Grid>();
            grid->shape = {40, 40, 40};
            grid->origin = {0, 0, 0};
            grid->spacing = {0.5, 0.5, 0.5};
            grid->occupancy.resize(40 * 40 * 40, 0);
            const auv6b::Geometry g(grid, auv6b::effective_radius(), nullptr);
            const auv6b::State state{{5, 5, 5}, 0, auv6b::pitch_limit + 5e-13, 1};
            const auto result = inspect(state, {0, 0}, g);
            if (!result.at("mismatch_detected").get<bool>() ||
                !result.at("candidate_model_valid").get<bool>() ||
                result.at("candidate_space_bounds").get<bool>())
                throw std::runtime_error("Documented pitch-predicate gap was not detected");
            std::cout << "Detected frozen pitch contract gap; admission remains BLOCKED\n";
            return 0;
        }
        std::ifstream source(input);
        Json request;
        source >> request;
        std::ofstream target(output);
        target << diagnose(request).dump(2) << '\n';
        if (!target)
            throw std::runtime_error("Cannot write diagnostic evidence");
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}

#ifdef _WIN32
int wmain(int argc, wchar_t **argv) {
    if (argc == 2)
        return run(argv[1], "");
    return argc == 3 ? run(argv[1], argv[2]) : 2;
}
#else
int main(int argc, char **argv) {
    if (argc == 2)
        return run(argv[1], "");
    return argc == 3 ? run(argv[1], argv[2]) : 2;
}
#endif
