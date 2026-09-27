package com.traclabs.biosim.server.simulation.environment;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SimEnvironmentThermalTest {

    @Test
    void addedHeatMovesTemperature() {
        SimEnvironment env = new SimEnvironment(0, "Cabin", 18000f, 55f, 0.33f, 0f, 0.001f, 0.01f, 0.659f);
        env.setOneNodeThermal(true);
        env.setTickLength(1f / 60f);
        float t0 = env.getTemperature();
        env.addHeatJoules(50000f);
        env.tick();
        assertTrue(env.getTemperature() > t0, "T0=" + t0 + " T1=" + env.getTemperature());
    }

    @Test
    void frozenDefaultIgnoresAddedHeat() {
        SimEnvironment env = new SimEnvironment(0, "Cabin", 18000f, 55f, 0.33f, 0f, 0.001f, 0.01f, 0.659f);
        env.setTickLength(1f / 60f);
        env.addHeatJoules(50000f);
        env.tick();
        assertEquals(23f, env.getTemperature(), 0.01f);
    }
}
