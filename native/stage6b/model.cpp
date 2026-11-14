#include "model.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>

namespace auv6b {
namespace {

bool finite_point(const Point &point) {
    return std::all_of(point.begin(), point.end(),
                       [](double value) { return std::isfinite(value); });
}

bool finite_state(const State &state) {
    return finite_point(state.position) && std::isfinite(state.yaw) && std::isfinite(state.pitch) &&
           std::isfinite(state.speed);
}

double sinc(double value) {
    if (std::abs(value) < 1e-5) {
        const double squared = value * value;
        return 1.0 - squared / 6.0 + squared * squared / 120.0;
    }
    return std::sin(value) / value;
}

double trig_integral(double angle, double rate, double duration, bool sine) {
    const double half = rate * duration / 2.0;
    const double middle = angle + half;
    return duration * sinc(half) * (sine ? std::sin(middle) : std::cos(middle));
}

std::size_t clipped_index(double value, std::size_t length) {
    if (std::isnan(value)) {
        throw std::invalid_argument("Cannot certify a NaN voxel index");
    }
    if (value <= 0.0) {
        return 0;
    }
    if (value >= static_cast<double>(length)) {
        return length;
    }
    return static_cast<std::size_t>(value);
}

bool same_frame(const Grid &first, const Grid &second) {
    return first.shape == second.shape && first.origin == second.origin &&
           first.spacing == second.spacing;
}

} // namespace

void Grid::validate() const {
    std::size_t count = 1;
    for (std::size_t axis = 0; axis < 3; ++axis) {
        if (shape[axis] == 0 || count > std::numeric_limits<std::size_t>::max() / shape[axis]) {
            throw std::invalid_argument("Voxel dimensions are empty or overflow");
        }
        count *= shape[axis];
        const double upper = origin[axis] + static_cast<double>(shape[axis]) * spacing[axis];
        if (!std::isfinite(origin[axis]) || !std::isfinite(spacing[axis]) || spacing[axis] <= 0.0 ||
            !std::isfinite(upper) || upper <= origin[axis]) {
            throw std::invalid_argument("Voxel frame must be finite and positive");
        }
    }
    if (occupancy.size() != count || std::any_of(occupancy.begin(), occupancy.end(),
                                                 [](std::uint8_t value) { return value > 1; })) {
        throw std::invalid_argument("Voxel storage does not match Boolean grid");
    }
}

std::size_t Grid::offset(std::size_t i, std::size_t j, std::size_t k) const {
    if (i >= shape[0] || j >= shape[1] || k >= shape[2]) {
        throw std::out_of_range("Voxel index lies outside grid");
    }
    return ((i * shape[1]) + j) * shape[2] + k;
}

double effective_radius() { return std::hypot(1.0, 0.2) + 0.25; }

double wrap_angle(double angle) {
    if (!std::isfinite(angle)) {
        throw std::invalid_argument("Cannot wrap a non-finite angle");
    }
    double result = std::fmod(angle + pi, 2.0 * pi);
    if (result < 0.0) {
        result += 2.0 * pi;
    }
    return result - pi;
}

State integrate(const State &state, const Control &control, double duration) {
    if (!finite_state(state) || !std::isfinite(control.yaw_rate) ||
        !std::isfinite(control.pitch_rate) || !std::isfinite(duration) || duration <= 0.0 ||
        state.speed <= 0.0) {
        throw std::invalid_argument("Integration needs finite inputs and positive speed/duration");
    }
    const double plus = state.yaw + state.pitch;
    const double minus = state.yaw - state.pitch;
    const double plus_rate = control.yaw_rate + control.pitch_rate;
    const double minus_rate = control.yaw_rate - control.pitch_rate;
    State following = state;
    following.position[0] += state.speed / 2.0 *
                             (trig_integral(plus, plus_rate, duration, false) +
                              trig_integral(minus, minus_rate, duration, false));
    following.position[1] += state.speed / 2.0 *
                             (trig_integral(plus, plus_rate, duration, true) +
                              trig_integral(minus, minus_rate, duration, true));
    following.position[2] +=
        state.speed * trig_integral(state.pitch, control.pitch_rate, duration, true);
    following.yaw = wrap_angle(state.yaw + control.yaw_rate * duration);
    following.pitch = state.pitch + control.pitch_rate * duration;
    if (!finite_state(following)) {
        throw std::overflow_error("Integration produced non-finite state");
    }
    return following;
}

double chord_error_bound(double speed, double yaw_rate, double pitch_rate, double duration) {
    if (!std::isfinite(speed) || !std::isfinite(yaw_rate) || !std::isfinite(pitch_rate) ||
        !std::isfinite(duration) || speed <= 0.0 || duration <= 0.0) {
        throw std::invalid_argument("Curve bound needs finite positive inputs");
    }
    const double bound = speed * std::hypot(yaw_rate, pitch_rate) * duration * duration / 8.0;
    if (!std::isfinite(bound)) {
        throw std::overflow_error("Curve bound overflow");
    }
    return bound;
}

Verdict validate_state(const State &state) {
    if (!finite_state(state)) {
        return {false, "invalid_state"};
    }
    if (state.speed != 1.0) {
        return {false, "frozen_speed"};
    }
    if (state.yaw < -pi || state.yaw >= pi) {
        return {false, "yaw_bound"};
    }
    if (std::abs(state.pitch) > pitch_limit + pitch_tolerance) {
        return {false, "pitch_bound"};
    }
    return {true, "ok"};
}

double segment_box_distance(const Point &start, const Point &end, const Point &lower,
                            const Point &upper) {
    if (!finite_point(start) || !finite_point(end) || !finite_point(lower) ||
        !finite_point(upper)) {
        throw std::invalid_argument("Segment/box coordinates must be finite");
    }
    Point delta{};
    std::vector<double> knots{0.0, 1.0};
    knots.reserve(8);
    for (std::size_t axis = 0; axis < 3; ++axis) {
        if (lower[axis] > upper[axis]) {
            throw std::invalid_argument("Box lower bound exceeds upper bound");
        }
        delta[axis] = end[axis] - start[axis];
        if (!std::isfinite(delta[axis])) {
            throw std::overflow_error("Segment displacement overflow");
        }
        if (delta[axis] != 0.0) {
            for (double face : {lower[axis], upper[axis]}) {
                const double crossing = (face - start[axis]) / delta[axis];
                if (crossing > 0.0 && crossing < 1.0) {
                    knots.push_back(crossing);
                }
            }
        }
    }
    std::sort(knots.begin(), knots.end());
    double smallest_squared = std::numeric_limits<double>::infinity();
    for (std::size_t interval = 0; interval + 1 < knots.size(); ++interval) {
        const double left = knots[interval];
        const double right = knots[interval + 1];
        const double middle = (left + right) / 2.0;
        double numerator = 0.0;
        double denominator = 0.0;
        for (std::size_t axis = 0; axis < 3; ++axis) {
            const double value = start[axis] + middle * delta[axis];
            double intercept = 0.0;
            double slope = 0.0;
            if (value < lower[axis]) {
                intercept = lower[axis] - start[axis];
                slope = -delta[axis];
            } else if (value > upper[axis]) {
                intercept = start[axis] - upper[axis];
                slope = delta[axis];
            }
            numerator -= intercept * slope;
            denominator += slope * slope;
        }
        if (!std::isfinite(numerator) || !std::isfinite(denominator)) {
            throw std::overflow_error("Cannot certify non-finite box minimum");
        }
        const double stationary = denominator > 0.0 ? numerator / denominator : 0.0;
        const double parameter = std::clamp(stationary, left, right);
        double squared = 0.0;
        for (std::size_t axis = 0; axis < 3; ++axis) {
            const double value = start[axis] + parameter * delta[axis];
            const double residual = std::max({lower[axis] - value, value - upper[axis], 0.0});
            squared += residual * residual;
        }
        if (!std::isfinite(squared)) {
            throw std::overflow_error("Cannot certify non-finite box distance");
        }
        smallest_squared = std::min(smallest_squared, squared);
    }
    return std::sqrt(smallest_squared);
}

Geometry::Geometry(std::shared_ptr<const Grid> physical, double radius,
                   std::shared_ptr<const Grid> ceiling)
    : physical_(std::move(physical)), ceiling_(std::move(ceiling)), radius_(radius) {
    if (!physical_ || !std::isfinite(radius_) || radius_ < 0.0) {
        throw std::invalid_argument("Geometry needs a grid and finite radius");
    }
    physical_->validate();
    if (ceiling_) {
        ceiling_->validate();
        if (!same_frame(*physical_, *ceiling_)) {
            throw std::invalid_argument("Physical and ceiling voxel frames differ");
        }
    }
}

double Geometry::distance(const Point &start, const Point &end, const Grid &grid,
                          double cutoff) const {
    std::array<std::size_t, 3> low{};
    std::array<std::size_t, 3> high{};
    for (std::size_t axis = 0; axis < 3; ++axis) {
        low[axis] = clipped_index(
            std::floor((std::min(start[axis], end[axis]) - cutoff - grid.origin[axis]) /
                       grid.spacing[axis]) -
                1.0,
            grid.shape[axis]);
        high[axis] = clipped_index(
            std::floor((std::max(start[axis], end[axis]) + cutoff - grid.origin[axis]) /
                       grid.spacing[axis]) +
                2.0,
            grid.shape[axis]);
        if (low[axis] >= high[axis]) {
            return cutoff;
        }
    }
    double result = cutoff;
    for (std::size_t i = low[0]; i < high[0]; ++i) {
        for (std::size_t j = low[1]; j < high[1]; ++j) {
            for (std::size_t k = low[2]; k < high[2]; ++k) {
                if (grid.occupancy[((i * grid.shape[1]) + j) * grid.shape[2] + k] == 0) {
                    continue;
                }
                const std::array<std::size_t, 3> index{i, j, k};
                Point lower{};
                Point upper{};
                for (std::size_t axis = 0; axis < 3; ++axis) {
                    lower[axis] =
                        grid.origin[axis] + static_cast<double>(index[axis]) * grid.spacing[axis];
                    upper[axis] = lower[axis] + grid.spacing[axis];
                }
                ++box_distance_tests;
                result = std::min(result, segment_box_distance(start, end, lower, upper));
            }
        }
    }
    return result;
}

Verdict Geometry::segment(const Point &start, const Point &end, double extra_radius) const {
    ++query_calls;
    ++segment_requests;
    if (!finite_point(start) || !finite_point(end)) {
        return {false, "invalid_coordinates"};
    }
    if (!std::isfinite(extra_radius) || extra_radius < 0.0 ||
        !std::isfinite(radius_ + extra_radius)) {
        throw std::invalid_argument("Extra radius must be finite and nonnegative");
    }
    const double radius = radius_ + extra_radius;
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const double lower = physical_->origin[axis];
        const double upper =
            lower + static_cast<double>(physical_->shape[axis]) * physical_->spacing[axis];
        if (start[axis] - lower < radius || end[axis] - lower < radius ||
            upper - start[axis] < radius || upper - end[axis] < radius) {
            return {false, "workspace_boundary"};
        }
    }
    if (distance(start, end, *physical_, radius + 2.0 * geometry_tolerance) <=
        radius + geometry_tolerance) {
        return {false, "physical_obstacle"};
    }
    if (ceiling_ && distance(start, end, *ceiling_, radius + 2.0 * geometry_tolerance) <=
                        radius + geometry_tolerance) {
        return {false, "mission_ceiling"};
    }
    return {true, "ok"};
}

