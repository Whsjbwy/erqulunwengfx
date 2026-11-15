#include "adapter.hpp"
#include <iostream>
using namespace auv6c;
int main() {
    try {
        auto grid = std::make_shared<auv6b::Grid>();
        grid->shape = {40, 40, 40};
        grid->origin = {0, 0, 0};
        grid->spacing = {0.5, 0.5, 0.5};
        grid->occupancy.resize(64000);
        auv6b::Geometry g(grid);
        Counters counts;
        auto si = information(g, counts);
        ob::ScopedState<> a(si->getStateSpace()), b(si->getStateSpace());
        write_state(a.get(), {{5, 5, 5}, 0, 0, 1});
        write_state(b.get(), {{6, 5, 5}, 0.2, 0.1, 1});
        if (std::abs(si->distance(a.get(), b.get()) - 1.3) > 1e-12)
            throw std::runtime_error("Mixed metric mismatch");
        Goal goal(si, {5.75, 5, 5});
        if (!goal.isSatisfied(a.get()))
            throw std::runtime_error("Goal equality must be accepted");
        if (si->getStatePropagator()->canPropagateBackward())
            throw std::runtime_error("Backward propagation enabled");
        std::cout << "PASSED mixed_metric, goal_equality, forward_only\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
