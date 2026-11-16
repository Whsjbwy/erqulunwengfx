// Instrumentation only: official OMPL tree algorithms and frozen6B model are reused.
#include "adapter.hpp"
#include <chrono>
#include <iostream>
#include <ompl/base/PlannerTerminationCondition.h>
#include <ompl/base/ProblemDefinition.h>
#include <ompl/base/objectives/ControlDurationObjective.h>
#include <ompl/config.h>
#include <ompl/control/planners/rrt/RRT.h>
#include <ompl/control/planners/sst/SST.h>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

// PSAPI requires the Win32 declarations above.
#include <psapi.h>
#endif

using namespace auv6c;
using Clock = std::chrono::steady_clock;
static double elapsed(Clock::time_point start) {
    return std::chrono::duration<double>(Clock::now() - start).count();
}

class ObservedSST final : public oc::SST {
  public:
    explicit ObservedSST(const oc::SpaceInformationPtr &si) : oc::SST(si) {}
    // Exposes a copy of the incumbent only. No tree method is overridden.
    Json incumbent() const {
        if (prevSolution_.empty())
            throw std::runtime_error("Empty official incumbent");
        Json states = Json::array(), controls = Json::array();
        for (std::size_t i = prevSolution_.size(); i-- > 0;) {
            states.push_back(pack(read_state(prevSolution_[i])));
            if (i > 0) {
                const auto u = read_control(prevSolutionControls_[i - 1]);
                controls.push_back({{"yaw_rate_rad_s", u.yaw_rate},
                                    {"pitch_rate_rad_s", u.pitch_rate},
                                    {"duration_s", prevSolutionSteps_[i - 1] * 0.1}});
            }
        }
        return {{"states", states}, {"controls", controls}};
    }
};

static Json peak_memory() {
#ifdef _WIN32
    PROCESS_MEMORY_COUNTERS counters{};
    if (!GetProcessMemoryInfo(GetCurrentProcess(), &counters, sizeof(counters)))
        throw std::runtime_error("Memory query failed");
    return counters.PeakWorkingSetSize;
#else
    return nullptr;
#endif
}

static Json accept(const Json &request) {
    auto g = geometry(request.at("scenario"));
    auto state = unpack(request.at("scenario").at("initial"));
    auto verdict = auv6b::validate_state(state);
    if (verdict.valid)
        verdict = g.segment(state.position, state.position);
    Counters counts;
    auto si = verdict.valid ? information(g, counts) : nullptr;
    Json trace = Json::array();
    auv6b::State candidate = state;
    for (const auto &segment : request.at("controls")) {
        if (!verdict.valid)
            break;
        const auv6b::Control control{segment.at("yaw_rate_rad_s"), segment.at("pitch_rate_rad_s")};
        for (unsigned k = 0; k < steps(segment.at("duration_s")); ++k) {
            const auto direct = auv6b::check_interval(state, control, 0.1, g);
            candidate = direct.following;
            ob::ScopedState<> from(si->getStateSpace()), to(si->getStateSpace());
            write_state(from.get(), state);
            auto *input = si->allocControl();
            input->as<oc::RealVectorControlSpace::ControlType>()->values[0] = control.yaw_rate;
            input->as<oc::RealVectorControlSpace::ControlType>()->values[1] = control.pitch_rate;
            const auto accepted = si->propagateWhileValid(from.get(), input, 1, to.get());
            si->freeControl(input);
            const auto expected = direct.verdict.valid ? candidate : state;
            const auto returned = read_state(to.get());
            if (accepted != unsigned(direct.verdict.valid) || !si->isValid(to.get()) ||
                distance(expected.position, returned.position) > 1e-10 ||
                std::abs(auv6b::wrap_angle(expected.yaw - returned.yaw)) > 1e-12 ||
                std::abs(expected.pitch - returned.pitch) > 1e-12)
                throw std::runtime_error(
                    "Actual OMPL acceptance differs from the full interval oracle");
            verdict = direct.verdict;
            if (!verdict.valid)
                break;
            state = candidate;
            trace.push_back(pack(state));
        }
    }
    return {{"ompl_version", OMPL_VERSION},       {"reason", verdict.reason},
            {"accepted_intervals", trace.size()}, {"states", trace},
            {"final_candidate", pack(candidate)}, {"propagator_calls", counts.calls}};
}

