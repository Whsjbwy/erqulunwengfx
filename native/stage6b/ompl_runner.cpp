// The tree algorithms are linked from unmodified official OMPL 2.0.2.
#include "model.hpp"

#include <nlohmann/json.hpp>
#include <ompl/base/OptimizationObjective.h>
#include <ompl/base/PlannerTerminationCondition.h>
#include <ompl/base/ProblemDefinition.h>
#include <ompl/base/ScopedState.h>
#include <ompl/base/goals/GoalSampleableRegion.h>
#include <ompl/base/objectives/ControlDurationObjective.h>
#include <ompl/base/spaces/RealVectorStateSpace.h>
#include <ompl/base/spaces/SO2StateSpace.h>
#include <ompl/config.h>
#include <ompl/control/PathControl.h>
#include <ompl/control/SimpleDirectedControlSampler.h>
#include <ompl/control/SpaceInformation.h>
#include <ompl/control/StatePropagator.h>
#include <ompl/control/planners/rrt/RRT.h>
#include <ompl/control/planners/sst/SST.h>
#include <ompl/control/spaces/RealVectorControlSpace.h>
#include <ompl/util/RandomNumbers.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>

namespace ob = ompl::base;
namespace oc = ompl::control;
namespace fs = std::filesystem;
using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;

namespace {

double elapsed(Clock::time_point start) {
    return std::chrono::duration<double>(Clock::now() - start).count();
}

Json state_json(const auv6b::State &state) {
    return Json::array({state.position[0], state.position[1], state.position[2], state.yaw,
                        state.pitch, state.speed});
}

auv6b::State state_from_json(const Json &value) {
    if (!value.is_array() || value.size() != 6) {
        throw std::invalid_argument(
            "A native state needs six stored values (fixed speed included)");
    }
    return {{{value.at(0).get<double>(), value.at(1).get<double>(), value.at(2).get<double>()}},
            value.at(3).get<double>(),
            value.at(4).get<double>(),
            value.at(5).get<double>()};
}

std::shared_ptr<const auv6b::Grid> read_grid(const Json &value) {
    auto grid = std::make_shared<auv6b::Grid>();
    grid->shape = value.at("shape").get<std::array<std::size_t, 3>>();
    grid->origin = value.at("origin").get<auv6b::Point>();
    grid->spacing = value.at("spacing").get<auv6b::Point>();
    std::size_t count = 1;
    for (const auto size : grid->shape) {
        if (size == 0 || count > 100000000 / size) {
            throw std::invalid_argument("Grid is empty or exceeds the Stage6B memory limit");
        }
        count *= size;
    }
    grid->occupancy.resize(count);
    std::ifstream stream(fs::u8path(value.at("data_file").get<std::string>()), std::ios::binary);
    if (!stream || !stream.read(reinterpret_cast<char *>(grid->occupancy.data()),
                                static_cast<std::streamsize>(count))) {
        throw std::runtime_error("Cannot read complete native occupancy grid");
    }
    if (stream.peek() != std::char_traits<char>::eof()) {
        throw std::invalid_argument("Occupancy file contains unexpected trailing bytes");
    }
    grid->validate();
    return grid;
}

auv6b::Geometry read_geometry(const Json &scene) {
    const double radius = scene.at("radius_m").get<double>();
    if (std::abs(radius - auv6b::effective_radius()) > 1e-12) {
        throw std::invalid_argument(
            "Effective radius differs from the frozen body-plus-margin model");
    }
    return {read_grid(scene.at("physical")), radius,
            scene.at("ceiling").is_null() ? nullptr : read_grid(scene.at("ceiling"))};
}

Json geometry_counters(const auv6b::Geometry &geometry) {
    return {{"query_calls", geometry.query_calls},
            {"box_distance_tests", geometry.box_distance_tests},
            {"segment_requests", geometry.segment_requests}};
}

auv6b::Control read_control(const Json &value) {
    return {value.at("yaw_rate_rad_s").get<double>(), value.at("pitch_rate_rad_s").get<double>()};
}

unsigned int interval_count(double duration) {
    if (!std::isfinite(duration) || duration <= 0.0 || duration > 100000.0) {
        throw std::invalid_argument("Control duration must be finite and positive");
    }
    const auto count = std::llround(duration / auv6b::time_step);
    if (count < 1 || std::abs(count * auv6b::time_step - duration) > 1e-12) {
        throw std::invalid_argument("Control duration must contain whole frozen steps");
    }
    return static_cast<unsigned int>(count);
}

auv6b::State read_state(const ob::State *value) {
    const auto *compound = value->as<ob::CompoundStateSpace::StateType>();
    const auto *position = compound->as<ob::RealVectorStateSpace::StateType>(0);
    return {{{position->values[0], position->values[1], position->values[2]}},
            compound->as<ob::SO2StateSpace::StateType>(1)->value,
            compound->as<ob::RealVectorStateSpace::StateType>(2)->values[0],
            1.0};
}

void write_state(ob::State *output, const auv6b::State &state) {
    auto *compound = output->as<ob::CompoundStateSpace::StateType>();
    auto *position = compound->as<ob::RealVectorStateSpace::StateType>(0);
    for (unsigned int axis = 0; axis < 3; ++axis)
        position->values[axis] = state.position[axis];
    compound->as<ob::SO2StateSpace::StateType>(1)->value = state.yaw;
    compound->as<ob::RealVectorStateSpace::StateType>(2)->values[0] = state.pitch;
}

auv6b::Control ompl_control(const oc::Control *value) {
    const auto *control = value->as<oc::RealVectorControlSpace::ControlType>();
    return {control->values[0], control->values[1]};
}

void write_control(oc::Control *output, const auv6b::Control &control) {
    auto *value = output->as<oc::RealVectorControlSpace::ControlType>();
    value->values[0] = control.yaw_rate;
    value->values[1] = control.pitch_rate;
}

double position_distance(const auv6b::Point &first, const auv6b::Point &second) {
    return std::hypot(std::hypot(first[0] - second[0], first[1] - second[1]), first[2] - second[2]);
}

struct PropagationAudit {
    std::uint64_t calls = 0;
    std::uint64_t intervals = 0;
    std::uint64_t accepted = 0;
    std::uint64_t state_checks = 0;
    std::map<std::string, std::uint64_t> rejected;
    Json first_rejection = Json::object();
};

class CertifiedPropagator final : public oc::StatePropagator {
  public:
    CertifiedPropagator(const oc::SpaceInformationPtr &information, const auv6b::Geometry &geometry,
                        PropagationAudit &audit)
        : oc::StatePropagator(information), geometry_(geometry), audit_(audit) {}

