#pragma once

#include "../stage6c/adapter.hpp"

namespace auv6dr {
namespace ob = ompl::base;
namespace oc = ompl::control;
using Json = nlohmann::json;
inline constexpr const char *adapter_id = "auv_pitch_contract_v1";

// Reuse every frozen component. Only align the declared numerical pitch domain.
inline oc::SpaceInformationPtr information(const auv6b::Geometry &geometry, auv6c::Counters &counts,
                                           unsigned minimum = 1, unsigned maximum = 50) {
    auto si = auv6c::information(geometry, counts, minimum, maximum);
    auto *space = si->getStateSpace()->as<ob::CompoundStateSpace>();
    auto *pitch = space->getSubspace(2)->as<ob::RealVectorStateSpace>();
    const double envelope = auv6b::pitch_limit + auv6b::pitch_tolerance;
    ob::RealVectorBounds bounds(1);
    bounds.setLow(-envelope);
    bounds.setHigh(envelope);
    pitch->setBounds(bounds);
    si->setup(); // Refresh bounds-dependent extent and setup metadata.
    return si;
}

inline Json policy(const oc::SpaceInformationPtr &si) {
    const auto *space = si->getStateSpace()->as<ob::CompoundStateSpace>();
    const auto &pitch = space->getSubspace(2)->as<ob::RealVectorStateSpace>()->getBounds();
    const auto &position = space->getSubspace(0)->as<ob::RealVectorStateSpace>()->getBounds();
    const auto &control = si->getControlSpace()->as<oc::RealVectorControlSpace>()->getBounds();
    return {
        {"adapter_id", adapter_id},
        {"nominal_pitch_limit_rad", auv6b::pitch_limit},
        {"frozen_pitch_tolerance_rad", auv6b::pitch_tolerance},
        {"declared_pitch_low_rad", pitch.low[0]},
        {"declared_pitch_high_rad", pitch.high[0]},
        {"state_dimension", space->getDimension()},
        {"position_low", position.low},
        {"position_high", position.high},
        {"control_low", control.low},
        {"control_high", control.high},
        {"subspace_weights",
         {space->getSubspaceWeight(0), space->getSubspaceWeight(1), space->getSubspaceWeight(2)}},
        {"step_s", si->getPropagationStepSize()},
        {"minimum_steps", si->getMinControlDuration()},
        {"maximum_steps", si->getMaxControlDuration()},
        {"backward_propagation", si->getStatePropagator()->canPropagateBackward()},
        {"final_model_filter", "unchanged auv6b::validate_state"},
        {"propagator", "unchanged auv6c::Propagator"}};
}
} // namespace auv6dr
