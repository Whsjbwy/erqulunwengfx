#pragma once

#include "model.hpp"
#include <cmath>
#include <filesystem>
#include <fstream>
#include <limits>
#include <map>
#include <memory>
#include <nlohmann/json.hpp>
#include <ompl/base/ScopedState.h>
#include <ompl/base/goals/GoalSampleableRegion.h>
#include <ompl/base/spaces/RealVectorStateSpace.h>
#include <ompl/base/spaces/SO2StateSpace.h>
#include <ompl/control/PathControl.h>
#include <ompl/control/SimpleDirectedControlSampler.h>
#include <ompl/control/SpaceInformation.h>
#include <ompl/control/StatePropagator.h>
#include <ompl/control/spaces/RealVectorControlSpace.h>
#include <ompl/util/RandomNumbers.h>
#include <stdexcept>

namespace auv6c {
namespace ob = ompl::base;
namespace oc = ompl::control;
using Json = nlohmann::json;

inline double distance(const auv6b::Point &a, const auv6b::Point &b) {
    return std::hypot(std::hypot(a[0] - b[0], a[1] - b[1]), a[2] - b[2]);
}
inline Json pack(const auv6b::State &s) {
    return {s.position[0], s.position[1], s.position[2], s.yaw, s.pitch, s.speed};
}
inline auv6b::State unpack(const Json &v) {
    if (!v.is_array() || v.size() != 6)
        throw std::invalid_argument("Expected six stored values");
    return {{v.at(0), v.at(1), v.at(2)}, v.at(3), v.at(4), v.at(5)};
}
inline auv6b::State read_state(const ob::State *value) {
    const auto *s = value->as<ob::CompoundStateSpace::StateType>();
    const auto *p = s->as<ob::RealVectorStateSpace::StateType>(0);
    return {{p->values[0], p->values[1], p->values[2]},
            s->as<ob::SO2StateSpace::StateType>(1)->value,
            s->as<ob::RealVectorStateSpace::StateType>(2)->values[0],
            1.0};
}
inline void write_state(ob::State *value, const auv6b::State &state) {
    auto *s = value->as<ob::CompoundStateSpace::StateType>();
    auto *p = s->as<ob::RealVectorStateSpace::StateType>(0);
    for (unsigned i = 0; i < 3; ++i)
        p->values[i] = state.position[i];
    s->as<ob::SO2StateSpace::StateType>(1)->value = state.yaw;
    s->as<ob::RealVectorStateSpace::StateType>(2)->values[0] = state.pitch;
}
inline auv6b::Control read_control(const oc::Control *value) {
    const auto *u = value->as<oc::RealVectorControlSpace::ControlType>();
    return {u->values[0], u->values[1]};
}
inline unsigned steps(double duration) {
    if (!std::isfinite(duration) || duration <= 0)
        throw std::invalid_argument("Invalid duration");
    const auto count = std::llround(duration / 0.1);
    if (count < 1 || std::abs(count * 0.1 - duration) > 1e-12)
        throw std::invalid_argument("Duration must contain whole0.1s steps");
    return static_cast<unsigned>(count);
}
inline std::shared_ptr<const auv6b::Grid> grid(const Json &v) {
    auto g = std::make_shared<auv6b::Grid>();
    g->shape = v.at("shape").get<std::array<std::size_t, 3>>();
    g->origin = v.at("origin").get<auv6b::Point>();
    g->spacing = v.at("spacing").get<auv6b::Point>();
    std::size_t count = 1;
    for (auto n : g->shape) {
        if (!n || count > 100000000 / n)
            throw std::invalid_argument("Invalid grid size");
        count *= n;
    }
    g->occupancy.resize(count);
    std::ifstream file(std::filesystem::u8path(v.at("data_file").get<std::string>()),
                       std::ios::binary);
    if (!file.read(reinterpret_cast<char *>(g->occupancy.data()),
                   static_cast<std::streamsize>(count)) ||
        file.peek() != std::char_traits<char>::eof())
        throw std::runtime_error("Invalid occupancy file");
    g->validate();
    return g;
}
inline auv6b::Geometry geometry(const Json &scene) {
    const double r = scene.at("radius_m");
    if (!std::isfinite(r) || std::abs(r - auv6b::effective_radius()) > 1e-12)
        throw std::invalid_argument("Frozen radius mismatch");
    return {grid(scene.at("physical")), r,
            scene.at("ceiling").is_null() ? nullptr : grid(scene.at("ceiling"))};
}

struct Counters {
    std::uint64_t calls = 0, intervals = 0, accepted = 0, state_checks = 0;
    std::map<std::string, std::uint64_t> rejections;
};

class Propagator final : public oc::StatePropagator {
  public:
    Propagator(const oc::SpaceInformationPtr &si, const auv6b::Geometry &g, Counters &counts)
        : oc::StatePropagator(si), geometry_(g), counts_(counts) {}
    bool canPropagateBackward() const override { return false; }
    void propagate(const ob::State *from, const oc::Control *input, double duration,
                   ob::State *to) const override {
        ++counts_.calls;
        auto state = read_state(from);
        const auto control = read_control(input);
        for (unsigned i = 0; i < steps(duration); ++i) {
            ++counts_.intervals;
            const auto next = auv6b::check_interval(state, control, 0.1, geometry_);
            if (!next.verdict.valid) {
                ++counts_.rejections[next.verdict.reason];
                auv6b::State sentinel;
                sentinel.position = geometry_.grid().origin;
                sentinel.position[0] -= 1000;
                write_state(to, sentinel);
                return;
            }
            ++counts_.accepted;
            state = next.following;
        }
        write_state(to, state);
    }