static Json plan(const Json &request) {
    const auto beginning = Clock::now();
    const unsigned seed = request.at("seed");
    if (!seed)
        throw std::invalid_argument("Zero seed is not permitted");
    ompl::RNG::setSeed(seed);
    const auto &scene = request.at("scenario");
    auto g = geometry(scene);
    const auto initial = unpack(scene.at("initial"));
    if (!auv6b::validate_state(initial).valid)
        throw std::invalid_argument("Invalid initial state before mapping");
    const auto goal = scene.at("goal").get<auv6b::Point>();
    for (auto x : goal)
        if (!std::isfinite(x))
            throw std::invalid_argument("Nonfinite goal");
    Counters counts;
    auto si = information(g, counts, request.at("propagation_min_steps"),
                          request.at("propagation_max_steps"));
    auto problem = std::make_shared<ob::ProblemDefinition>(si);
    ob::ScopedState<> start(si->getStateSpace());
    write_state(start.get(), initial);
    problem->addStartState(start);
    problem->setGoal(std::make_shared<Goal>(si, goal));
    const bool anytime = request.at("search_mode") == "anytime";
    auto objective = std::make_shared<ob::ControlDurationObjective>(si);
    objective->setCostThreshold(ob::Cost(anytime ? 0.0 : std::numeric_limits<double>::infinity()));
    problem->setOptimizationObjective(objective);
    const std::string algorithm = request.at("algorithm");
    ob::PlannerPtr planner;
    Json events = Json::array(), first = nullptr;
    auto observe = [&](const Json &path) {
        const auto certificate = certify(path, initial, goal, g);
        if (!certificate.at("goal_reached").get<bool>())
            throw std::runtime_error("Exact incumbent misses goal");
        events.push_back({{"native_certificate_finish_s", elapsed(beginning)},
                          {"cost", certificate.at("cost")},
                          {"certificate_intervals", certificate.at("checked_intervals")}});
        if (first.is_null())
            first = path;
    };
    if (algorithm == "sst") {
        auto sst = std::make_shared<ObservedSST>(si);
        sst->setSelectionRadius(request.at("selection_radius"));
        sst->setPruningRadius(request.at("pruning_radius"));
        sst->setGoalBias(request.at("goal_bias"));
        problem->setIntermediateSolutionCallback(
            [&](const ob::Planner *p, const std::vector<const ob::State *> &, ob::Cost cost) {
                const auto *observed = dynamic_cast<const ObservedSST *>(p);
                if (!observed)
                    throw std::runtime_error("Callback is not the official SST observer");
                const auto path = observed->incumbent();
                observe(path);
                if (std::abs(events.back().at("cost").get<double>() - cost.value()) > 1e-9)
                    throw std::runtime_error("Cost does not match returned controls");
            });
        planner = sst;
    } else if (algorithm == "rrt" && !anytime) {
        auto rrt = std::make_shared<oc::RRT>(si);
        rrt->setGoalBias(request.at("goal_bias"));
        rrt->setIntermediateStates(false);
        planner = rrt;
    } else
        throw std::invalid_argument("Unsupported preregistered condition");
    planner->setProblemDefinition(problem);
    planner->setup();
    const double cap = request.at("search_budget_s");
    if (!(cap > 0 && cap <= 8))
        throw std::invalid_argument("Unregistered search budget");
    const auto status =
        planner->solve(ob::PlannerTerminationCondition([&] { return elapsed(beginning) >= cap; }));
    Json output = {{"ompl_version", OMPL_VERSION},
                   {"status", problem->hasExactSolution() ? "exact"
                              : problem->hasSolution()    ? "approximate"
                                                          : "no_solution"},
                   {"raw_status", status.asString()},
                   {"states", Json::array()},
                   {"controls", Json::array()},
                   {"candidate_return_s", elapsed(beginning)}};
    if (problem->hasSolution()) {
        const auto path = std::dynamic_pointer_cast<oc::PathControl>(problem->getSolutionPath());
        if (!path)
            throw std::runtime_error("Official planner did not return PathControl");
        auto data = export_path(*path);
        output["states"] = data.at("states");
        output["controls"] = data.at("controls");
        output["native_certificate"] = certify(data, initial, goal, g);
        if (problem->hasExactSolution() && first.is_null())
            observe(data);
        output["first_path_is_final"] = !first.is_null() && first == data;
        output["first_path"] = first.is_null() || first == data ? Json(nullptr) : first;
    }
    output["improvement_events"] = events;
    output["peak_native_rss_bytes"] = peak_memory();
    output["propagated_intervals"] = counts.intervals;
    output["propagator_calls"] = counts.calls;
    output["state_validity_calls"] = counts.state_checks;
    output["rejection_counts"] = counts.rejections;
    output["collision_queries"] = g.query_calls;
    output["box_distance_tests"] = g.box_distance_tests;
    output["native_certificate_finish_s"] = elapsed(beginning);
    output["seed"] = seed;
    output["algorithm"] = algorithm;
    return output;
}

static int run(const std::filesystem::path &input, const std::filesystem::path &output) {
    try {
        std::ifstream file(input);
        Json request;
        file >> request;
        const std::string mode = request.at("mode");
        if (mode != "plan" && mode != "replay")
            throw std::invalid_argument("Unknown native request mode");
        const Json result = mode == "plan" ? plan(request) : accept(request);
        std::ofstream target(output);
        target << result.dump(2);
        if (!target)
            throw std::runtime_error("Cannot write native result");
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
#ifdef _WIN32
int wmain(int argc, wchar_t **argv) {
    if (argc != 3)
        return 2;
    return run(argv[1], argv[2]);
}
#else
int main(int argc, char **argv) {
    if (argc != 3)
        return 2;
    return run(argv[1], argv[2]);
}
#endif
