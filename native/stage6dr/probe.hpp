#pragma once

#include "adapter.hpp"
#include <algorithm>
#include <memory>

namespace auv6dr {

inline Json number(double value) {
    if (std::isfinite(value))
        return value;
    return std::isnan(value) ? Json("nan") : Json(value > 0 ? "+inf" : "-inf");
}

inline double decode_number(const Json &value) {
    if (value.is_number())
        return value.get<double>();
    if (value == "nan")
        return std::numeric_limits<double>::quiet_NaN();
    if (value == "+inf")
        return std::numeric_limits<double>::infinity();
    if (value == "-inf")
        return -std::numeric_limits<double>::infinity();
    throw std::invalid_argument("Expected a number or an explicit nonfinite test tag");
}

inline auv6b::State decode_state(const Json &values) {
    if (!values.is_array() || values.size() != 6)
        throw std::invalid_argument("Expected five states plus the fixed speed parameter");
    return {{decode_number(values[0]), decode_number(values[1]), decode_number(values[2])},
            decode_number(values[3]),
            decode_number(values[4]),
            decode_number(values[5])};
}

inline Json state_values(const auv6b::State &state) {
    return {number(state.position[0]), number(state.position[1]), number(state.position[2]),
            number(state.yaw),         number(state.pitch),       number(state.speed)};
}

inline Json state_status(const oc::SpaceInformationPtr &si, const auv6b::State &state,
                         const auv6b::Geometry &geometry) {
    const auto model = auv6b::validate_state(state);
    const auto point = geometry.segment(state.position, state.position);
    Json result = {{"state", state_values(state)},    {"model_valid", model.valid},
                   {"model_reason", model.reason},    {"geometry_valid", point.valid},
                   {"geometry_reason", point.reason}, {"mapping_performed", false},
                   {"satisfies_bounds", nullptr},     {"si_is_valid", nullptr}};
    // Invalid fixed speed cannot be represented by the five-dimensional space.
    if (!std::isfinite(state.speed) || state.speed != 1.0)
        return result;
    ob::ScopedState<> mapped(si->getStateSpace());
    auv6c::write_state(mapped.get(), state);
    result["mapping_performed"] = true;
    result["satisfies_bounds"] = si->getStateSpace()->satisfiesBounds(mapped.get());
    result["si_is_valid"] = si->isValid(mapped.get());
    return result;
}

inline Json interval_status(const oc::SpaceInformationPtr &si, const auv6b::State &state,
                            const auv6b::Control &input, const auv6b::Geometry &geometry) {
    const auto direct = auv6b::check_interval(state, input, 0.1, geometry);
    const auto source = state_status(si, state, geometry);
    const auto candidate = state_status(si, direct.following, geometry);
    Json result = {{"source", source},
                   {"candidate", candidate},
                   {"control", {number(input.yaw_rate), number(input.pitch_rate)}},
                   {"frozen_interval_valid", direct.verdict.valid},
                   {"frozen_interval_reason", direct.verdict.reason},
                   {"expected_steps", unsigned(direct.verdict.valid)},
                   {"propagation_invoked", false},
                   {"accepted_steps", nullptr},
                   {"returned_state", nullptr},
                   {"returned_si_valid", nullptr},
                   {"position_error_m", nullptr},
                   {"angle_or_speed_error", nullptr},
                   {"agreement", false}};
    if (!source["mapping_performed"].get<bool>() || !source["si_is_valid"].get<bool>()) {
        result["agreement"] =
            !source["model_valid"].get<bool>() || !source["geometry_valid"].get<bool>();
        return result;
    }
    ob::ScopedState<> from(si->getStateSpace()), to(si->getStateSpace());
    auv6c::write_state(from.get(), state);
    const auto release = [si](oc::Control *control) { si->freeControl(control); };
    std::unique_ptr<oc::Control, decltype(release)> control(si->allocControl(), release);
    auto *values = control->as<oc::RealVectorControlSpace::ControlType>();
    values->values[0] = input.yaw_rate;
    values->values[1] = input.pitch_rate;
    const unsigned accepted = si->propagateWhileValid(from.get(), control.get(), 1, to.get());
    const auto actual = auv6c::read_state(to.get());
    const auto expected = direct.verdict.valid ? direct.following : state;
    const double position_error = auv6c::distance(expected.position, actual.position);
    const double angle_error = std::max({std::abs(auv6b::wrap_angle(expected.yaw - actual.yaw)),
                                         std::abs(expected.pitch - actual.pitch),
                                         std::abs(expected.speed - actual.speed)});
    const bool returned_valid = si->isValid(to.get());
    result["propagation_invoked"] = true;
    result["accepted_steps"] = accepted;
    result["returned_state"] = state_values(actual);
    result["returned_si_valid"] = returned_valid;
    result["position_error_m"] = position_error;
    result["angle_or_speed_error"] = angle_error;
    result["agreement"] = accepted == unsigned(direct.verdict.valid) && returned_valid &&
                          position_error <= 1e-10 && angle_error <= 1e-12;
    return result;
}
} // namespace auv6dr