    bool canPropagateBackward() const override { return false; }

    void propagate(const ob::State *from, const oc::Control *input, double duration,
                   ob::State *to) const override {
        ++audit_.calls;
        auto state = read_state(from);
        const auto control = ompl_control(input);
        const auto count = interval_count(duration);
        for (unsigned int index = 0; index < count; ++index) {
            ++audit_.intervals;
            const auto result = auv6b::check_interval(state, control, auv6b::time_step, geometry_);
            if (!result.verdict.valid) {
                ++audit_.rejected[result.verdict.reason];
                if (!audit_.first_rejection.contains(result.verdict.reason)) {
                    audit_.first_rejection[result.verdict.reason] = {
                        {"start", state_json(state)}, {"candidate", state_json(result.following)}};
                }
                // A finite out-of-bounds sentinel must fail the explicit validity checker.
                auv6b::State invalid;
                invalid.position = geometry_.grid().origin;
                invalid.position[0] -= 1000.0;
                write_state(to, invalid);
                return;
            }
            ++audit_.accepted;
            state = result.following;
        }
        write_state(to, state);
    }

  private:
    const auv6b::Geometry &geometry_;
    PropagationAudit &audit_;
};

class PositionGoal final : public ob::GoalSampleableRegion {
  public:
    PositionGoal(const ob::SpaceInformationPtr &information, auv6b::Point goal)
        : ob::GoalSampleableRegion(information), goal_(goal) {
        threshold_ = 0.75;
    }

    double distanceGoal(const ob::State *state) const override {
        return position_distance(read_state(state).position, goal_);
    }
    bool isSatisfied(const ob::State *state) const override {
        return distanceGoal(state) <= threshold_;
    }
    bool isSatisfied(const ob::State *state, double *distance) const override {
        const double value = distanceGoal(state);
        if (distance)
            *distance = value;
        return value <= threshold_;
    }
    void sampleGoal(ob::State *output) const override {
        write_state(output, {goal_, rng_.uniformReal(-auv6b::pi, auv6b::pi),
                             rng_.uniformReal(-auv6b::pitch_limit, auv6b::pitch_limit), 1.0});
    }
    unsigned int maxSampleCount() const override {
        return std::numeric_limits<unsigned int>::max();
    }