  private:
    const auv6b::Geometry &geometry_;
    Counters &counts_;
};

inline oc::SpaceInformationPtr information(const auv6b::Geometry &g, Counters &counts,
                                           unsigned minimum = 1, unsigned maximum = 50) {
    auto position = std::make_shared<ob::RealVectorStateSpace>(3);
    ob::RealVectorBounds bounds(3);
    for (unsigned i = 0; i < 3; ++i) {
        bounds.setLow(i, g.grid().origin[i]);
        bounds.setHigh(i, g.grid().origin[i] + g.grid().shape[i] * g.grid().spacing[i]);
    }
    position->setBounds(bounds);
    auto pitch = std::make_shared<ob::RealVectorStateSpace>(1);
    ob::RealVectorBounds pb(1);
    pb.setLow(-auv6b::pitch_limit);
    pb.setHigh(auv6b::pitch_limit);
    pitch->setBounds(pb);
    auto space = std::make_shared<ob::CompoundStateSpace>();
    space->addSubspace(position, 1);
    space->addSubspace(std::make_shared<ob::SO2StateSpace>(), 1);
    space->addSubspace(pitch, 1);
    space->lock();
    auto controls = std::make_shared<oc::RealVectorControlSpace>(space, 2);
    ob::RealVectorBounds cb(2);
    cb.setLow(0, -auv6b::yaw_rate_limit);
    cb.setHigh(0, auv6b::yaw_rate_limit);
    cb.setLow(1, -auv6b::pitch_rate_limit);
    cb.setHigh(1, auv6b::pitch_rate_limit);
    controls->setBounds(cb);
    auto si = std::make_shared<oc::SpaceInformation>(space, controls);
    si->setStatePropagator(std::make_shared<Propagator>(si, g, counts));
    si->setStateValidityChecker([space, &g, &counts](const ob::State *s) {
        ++counts.state_checks;
        const auto state = read_state(s);
        return space->satisfiesBounds(s) && auv6b::validate_state(state).valid &&
               g.segment(state.position, state.position).valid;
    });
    si->setPropagationStepSize(0.1);
    si->setMinMaxControlDuration(minimum, maximum);
    si->setDirectedControlSamplerAllocator([](const oc::SpaceInformation *value) {
        return std::make_shared<oc::SimpleDirectedControlSampler>(value, 1);
    });
    si->setup();
    return si;
}

class Goal final : public ob::GoalSampleableRegion {
  public:
    Goal(const ob::SpaceInformationPtr &si, auv6b::Point goal)
        : ob::GoalSampleableRegion(si), goal_(goal) {
        threshold_ = 0.75;
    }
    double distanceGoal(const ob::State *s) const override {
        return distance(read_state(s).position, goal_);
    }
    bool isSatisfied(const ob::State *s) const override { return distanceGoal(s) <= threshold_; }
    bool isSatisfied(const ob::State *s, double *d) const override {
        const auto v = distanceGoal(s);
        if (d)
            *d = v;
        return v <= threshold_;
    }
    void sampleGoal(ob::State *s) const override {
        write_state(s, {goal_, rng_.uniformReal(-auv6b::pi, auv6b::pi),
                        rng_.uniformReal(-auv6b::pitch_limit, auv6b::pitch_limit), 1});
    }
    unsigned maxSampleCount() const override { return std::numeric_limits<unsigned>::max(); }

  private:
    auv6b::Point goal_;
    mutable ompl::RNG rng_;
};

inline Json export_path(const oc::PathControl &path) {
    Json states = Json::array(), controls = Json::array();
    for (std::size_t i = 0; i < path.getStateCount(); ++i)
        states.push_back(pack(read_state(path.getState(i))));
    for (std::size_t i = 0; i < path.getControlCount(); ++i) {
        const auto u = read_control(path.getControl(i));
        controls.push_back({{"yaw_rate_rad_s", u.yaw_rate},
                            {"pitch_rate_rad_s", u.pitch_rate},
                            {"duration_s", path.getControlDuration(i)}});
    }
    return {{"states", states}, {"controls", controls}};
}

inline Json certify(const Json &path, const auv6b::State &initial, const auv6b::Point &goal,
                    const auv6b::Geometry &g) {
    const auto &states = path.at("states");
    const auto &controls = path.at("controls");
    if (states.size() != controls.size() + 1)
        throw std::runtime_error("Broken PathControl cardinality");
    auto state = initial;
    std::uint64_t intervals = 0;
    double cost = 0;
    for (std::size_t i = 0; i < states.size(); ++i) {
        const auto node = unpack(states.at(i));
        if (!auv6b::validate_state(node).valid || distance(node.position, state.position) > 1e-10 ||
            std::abs(auv6b::wrap_angle(node.yaw - state.yaw)) > 1e-12 ||
            std::abs(node.pitch - state.pitch) > 1e-12 ||
            !g.segment(state.position, state.position).valid)
            throw std::runtime_error("Returned node failed native certificate");
        if (i == controls.size())
            break;
        const auto &u = controls.at(i);
        const double duration = u.at("duration_s");
        cost += duration;
        for (unsigned k = 0; k < steps(duration); ++k) {
            const auto next = auv6b::check_interval(
                state, {u.at("yaw_rate_rad_s"), u.at("pitch_rate_rad_s")}, 0.1, g);
            if (!next.verdict.valid)
                throw std::runtime_error("Returned control interval failed native certificate");
            ++intervals;
            state = next.following;
        }
    }
    return {{"valid", true},
            {"goal_reached", distance(state.position, goal) <= 0.75},
            {"cost", cost},
            {"checked_intervals", intervals}};
}
} // namespace auv6c
