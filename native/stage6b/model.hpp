#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace auv6b {

using Point = std::array<double, 3>;

inline constexpr double pi = 3.141592653589793238462643383279502884;
inline constexpr double yaw_rate_limit = pi / 18.0;
inline constexpr double pitch_rate_limit = pi / 36.0;
inline constexpr double pitch_limit = pi / 9.0;
inline constexpr double time_step = 0.1;
inline constexpr double geometry_tolerance = 1e-9;
inline constexpr double pitch_tolerance = 1e-12;

struct State {
    Point position{};
    double yaw = 0.0;
    double pitch = 0.0;
    double speed = 1.0;
};

struct Control {
    double yaw_rate = 0.0;
    double pitch_rate = 0.0;
};

struct Grid {
    std::array<std::size_t, 3> shape{};
    Point origin{};
    Point spacing{0.5, 0.5, 0.5};
    std::vector<std::uint8_t> occupancy;

    // Occupancy uses NumPy C order: ((i * ny) + j) * nz + k.
    void validate() const;
    std::size_t offset(std::size_t i, std::size_t j, std::size_t k) const;
};

struct Verdict {
    bool valid = false;
    std::string reason;
};

struct IntervalResult {
    State following;
    Verdict verdict;
    double chord_error_bound_m = 0.0;
};

double effective_radius();
double wrap_angle(double angle);

// This mathematical integrator permits arbitrary positive durations. The frozen
// speed, rate, angle and time-step limits are enforced by check_interval.
State integrate(const State &state, const Control &control, double duration);
double chord_error_bound(double speed, double yaw_rate, double pitch_rate, double duration);
Verdict validate_state(const State &state);

// Exact segment-to-closed-box distance, using all piecewise-quadratic intervals.
double segment_box_distance(const Point &start, const Point &end, const Point &lower,
                            const Point &upper);

class Geometry {
  public:
    Geometry(std::shared_ptr<const Grid> physical, double radius = effective_radius(),
             std::shared_ptr<const Grid> ceiling = nullptr);

    Verdict segment(const Point &start, const Point &end, double extra_radius = 0.0) const;
    double clearance(const Point &start, const Point &end, double cap = 3.0,
                     bool mission = false) const;

    double radius() const noexcept { return radius_; }
    const Grid &grid() const noexcept { return *physical_; }
    const Grid *ceiling() const noexcept { return ceiling_.get(); }

    mutable std::uint64_t query_calls = 0;
    mutable std::uint64_t box_distance_tests = 0;
    mutable std::uint64_t segment_requests = 0;

  private:
    double distance(const Point &start, const Point &end, const Grid &grid, double cutoff) const;

    std::shared_ptr<const Grid> physical_;
    std::shared_ptr<const Grid> ceiling_;
    double radius_;
};

// Certifies one complete frozen 0.1-second interval. A rejected following state
// remains the candidate, not an accepted state; the caller must inspect verdict.
IntervalResult check_interval(const State &state, const Control &control, double duration,
                              const Geometry &geometry);

} // namespace auv6b
