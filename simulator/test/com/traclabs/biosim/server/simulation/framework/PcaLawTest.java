package com.traclabs.biosim.server.simulation.framework;

import com.traclabs.biosim.server.simulation.environment.SimEnvironment;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PcaLawTest {

    @Test
    void inhibitIsOff() {
        SimEnvironment env = new SimEnvironment(0, "Cabin", 18000f, 55f, 0.33f, 0f, 0.001f, 0.01f, 0.659f);
        assertFalse(PcaLaw.shouldInjectOxygen(env, 0f));
        assertFalse(PcaLaw.shouldInjectNitrogen(env, 0f));
    }

    @Test
    void holdsNearSetpoint() {
        SimEnvironment env = new SimEnvironment(0, "Cabin", 18000f, 55f, 0.33f, 0f, 0.001f, 0.01f, 0.659f);
        // ppO2 ≈ 0.33*55 = 18.15 kPa
        assertFalse(PcaLaw.shouldInjectOxygen(env, 18f));
        assertFalse(PcaLaw.shouldInjectNitrogen(env, 55f));
    }
}
