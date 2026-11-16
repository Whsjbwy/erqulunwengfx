#include "identity.hpp"
#include <iostream>

int main() {
    try {
        auto grid = std::make_shared<auv6b::Grid>();
        grid->shape = {40, 40, 40};
        grid->origin = {0, 0, 0};
        grid->spacing = {0.5, 0.5, 0.5};
        grid->occupancy.resize(64000, 0);
        const auv6b::Geometry geometry(grid);
        const auv6b::State start{{5, 5, 5}, 0, 0, 1};
        auv6c::Counters counts, old_counts;
        const auto si = auv6dr::information(geometry, counts);
        for (const auto &planner :
             {ompl::base::PlannerPtr(std::make_shared<ompl::control::RRT>(si)),
              ompl::base::PlannerPtr(std::make_shared<ompl::control::SST>(si))}) {
            const auto identity = auv6ds::planner_identity(planner, si, start, geometry);
            if (!identity.at("planner_si_same_object").get<bool>())
                throw std::runtime_error("Planner identity assertion failed");
        }
        const auto old = auv6c::information(geometry, old_counts);
        bool rejected = false;
        try {
            auv6ds::planner_identity(std::make_shared<ompl::control::RRT>(old), old, start,
                                     geometry);
        } catch (const std::runtime_error &) {
            rejected = true;
        }
        if (!rejected)
            throw std::runtime_error("Identity test accepted the old narrower adapter");
        std::cout << "PASS official RRT/SST actual SI; old adapter rejected; no solve\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