  private:
    auv6b::Point goal_;
    mutable ompl::RNG rng_;
};

ob::StateSpacePtr make_state_space(const auv6b::Grid &grid) {
    auto positions = std::make_shared<ob::RealVectorStateSpace>(3);
    ob::RealVectorBounds bounds(3);
    for (unsigned int axis = 0; axis < 3; ++axis) {
        bounds.setLow(axis, grid.origin[axis]);
        bounds.setHigh(axis, grid.origin[axis] + grid.shape[axis] * grid.spacing[axis]);
    }
    positions->setBounds(bounds);
    auto pitch = std::make_shared<ob::RealVectorStateSpace>(1);
    ob::RealVectorBounds pitch_bounds(1);
    pitch_bounds.setLow(-auv6b::pitch_limit);
    pitch_bounds.setHigh(auv6b::pitch_limit);
    pitch->setBounds(pitch_bounds);
    auto state_space = std::make_shared<ob::CompoundStateSpace>();
    state_space->addSubspace(positions, 1.0);
    state_space->addSubspace(std::make_shared<ob::SO2StateSpace>(), 1.0);
    state_space->addSubspace(pitch, 1.0);
    state_space->lock();
    return state_space;
}

oc::SpaceInformationPtr make_information(const auv6b::Geometry &geometry, PropagationAudit &audit,
                                         unsigned int minimum_steps, unsigned int maximum_steps) {
    if (minimum_steps == 0 || maximum_steps < minimum_steps) {
        throw std::invalid_argument("Control duration bounds must be positive and ordered");
    }
    auto states = make_state_space(geometry.grid());
    auto controls = std::make_shared<oc::RealVectorControlSpace>(states, 2);
    ob::RealVectorBounds control_bounds(2);
    control_bounds.setLow(0, -auv6b::yaw_rate_limit);
    control_bounds.setHigh(0, auv6b::yaw_rate_limit);
    control_bounds.setLow(1, -auv6b::pitch_rate_limit);
    control_bounds.setHigh(1, auv6b::pitch_rate_limit);
    controls->setBounds(control_bounds);
    auto information = std::make_shared<oc::SpaceInformation>(states, controls);
    information->setStatePropagator(
        std::make_shared<CertifiedPropagator>(information, geometry, audit));
    // Own the state space only. Capturing information would create a cycle, and
    // capturing the local shared_ptr by reference would leave a dangling ref.
    information->setStateValidityChecker([states, &geometry, &audit](const ob::State *state) {
        ++audit.state_checks;
        const auto value = read_state(state);
        return states->satisfiesBounds(state) && auv6b::validate_state(value).valid &&
               geometry.segment(value.position, value.position).valid;
    });
    information->setPropagationStepSize(auv6b::time_step);
    information->setMinMaxControlDuration(minimum_steps, maximum_steps);
    information->setDirectedControlSamplerAllocator([](const oc::SpaceInformation *si) {
        return std::make_shared<oc::SimpleDirectedControlSampler>(si, 1);
    });
    information->setup();
    return information;
}

bool states_match(const auv6b::State &first, const auv6b::State &second) {
    return auv6b::validate_state(first).valid && auv6b::validate_state(second).valid &&
           position_distance(first.position, second.position) <= 1e-10 &&
           std::abs(auv6b::wrap_angle(first.yaw - second.yaw)) <= 1e-12 &&
           std::abs(first.pitch - second.pitch) <= 1e-12 && first.speed == second.speed;
}

struct AdapterStep {
    unsigned int accepted_steps;
    auv6b::State returned_state;
    bool returned_state_valid;
};

AdapterStep verify_adapter_step(const oc::SpaceInformationPtr &information,
                                const auv6b::State &state, const auv6b::Control &control,
                                const auv6b::IntervalResult &direct) {
    ob::ScopedState<> from(information->getStateSpace());
    ob::ScopedState<> to(information->getStateSpace());
    write_state(from.get(), state);
    const auto delete_control = [si = information.get()](oc::Control *value) {
        si->freeControl(value);
    };
    std::unique_ptr<oc::Control, decltype(delete_control)> native_control(
        information->allocControl(), delete_control);
    write_control(native_control.get(), control);
    const unsigned int accepted =
        information->propagateWhileValid(from.get(), native_control.get(), 1, to.get());
    const auto returned = read_state(to.get());
    const bool returned_valid = information->isValid(to.get());
    const unsigned int expected = direct.verdict.valid ? 1U : 0U;
    const auto &expected_state = direct.verdict.valid ? direct.following : state;
    if (accepted != expected || !returned_valid || !states_match(returned, expected_state)) {
        throw std::runtime_error(
            "OMPL adapter disagrees with the direct continuous interval certificate");
    }
    // After rejecting a step OMPL returns the valid source state. The accepted
    // step count, never isValid(to) alone, decides whether motion was accepted.
    return {accepted, returned, returned_valid};
}

Json supplied_replay(const Json &request) {
    const auto &scene = request.at("scenario");
    auto geometry = read_geometry(scene);
    auto state = state_from_json(scene.at("initial"));
    auto candidate = state;
    auto verdict = auv6b::validate_state(state);
    const bool rejected_before_mapping = !verdict.valid;
    if (verdict.valid)
        verdict = geometry.segment(state.position, state.position);
    PropagationAudit audit;
    const auto information = verdict.valid ? make_information(geometry, audit, 1, 1) : nullptr;
    Json states = Json::array({state_json(state)});
    Json trace = Json::array();
    Json control_probes = Json::array();
    for (const auto &segment : request.at("controls")) {
        if (!verdict.valid)
            break;
        const auto control = read_control(segment);
        const bool invalid_control = !std::isfinite(control.yaw_rate) ||
                                     !std::isfinite(control.pitch_rate) ||
                                     std::abs(control.yaw_rate) > auv6b::yaw_rate_limit ||
                                     std::abs(control.pitch_rate) > auv6b::pitch_rate_limit;
        if (invalid_control) {
            const auto direct = auv6b::check_interval(state, control, auv6b::time_step, geometry);
            const auto probe = verify_adapter_step(information, state, control, direct);
            verdict = direct.verdict;
            control_probes.push_back({{"reason", verdict.reason},
                                      {"yaw_rate_rad_s", control.yaw_rate},
                                      {"pitch_rate_rad_s", control.pitch_rate},
                                      {"adapter_accepted_steps", probe.accepted_steps},
                                      {"adapter_return_state_valid", probe.returned_state_valid}});
            break;
        }
        const auto count = interval_count(segment.at("duration_s").get<double>());
        for (unsigned int index = 0; index < count; ++index) {
            const auto result = auv6b::check_interval(state, control, auv6b::time_step, geometry);
            const auto adapter = verify_adapter_step(information, state, control, result);
            candidate = result.following;
            verdict = result.verdict;
            trace.push_back({{"start", state_json(state)},
                             {"following", state_json(candidate)},
                             {"accepted", verdict.valid},
                             {"reason", verdict.reason},
                             {"chord_error_bound_m", result.chord_error_bound_m},
                             {"adapter_checked", true},
                             {"adapter_accepted_steps", adapter.accepted_steps},
                             {"adapter_returned_state", state_json(adapter.returned_state)},
                             {"adapter_return_state_valid", adapter.returned_state_valid}});
            if (!verdict.valid)
                break;
            state = adapter.returned_state;
            states.push_back(state_json(state));
        }
    }
    return {{"mode", "replay"},
            {"ompl_version", OMPL_VERSION},
            {"reason", verdict.reason},
            {"states", states},
            {"trace", trace},
            {"last_accepted_state", state_json(state)},
            {"last_candidate_state", trace.empty() ? Json(nullptr) : state_json(candidate)},
            {"accepted_intervals", states.size() - 1},
            {"adapter_initial_rejected_before_mapping", rejected_before_mapping},
            {"adapter_probes_passed",
             audit.calls > 0 || (rejected_before_mapping && verdict.reason == "frozen_speed")},
            {"adapter_control_probes", control_probes},
            {"adapter_propagator_calls", audit.calls},
            {"adapter_interval_checks", audit.intervals},
            {"adapter_accepted_intervals", audit.accepted},
            {"adapter_state_validity_calls", audit.state_checks},
            {"adapter_rejection_counts", audit.rejected},
            {"counters", geometry_counters(geometry)}};
}

Json certify_solution(const Json &states, const Json &controls, const auv6b::Geometry &geometry,
                      const auv6b::Point &goal, const auv6b::State &declared_initial) {
    if (!states.is_array() || !controls.is_array() || states.size() != controls.size() + 1) {
        throw std::runtime_error("OMPL PathControl state/control cardinality mismatch");
    }
    auto state = state_from_json(states.at(0));
    std::uint64_t checked = 0;
    for (std::size_t index = 0; index < states.size(); ++index) {
        const auto node = state_from_json(states.at(index));
        auto verdict = auv6b::validate_state(node);
        if (verdict.valid)
            verdict = geometry.segment(node.position, node.position);
        if (!verdict.valid) {
            return {{"valid", false},
                    {"reason", "invalid_node_" + verdict.reason},
                    {"node_index", index},
                    {"checked_intervals", checked},
                    {"goal_reached", false}};
        }
    }
    if (!states_match(state, declared_initial)) {
        return {{"valid", false},
                {"reason", "initial_node_mismatch"},
                {"checked_intervals", checked},
                {"goal_reached", false}};
    }
    double maximum_position = 0.0;
    double maximum_angle = 0.0;
    for (std::size_t index = 0; index < controls.size(); ++index) {
        const auto input = read_control(controls.at(index));
        const auto count = interval_count(controls.at(index).at("duration_s").get<double>());
        for (unsigned int step = 0; step < count; ++step) {
            const auto result = auv6b::check_interval(state, input, auv6b::time_step, geometry);
            ++checked;
            if (!result.verdict.valid) {
                return {{"valid", false},
                        {"reason", result.verdict.reason},
                        {"checked_intervals", checked},
                        {"goal_reached", false}};
            }
            state = result.following;
        }
        const auto node = state_from_json(states.at(index + 1));
        maximum_position =
            std::max(maximum_position, position_distance(state.position, node.position));
        maximum_angle =
            std::max(maximum_angle, std::max(std::abs(auv6b::wrap_angle(state.yaw - node.yaw)),
                                             std::abs(state.pitch - node.pitch)));
    }
    const bool consistent = maximum_position <= 1e-10 && maximum_angle <= 1e-12;
    return {{"valid", consistent},
            {"reason", consistent ? "ok" : "node_mismatch"},
            {"checked_intervals", checked},
            {"maximum_node_position_error_m", maximum_position},
            {"maximum_node_angle_error_rad", maximum_angle},
            {"zero_control_path", controls.empty()},
            {"goal_reached", position_distance(state.position, goal) <= 0.75},
            {"final_goal_distance_m", position_distance(state.position, goal)}};
}

Json plan(const Json &request) {
    const auto beginning = Clock::now();
    const auto seed = request.at("seed").get<unsigned int>();
    if (seed == 0)
        throw std::invalid_argument(
            "OMPL seed zero aliases seed one; use registered positive seeds");
    ompl::RNG::setSeed(seed); // Before constructing any OMPL RNG instance.
    const auto &scene = request.at("scenario");
    auto geometry = read_geometry(scene);
    const auto initial = state_from_json(scene.at("initial"));
    const auto goal = scene.at("goal").get<auv6b::Point>();
    if (!std::all_of(goal.begin(), goal.end(), [](double value) { return std::isfinite(value); })) {
        throw std::invalid_argument("Native goal coordinates must be finite");
    }
    const auto initial_check = auv6b::validate_state(initial);
    if (!initial_check.valid)
        throw std::invalid_argument("Invalid native initial state: " + initial_check.reason);
    PropagationAudit audit;
    auto information =
        make_information(geometry, audit, request.at("propagation_min_steps").get<unsigned int>(),
                         request.at("propagation_max_steps").get<unsigned int>());
    ob::ScopedState<> start(information->getStateSpace());
    write_state(start.get(), initial);
    auto problem = std::make_shared<ob::ProblemDefinition>(information);
    problem->addStartState(start);
    problem->setGoal(std::make_shared<PositionGoal>(information, goal));
    auto objective = std::make_shared<ob::ControlDurationObjective>(information);
    // Official SST honors this threshold and returns its first finite exact path.
    objective->setCostThreshold(ob::Cost(std::numeric_limits<double>::infinity()));
    problem->setOptimizationObjective(objective);
    ob::PlannerPtr planner;
    const auto algorithm = request.at("algorithm").get<std::string>();
    if (algorithm == "sst") {
        auto sst = std::make_shared<oc::SST>(information);
        sst->setSelectionRadius(request.at("selection_radius").get<double>());
        sst->setPruningRadius(request.at("pruning_radius").get<double>());
        sst->setGoalBias(request.at("goal_bias").get<double>());
        planner = sst;
    } else if (algorithm == "rrt") {
        auto rrt = std::make_shared<oc::RRT>(information);
        rrt->setGoalBias(request.at("goal_bias").get<double>());
        rrt->setIntermediateStates(false);
        planner = rrt;
    } else {
        throw std::invalid_argument("Only official control SST and control RRT are permitted");
    }
    planner->setProblemDefinition(problem);
    planner->setup();
    const double search_budget = request.at("search_budget_s").get<double>();
    if (!(search_budget > 0.0 && search_budget <= 8.0))
        throw std::invalid_argument("Search cap exceeds preregistration");
    ob::PlannerTerminationCondition stop(
        [&] { return elapsed(beginning) >= search_budget || problem->hasExactSolution(); });
    const auto status = planner->solve(stop);
    const double returned_s = elapsed(beginning);
    Json output = {{"mode", "plan"},
                   {"ompl_version", OMPL_VERSION},
                   {"seed", seed},
                   {"algorithm", algorithm},
                   {"raw_status", status.asString()},
                   {"status", problem->hasExactSolution() ? "exact"
                              : problem->hasSolution()    ? "approximate"
                                                          : "no_solution"},
                   {"candidate_return_s", returned_s},
                   {"planning_counters", geometry_counters(geometry)},
                   {"propagator_calls", audit.calls},
                   {"propagated_intervals", audit.intervals},
                   {"accepted_intervals", audit.accepted},
                   {"state_validity_calls", audit.state_checks},
                   {"rejection_counts", audit.rejected},
                   {"first_rejections", audit.first_rejection},
                   {"states", Json::array()},
                   {"controls", Json::array()}};
    if (problem->hasSolution()) {
        const auto path = std::dynamic_pointer_cast<oc::PathControl>(problem->getSolutionPath());
        if (!path)
            throw std::runtime_error("OMPL did not return PathControl");
        for (std::size_t index = 0; index < path->getStateCount(); ++index) {
            output["states"].push_back(state_json(read_state(path->getState(index))));
        }
        for (std::size_t index = 0; index < path->getControlCount(); ++index) {
            const auto input = ompl_control(path->getControl(index));
            output["controls"].push_back({{"yaw_rate_rad_s", input.yaw_rate},
                                          {"pitch_rate_rad_s", input.pitch_rate},
                                          {"duration_s", path->getControlDuration(index)}});
        }
        const auto certificate_start = Clock::now();
        output["native_certificate"] =
            certify_solution(output["states"], output["controls"], geometry, goal, initial);
        output["native_certificate_s"] = elapsed(certificate_start);
        output["native_certificate_finish_s"] = elapsed(beginning);
    }
    output["counters_total"] = geometry_counters(geometry);
    output["total_native_s"] = elapsed(beginning);
    output["native_deadline_rejected"] =
        elapsed(beginning) > request.at("total_budget_s").get<double>();
    return output;
}

int run(const fs::path &input, const fs::path &output) {
    if (fs::exists(output))
        throw std::runtime_error("Refusing to overwrite a native output record");
    std::ifstream source(input);
    if (!source)
        throw std::runtime_error("Cannot open native request file");
    Json request;
    source >> request;
    const auto mode = request.at("mode").get<std::string>();
    const auto result = mode == "replay" ? supplied_replay(request)
                        : mode == "plan" ? plan(request)
                                         : throw std::invalid_argument("Unknown native operation");
    std::ofstream destination(output);
    if (!destination)
        throw std::runtime_error("Cannot create native response file");
    destination << result.dump(2);
    destination.close();
    if (!destination)
        throw std::runtime_error("Native response write failed");
    return 0;
}

} // namespace

#ifdef _WIN32
int wmain(int argc, wchar_t **argv) {
#else
int main(int argc, char **argv) {
#endif
    try {
        if (argc != 3)
            throw std::invalid_argument("Usage: auv6b_runner INPUT_JSON OUTPUT_JSON");
        return run(fs::path(argv[1]), fs::path(argv[2]));
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 2;
    }
}