double Geometry::clearance(const Point &start, const Point &end, double cap, bool mission) const {
    if (!finite_point(start) || !finite_point(end) || !std::isfinite(cap) || cap <= 0.0 ||
        !std::isfinite(radius_ + cap)) {
        throw std::invalid_argument("Clearance needs finite points and positive cap");
    }
    double result = radius_ + cap;
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const double lower = physical_->origin[axis];
        const double upper =
            lower + static_cast<double>(physical_->shape[axis]) * physical_->spacing[axis];
        result = std::min({result, start[axis] - lower, end[axis] - lower, upper - start[axis],
                           upper - end[axis]});
    }
    result = std::min(result, distance(start, end, *physical_, radius_ + cap));
    if (mission && ceiling_) {
        result = std::min(result, distance(start, end, *ceiling_, radius_ + cap));
    }
    return result - radius_;
}

IntervalResult check_interval(const State &state, const Control &control, double duration,
                              const Geometry &geometry) {
    IntervalResult result{state, validate_state(state), 0.0};
    if (!result.verdict.valid) {
        return result;
    }
    if (!std::isfinite(duration) || std::abs(duration - time_step) > 1e-12) {
        result.verdict = {false, "invalid_duration"};
        return result;
    }
    if (!std::isfinite(control.yaw_rate) || !std::isfinite(control.pitch_rate)) {
        result.verdict = {false, "invalid_control"};
        return result;
    }
    if (std::abs(control.yaw_rate) > yaw_rate_limit) {
        result.verdict = {false, "yaw_rate"};
        return result;
    }
    if (std::abs(control.pitch_rate) > pitch_rate_limit) {
        result.verdict = {false, "pitch_rate"};
        return result;
    }
    result.following = integrate(state, control, duration);
    result.chord_error_bound_m =
        chord_error_bound(state.speed, control.yaw_rate, control.pitch_rate, duration);
    if (std::abs(result.following.pitch) > pitch_limit + pitch_tolerance) {
        result.verdict = {false, "pitch_bound"};
        return result;
    }
    result.verdict =
        geometry.segment(state.position, result.following.position, result.chord_error_bound_m);
    return result;
}

} // namespace auv6b
