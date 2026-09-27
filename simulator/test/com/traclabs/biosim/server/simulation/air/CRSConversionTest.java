package com.traclabs.biosim.server.simulation.air;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class CRSConversionTest {

    @Test
    void etaOfStoichMin() {
        assertEquals(0.85f, CRSConversion.convertedMoles(1f, 4f), 1e-5f);
        assertEquals(0.85f, CRSConversion.convertedMoles(2f, 4f), 1e-5f);
        assertEquals(0.425f, CRSConversion.convertedMoles(1f, 2f), 1e-5f);
    }

    @Test
    void starvesWithoutHydrogen() {
        assertEquals(0f, CRSConversion.convertedMoles(10f, 0f));
        assertEquals(0f, CRSConversion.convertedMoles(0f, 40f));
    }
}
