#include "probe.hpp"
#include <iostream>

using namespace auv6dr;

static void require(bool condition, const char *message) {
    if (!condition)
        throw std::runtime_error(message);
}

int main() {
    try {
        auto grid = std::make_shared<auv6b::Grid>();
        grid->shape = {40, 40, 40};
        grid->origin = {0, 0, 0};
        grid->spacing = {0.5, 0.5, 0.5};
        grid->occupancy.resize(64000, 0);
        const auv6b::Geometry geometry(grid);
        auv6c::Counters counts, old_counts;
        const auto si = auv6dr::information(geometry, counts);
        const auto old = auv6c::information(geometry, old_counts);
        const double envelope = auv6b::pitch_limit + auv6b::pitch_tolerance;
        for (double sign : {-1.0, 1.0}) {
            auv6b::State state{{5, 5, 5}, 0, sign * (auv6b::pitch_limit + 5e-13), 1};
            require(state_status(si, state, geometry)["si_is_valid"].get<bool>(),
                    "Existing model tolerance was not admitted");
            require(!state_status(old, state, geometry)["si_is_valid"].get<bool>(),
                    "Original diagnostic unexpectedly became valid");
            state.pitch = sign * envelope;
            const auto at = interval_status(si, state, {0, 0}, geometry);
            require(at["agreement"].get<bool>() && at["accepted_steps"] == 1,
                    "Exact signed model envelope rejected");
            const double next = std::nextafter(envelope, std::numeric_limits<double>::infinity());
            const auto outside =
                interval_status(si, state, {0, sign * (next - envelope) / 0.1}, geometry);
            require(outside["agreement"].get<bool>() && outside["accepted_steps"] == 0,
                    "One ULP outside model envelope was accepted");
            require(outside["candidate"]["satisfies_bounds"].get<bool>() &&
                        !outside["candidate"]["si_is_valid"].get<bool>(),
                    "Final model filter did not block the OMPL epsilon band");
            state.pitch = 0;
            for (const auto &control :
                 {auv6b::Control{sign * (auv6b::yaw_rate_limit + 1e-9), 0},
                  auv6b::Control{0, sign * (auv6b::pitch_rate_limit + 1e-9)}}) {
                const auto rejected = interval_status(si, state, control, geometry);
                require(rejected["agreement"].get<bool>() && rejected["accepted_steps"] == 0,
                        "Illegal signed control was accepted");
            }
        }
        auv6b::State state{{5, 5, 5}, 0, 0, 1};
        const auto invalid =
            interval_status(si, state, {std::numeric_limits<double>::quiet_NaN(), 0}, geometry);
        require(invalid["agreement"].get<bool>() && invalid["accepted_steps"] == 0,
                "Nonfinite control was accepted");
        state.speed = 0;
        require(!state_status(si, state, geometry)["mapping_performed"].get<bool>(),
                "Invalid fixed speed was silently mapped to one");
        const auto metadata = policy(si);
        require(metadata["state_dimension"] == 5 && metadata["minimum_steps"] == 1 &&
                    metadata["maximum_steps"] == 50 && metadata["step_s"] == 0.1 &&
                    !metadata["backward_propagation"].get<bool>(),
                "Frozen SI settings changed");
        require(dynamic_cast<auv6c::Propagator *>(si->getStatePropagator().get()) != nullptr,
                "Frozen propagator was replaced");
        ob::ScopedState<> a(si->getStateSpace()), b(si->getStateSpace());
        auv6c::write_state(a.get(), {{5, 5, 5}, 0, 0, 1});
        auv6c::write_state(b.get(), {{6, 5, 5}, 0.2, 0.1, 1});
        require(std::abs(si->distance(a.get(), b.get()) - 1.3) <= 1e-12, "Mixed metric changed");
        auv6c::Goal goal(si, {5.75, 5, 5});
        require(goal.isSatisfied(a.get()), "Frozen goal equality changed");
        std::cout << "PASSED signed envelope, epsilon filter, illegal controls, fixed speed, "
                     "frozen SI/goal\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
