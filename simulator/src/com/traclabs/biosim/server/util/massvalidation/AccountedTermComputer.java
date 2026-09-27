package com.traclabs.biosim.server.util.massvalidation;

@FunctionalInterface
public interface AccountedTermComputer {
    double computeKg(int tick);
}
