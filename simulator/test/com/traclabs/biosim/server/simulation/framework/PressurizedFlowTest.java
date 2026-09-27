package com.traclabs.biosim.server.simulation.framework;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class PressurizedFlowTest {

    @Test
    void noDriveMeansNoFlow() {
        assertEquals(0f, PressurizedFlow.molesThisTick(55f, 55f, 3.3f, 1f));
        assertEquals(0f, PressurizedFlow.molesThisTick(50f, 55f, 3.3f, 1f));
        assertEquals(0f, PressurizedFlow.molesThisTick(20000f, 55f, 0f, 1f));
    }

    @Test
    void nameplateCapsWhenTankIsHigh() {
        float moles = PressurizedFlow.molesThisTick(20000f, 55f, 3.3f, 1f);
        assertEquals(3.3f, moles, 1e-4f);
    }

    @Test
    void lowDeltaPUsesOrificeNotTheNameplate() {
        float dP = 10f;
        float moles = PressurizedFlow.molesThisTick(65f, 55f, 3.3f, 1f);
        assertEquals(PressurizedFlow.K_MOL_PER_HOUR_PER_KPA * dP, moles, 1e-4f);
    }
}
