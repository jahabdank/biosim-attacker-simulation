package com.traclabs.biosim.server.simulation.environment;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class DehumidifierDewpointTest {

    @Test
    void onePercentAtExplorationPressureIsBelowCoil() {
        float td = Dehumidifier.dewPointC(23f, 0.01f, 55f);
        assertTrue(td < Dehumidifier.T_HX_C, "dewpointC=" + td);
        assertEquals(0f, Dehumidifier.molesToCondense(23f, 0.01f, 400f, 55f, 1f / 60f,
                Dehumidifier.UA_W_PER_K, 1f));
    }

    @Test
    void highHumidityCondenses() {
        float removed = Dehumidifier.molesToCondense(23f, 0.04f, 400f, 55f, 1f,
                Dehumidifier.UA_W_PER_K, 1f);
        assertTrue(removed > 0f, "removed=" + removed);
    }

    @Test
    void saturationAtCoilIsIdentityDewpoint() {
        float es = Dehumidifier.saturationVaporPressureHpa(10f);
        float y = es / (55f * 10f);
        assertEquals(10f, Dehumidifier.dewPointC(23f, y, 55f), 0.3f);
    }
}
