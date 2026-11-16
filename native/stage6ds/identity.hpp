#pragma once

#include "../stage6dr/probe.hpp"
#include <ompl/base/Planner.h>
#include <ompl/control/planners/rrt/RRT.h>
#include <ompl/control/planners/sst/SST.h>

namespace auv6ds {
using Json = nlohmann::json;
namespace ob = ompl::base;
namespace oc = ompl::control;
inline constexpr const char *binary_id = "auv_obstacle_baselines_v1";

// Inspect the SI held by the actual official planner, not a neighbouring probe.
inline Json planner_identity(const ob::PlannerPtr &planner, const oc::SpaceInformationPtr &si,
                             const auv6b::State &initial, const auv6b::Geometry &geometry) {
    if (planner->getSpaceInformation().get() != si.get())
        throw std::runtime_error("Planner holds a different SpaceInformation");
    const auto policy = auv6dr::policy(si);
    const double envelope = auv6b::pitch_limit + auv6b::pitch_tolerance;
    if (policy.at("declared_pitch_low_rad") != -envelope ||
        policy.at("declared_pitch_high_rad") != envelope)
        throw std::runtime_error("Actual planner did not receive repaired pitch bounds");
    Json signed_probes = Json::array();
    for (const double sign : {-1.0, 1.0}) {
        auto state = initial;
        state.pitch = sign * (auv6b::pitch_limit + 5e-13);
        auto inside = auv6dr::state_status(si, state, geometry);
        state.pitch = sign * std::nextafter(envelope, std::numeric_limits<double>::infinity());
        auto outside = auv6dr::state_status(si, state, geometry);
        if (!inside.at("si_is_valid").get<bool>() || outside.at("si_is_valid").get<bool>())
            throw std::runtime_error("Actual planner pitch contract failed signed probes");
        signed_probes.push_back({{"inside", inside}, {"outside", outside}});
    }
    const auto *rrt = dynamic_cast<const oc::RRT *>(planner.get());
    const auto *sst = dynamic_cast<const oc::SST *>(planner.get());
    if (!rrt && !sst)
        throw std::runtime_error("Planner is not an official control RRT/SST instance");
    Json settings = {{"goal_bias", rrt ? rrt->getGoalBias() : sst->getGoalBias()}};
    if (sst) {
        settings["selection_radius"] = sst->getSelectionRadius();
        settings["pruning_radius"] = sst->getPruningRadius();
    }
    return {{"binary_id", binary_id},
            {"adapter", policy},
            {"planner_si_same_object", true},
            {"official_class", rrt ? "ompl::control::RRT" : "ompl::control::SST"},
            {"actual_settings", settings},
            {"signed_probes", signed_probes}};
}
} // namespace auv6ds
