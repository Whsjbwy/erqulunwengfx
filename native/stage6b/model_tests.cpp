#include "model.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using namespace auv6b;

void require(bool condition, const std::string &message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

void close(double actual, double expected, double tolerance, const std::string &message) {
    require(std::isfinite(actual) && std::abs(actual - expected) <= tolerance, message);
}

void throws_invalid(const std::function<void()> &operation, const std::string &message) {
    bool threw = false;
    try {
        operation();
    } catch (const std::invalid_argument &) {
        threw = true;
    }
    require(threw, message);
}

std::shared_ptr<Grid> empty_grid() {
    auto grid = std::make_shared<Grid>();
    grid->shape = {160, 160, 80};
    grid->occupancy.assign(160 * 160 * 80, 0);
    return grid;
}

std::shared_ptr<Grid> corner_grid() {
    auto grid = empty_grid();
    grid->occupancy[grid->offset(60, 40, 30)] = 1;
    return grid;
}

std::array<double, 5> rk4(const State &state, const Control &control, double duration) {
    using Value = std::array<double, 5>;
    Value current{state.position[0], state.position[1], state.position[2], state.yaw, state.pitch};
    const double step = duration / 1000.0;
    const auto derivative = [&](const Value &value) -> Value {
        return {state.speed * std::cos(value[4]) * std::cos(value[3]),
                state.speed * std::cos(value[4]) * std::sin(value[3]),
                state.speed * std::sin(value[4]), control.yaw_rate, control.pitch_rate};
    };
    const auto shifted = [](const Value &value, const Value &delta, double scale) -> Value {
        Value output{};
        for (std::size_t index = 0; index < value.size(); ++index) {
            output[index] = value[index] + scale * delta[index];
        }
        return output;
    };
    for (int iteration = 0; iteration < 1000; ++iteration) {
        const Value a = derivative(current);
        const Value b = derivative(shifted(current, a, step / 2.0));
        const Value c = derivative(shifted(current, b, step / 2.0));
        const Value d = derivative(shifted(current, c, step));
        for (std::size_t index = 0; index < current.size(); ++index) {
            current[index] += step * (a[index] + 2.0 * b[index] + 2.0 * c[index] + d[index]) / 6.0;
        }
    }
    return current;
}

void analytic_motion() {
    const State initial{{20.0, 20.0, 15.0}, 0.0, 0.0, 1.0};
    const State straight = integrate(initial, {}, 20.0);
    close(straight.position[0], 40.0, 1e-12, "Straight endpoint");
    for (double sign : {-1.0, 1.0}) {
        const State arc = integrate(initial, {sign * yaw_rate_limit, 0.0}, 9.0);
        close(arc.position[0], 20.0 + 1.0 / yaw_rate_limit, 1e-11, "Arc X endpoint");
        close(arc.position[1], 20.0 + sign / yaw_rate_limit, 1e-11, "Arc Y endpoint");
        close(arc.position[2], 15.0, 1e-12, "Arc Z endpoint");
        close(arc.yaw, sign * pi / 2.0, 1e-12, "Arc yaw endpoint");
    }
    const double climb_rate = pitch_rate_limit / 2.0;
    const State climb = integrate(initial, {0.0, climb_rate}, 4.0);
    close(climb.position[0], 20.0 + std::sin(climb_rate * 4.0) / climb_rate, 1e-11,
          "Climb analytic X");
    close(climb.position[2], 15.0 + (1.0 - std::cos(climb_rate * 4.0)) / climb_rate, 1e-11,
          "Climb analytic Z");
    const State pitched{{20.0, 20.0, 15.0}, 0.3, 0.05, 1.0};
    for (const Control control : {Control{pi / 36.0, pi / 90.0}, Control{pi / 90.0, pi / 90.0},
                                  Control{pi / 90.0, -pi / 90.0}}) {
        const State exact = integrate(pitched, control, 4.0);
        const auto independent = rk4(pitched, control, 4.0);
        for (std::size_t axis = 0; axis < 3; ++axis) {
            close(exact.position[axis], independent[axis], 1e-10, "Combined-rate independent RK4");
        }
    }
    close(wrap_angle(pi), -pi, 1e-12, "Pi canonicalization");
    close(wrap_angle(-3.0 * pi / 2.0), pi / 2.0, 1e-12, "Negative periodic yaw");
}

void strict_model_limits() {
    const Geometry geometry(empty_grid());
    const State initial{{20.0, 20.0, 15.0}, 0.0, 0.0, 1.0};
    require(check_interval(initial, {}, time_step, geometry).verdict.valid,
            "Straight interval accepted");
    require(
        check_interval(initial, {yaw_rate_limit + 1e-8, 0.0}, time_step, geometry).verdict.reason ==
            "yaw_rate",
        "Yaw limit is not clipped");
    require(check_interval(initial, {0.0, pitch_rate_limit + 1e-8}, time_step, geometry)
                    .verdict.reason == "pitch_rate",
            "Pitch-rate limit is not clipped");
    State state = initial;
    state.pitch = 19.0 * pi / 180.0;
    for (int index = 0; index < 2; ++index) {
        const auto accepted = check_interval(state, {0.0, pitch_rate_limit}, time_step, geometry);
        require(accepted.verdict.valid, "Pitch up to20degrees accepted");
        state = accepted.following;
    }
    const auto rejected = check_interval(state, {0.0, pitch_rate_limit}, time_step, geometry);
    require(rejected.verdict.reason == "pitch_bound", "Pitch angle rejected");
    require(rejected.following.pitch > pitch_limit,
            "Rejected pitch candidate retained without clipping");
    state.speed = 0.0;
    require(validate_state(state).reason == "frozen_speed",
            "Hover is not an additional supported speed");
    state = initial;
    state.yaw = pi;
    require(validate_state(state).reason == "yaw_bound", "SO2 canonical bound");
    state.yaw = -pi;
    require(validate_state(state).valid, "Equivalent minusPi is canonical");
    require(check_interval(initial, {}, 0.2, geometry).verdict.reason == "invalid_duration",
            "Multi-step input cannot bypass per-interval checks");
}

void closed_box_contact() {
    const Point lower{10.0, 10.0, 10.0};
    const Point upper{10.5, 10.5, 10.5};
    close(segment_box_distance({9.0, 10.25, 10.25}, {9.0, 10.25, 10.25}, lower, upper), 1.0, 1e-12,
          "Face distance");
    const double edge = 10.0 - 1.0 / std::sqrt(2.0);
    close(segment_box_distance({edge, edge, 10.25}, {edge, edge, 10.25}, lower, upper), 1.0, 1e-12,
          "Edge distance");
    const double corner = 10.0 - 1.0 / std::sqrt(3.0);
    close(segment_box_distance({corner, corner, corner}, {corner, corner, corner}, lower, upper),
          1.0, 1e-12, "Corner distance");
    close(segment_box_distance({9.0, 10.25, 10.25}, {12.0, 10.25, 10.25}, lower, upper), 0.0, 1e-12,
          "Crossed box interval");
    auto grid = empty_grid();
    grid->occupancy[grid->offset(20, 20, 20)] = 1;
    const Geometry geometry(grid, 1.0);
    for (const Point point :
         {Point{9.0, 10.25, 10.25}, Point{edge, edge, 10.25}, Point{corner, corner, corner}}) {
        require(geometry.segment(point, point).reason == "physical_obstacle",
                "Closed face, edge and corner contact rejected");
    }
    require(geometry.segment({8.99, 10.25, 10.25}, {8.99, 10.25, 10.25}).valid,
            "Strictly clear stationary sphere");
    require(geometry.segment({8.95, 10.25, 10.25}, {8.95, 10.25, 10.25}, 0.1).reason ==
                "physical_obstacle",
            "Curved-motion enclosure applied to radius");
    require(geometry.box_distance_tests > 0 && geometry.query_calls == 5 &&
                geometry.segment_requests == 5,
            "Geometry counters include actual checks");
}

void short_interval_midpoint_collision() {
    const Geometry geometry(corner_grid());
    const double radius = effective_radius();
    const double d = radius - 0.0004;
    const double offset = 0.05 / std::sqrt(2.0);
    const Point middle{30.0 - d / std::sqrt(2.0), 20.0 - d / std::sqrt(2.0), 15.25};
    const Point start{middle[0] - offset, middle[1] + offset, middle[2]};
    const Point end{middle[0] + offset, middle[1] - offset, middle[2]};
    require(geometry.segment(start, start).valid && geometry.segment(end, end).valid,
            "Both endpoint spheres are free");
    require(geometry.segment(middle, middle).reason == "physical_obstacle",
            "Analytic midpoint sphere intersects voxel corner");
    const State initial{start, -pi / 4.0, 0.0, 1.0};
    const auto result = check_interval(initial, {}, time_step, geometry);
    require(result.verdict.reason == "physical_obstacle",
            "Continuous0.1second interval cannot tunnel through corner");
    for (std::size_t axis = 0; axis < 3; ++axis) {
        close(result.following.position[axis], end[axis], 1e-12,
              "Counterexample uses frozen speed and duration");
    }
    require(geometry.clearance(start, start) > 0.0 && geometry.clearance(middle, middle) < 0.0,
            "Independent endpoint/midpoint signed gaps retained");
}

void mission_frame_and_boundary() {
    const auto physical = empty_grid();
    const auto ceiling = corner_grid();
    const Geometry geometry(physical, 1.0, ceiling);
    require(geometry.segment({29.0, 20.25, 15.25}, {29.0, 20.25, 15.25}).reason ==
                "mission_ceiling",
            "Mission voxels are separately rejected");
    require(geometry.clearance({29.0, 20.25, 15.25}, {29.0, 20.25, 15.25}, 3.0, false) > 0.0,
            "Physical clearance excludes virtual ceiling");
    close(geometry.clearance({29.0, 20.25, 15.25}, {29.0, 20.25, 15.25}, 3.0, true), 0.0, 1e-12,
          "Mission clearance includes ceiling");
    require(geometry.segment({1.0, 5.0, 5.0}, {1.0, 5.0, 5.0}).valid,
            "Workspace boundary follows frozen inclusive fit convention");
    require(geometry.segment({0.999, 5.0, 5.0}, {0.999, 5.0, 5.0}).reason == "workspace_boundary",
            "Sphere extending beyond workspace rejected");
    auto bad_frame = empty_grid();
    bad_frame->origin[0] = 0.5;
    throws_invalid([&] { Geometry invalid(physical, 1.0, bad_frame); },
                   "Mismatched frames cannot be silently combined");
}

void malformed_inputs_fail_closed() {
    const double nan = std::numeric_limits<double>::quiet_NaN();
    const double infinity = std::numeric_limits<double>::infinity();
    const Geometry geometry(empty_grid());
    const State initial{{20.0, 20.0, 15.0}, 0.0, 0.0, 1.0};
    State invalid = initial;
    invalid.position[0] = nan;
    require(validate_state(invalid).reason == "invalid_state", "NaN initial position rejected");
    invalid = initial;
    invalid.pitch = infinity;
    require(validate_state(invalid).reason == "invalid_state",
            "Infinite initial attitude rejected");
    require(check_interval(initial, {nan, 0.0}, time_step, geometry).verdict.reason ==
                "invalid_control",
            "NaN control rejected before geometry");
    require(check_interval(initial, {}, nan, geometry).verdict.reason == "invalid_duration",
            "NaN duration rejected");
    require(geometry.segment({nan, 2.0, 2.0}, {2.0, 2.0, 2.0}).reason == "invalid_coordinates",
            "NaN geometry cannot be accepted");
    throws_invalid([&] { geometry.segment(initial.position, initial.position, -0.1); },
                   "Negative enclosure radius rejected");
    throws_invalid([&] { geometry.clearance(initial.position, initial.position, 0.0); },
                   "Nonpositive clearance cap rejected");
    throws_invalid([&] { integrate(initial, {}, 0.0); }, "Zero integration duration rejected");
    auto bad_grid = empty_grid();
    bad_grid->occupancy.pop_back();
    throws_invalid([&] { Geometry invalid_geometry(bad_grid); },
                   "Truncated voxel storage rejected");
    auto nonbinary = empty_grid();
    nonbinary->occupancy.front() = 2;
    throws_invalid([&] { nonbinary->validate(); }, "Nonbinary voxel storage rejected");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string, std::function<void()>>> tests{
        {"analytic_motion", analytic_motion},
        {"strict_model_limits", strict_model_limits},
        {"closed_box_contact", closed_box_contact},
        {"short_interval_midpoint_collision", short_interval_midpoint_collision},
        {"mission_frame_and_boundary", mission_frame_and_boundary},
        {"malformed_inputs_fail_closed", malformed_inputs_fail_closed},
    };
    for (const auto &test : tests) {
        try {
            test.second();
        } catch (const std::exception &error) {
            std::cerr << "FAILED " << test.first << ": " << error.what() << '\n';
            return 1;
        }
        std::cout << "PASSED " << test.first << '\n';
    }
    std::cout << "6 native model test groups passed\n";
    return 0;
}
