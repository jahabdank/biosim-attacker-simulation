package com.traclabs.biosim.integration;

import com.traclabs.biosim.server.framework.BioDriver;
import com.traclabs.biosim.server.framework.BiosimInitializer;
import com.traclabs.biosim.server.simulation.air.CO2Store;
import com.traclabs.biosim.server.simulation.air.O2Store;
import com.traclabs.biosim.server.simulation.environment.EnvironmentStore;
import com.traclabs.biosim.server.simulation.environment.SimEnvironment;
import com.traclabs.biosim.server.simulation.framework.Store;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

public class MassConservationE2ETest {

    private static final int SIM_ID = 42;

    private static final int N_TICKS = 20;

    private static final double ABS_TOLERANCE_MOLES = 1.0e-3;

    private static final String TEST_CONFIG_XML =
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>" +
                    "<biosim xmlns=\"http://www.traclabs.com/biosim\"" +
                    "        xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\"" +
                    "        xsi:schemaLocation=\"http://www.traclabs.com/biosim schema/BiosimInitSchema.xsd\">" +
                    "    <Globals tickLength=\"1\" runTillN=\"0\" runTillCrewDeath=\"false\"" +
                    "             runTillPlantDeath=\"false\" startPaused=\"true\"" +
                    "             exitWhenFinished=\"false\" isLooping=\"false\"" +
                    "             driverStutterLength=\"0\"/>" +
                    "    <SimBioModules>" +
                    "        <air>" +
                    "            <O2Store moduleName=\"O2Store\" level=\"1000.0\" capacity=\"100000.0\"/>" +
                    "            <CO2Store moduleName=\"CO2Store\" level=\"0.0\" capacity=\"100000.0\"/>" +
                    "        </air>" +
                    "        <environment>" +
                    "            <SimEnvironment moduleName=\"SimEnvironment\" initialVolume=\"100000\"/>" +
                    "        </environment>" +
                    "        <framework>" +
                    "            <Accumulator moduleName=\"O2_Injector\">" +
                    "                <O2Consumer inputs=\"O2Store\"" +
                    "                            desiredFlowRates=\"5.0\" maxFlowRates=\"5.0\"/>" +
                    "                <O2Producer outputs=\"SimEnvironment\"" +
                    "                            desiredFlowRates=\"5.0\" maxFlowRates=\"5.0\"/>" +
                    "            </Accumulator>" +
                    "            <Accumulator moduleName=\"CO2_Scrubber\">" +
                    "                <CO2Consumer inputs=\"SimEnvironment\"" +
                    "                             desiredFlowRates=\"3.0\" maxFlowRates=\"3.0\"/>" +
                    "                <CO2Producer outputs=\"CO2Store\"" +
                    "                             desiredFlowRates=\"3.0\" maxFlowRates=\"3.0\"/>" +
                    "            </Accumulator>" +
                    "        </framework>" +
                    "    </SimBioModules>" +
                    "</biosim>";

    @AfterEach
    void tearDown() {
        BiosimInitializer.deleteInstance(SIM_ID);
    }

    @Test
    void totalMassIsConservedEveryTick() {
        BiosimInitializer.deleteInstance(SIM_ID);

        BiosimInitializer initializer = BiosimInitializer.getInstance(SIM_ID);
        initializer.parseXmlConfiguration(TEST_CONFIG_XML);

        BioDriver bioDriver = initializer.getBioDriver();
        assertNotNull(bioDriver, "BioDriver was not configured");
        bioDriver.reset();

        O2Store o2Store = (O2Store) BiosimInitializer.getModule(SIM_ID, "O2Store");
        CO2Store co2Store = (CO2Store) BiosimInitializer.getModule(SIM_ID, "CO2Store");
        SimEnvironment env = (SimEnvironment) BiosimInitializer.getModule(SIM_ID, "SimEnvironment");
        assertNotNull(o2Store, "O2Store missing after parse");
        assertNotNull(co2Store, "CO2Store missing after parse");
        assertNotNull(env, "SimEnvironment missing after parse");

        double initialTotalMoles = computeTotalMoles(o2Store, co2Store, env);
        double initialO2StoreMoles = o2Store.getCurrentLevel();
        double initialEnvironmentO2Moles = env.getO2Store().getCurrentLevel();
        double initialEnvironmentCO2Moles = env.getCO2Store().getCurrentLevel();
        double initialCO2StoreMoles = co2Store.getCurrentLevel();

        for (int step = 1; step <= N_TICKS; step++) {
            bioDriver.advanceOneTick();
            assertEquals(step, bioDriver.getTicks(), "BioDriver did not advance the production simulation tick");

            assertNonNegative(o2Store, "O2Store", step);
            assertNonNegative(co2Store, "CO2Store", step);
            for (EnvironmentStore subStore : environmentSubStores(env)) {
                assertNonNegative(subStore, subStore.getModuleName(), step);
            }

            double current = computeTotalMoles(o2Store, co2Store, env);
            double diff = current - initialTotalMoles;
            if (Math.abs(diff) > ABS_TOLERANCE_MOLES) {
                fail(String.format(
                        "Mass conservation violated at step %d:%n" +
                                "  initialTotalMoles  = %.9f%n" +
                                "  observedTotalMoles = %.9f%n" +
                                "  signedDifference   = %+.9f   (negative = leak, positive = creation)%n" +
                                "  tolerance          = %.9f",
                        step, initialTotalMoles, current, diff, ABS_TOLERANCE_MOLES));
            }
        }

        assertTrue(o2Store.getCurrentLevel() < initialO2StoreMoles,
                "O2Store did not feed the production simulation");
        assertTrue(env.getO2Store().getCurrentLevel() > initialEnvironmentO2Moles,
                "SimEnvironment did not receive O2 during production simulation ticks");
        assertTrue(env.getCO2Store().getCurrentLevel() < initialEnvironmentCO2Moles,
                "SimEnvironment did not supply CO2 during production simulation ticks");
        assertTrue(co2Store.getCurrentLevel() > initialCO2StoreMoles,
                "CO2Store did not receive CO2 during production simulation ticks");

        double finalTotal = computeTotalMoles(o2Store, co2Store, env);
        double finalDiff = finalTotal - initialTotalMoles;
        if (Math.abs(finalDiff) > ABS_TOLERANCE_MOLES) {
            fail(String.format(
                    "Mass conservation violated at end of run:%n" +
                            "  initialTotalMoles  = %.9f%n" +
                            "  observedTotalMoles = %.9f%n" +
                            "  signedDifference   = %+.9f",
                    initialTotalMoles, finalTotal, finalDiff));
        }
    }

    private static void assertNonNegative(Store store, String label, int step) {
        float level = store.getCurrentLevel();
        if (level < 0f) {
            fail(String.format(
                    "Store '%s' reported negative mass (%.9f) at step %d",
                    label, level, step));
        }
    }

    private static EnvironmentStore[] environmentSubStores(SimEnvironment env) {
        return new EnvironmentStore[]{
                env.getO2Store(),
                env.getCO2Store(),
                env.getNitrogenStore(),
                env.getOtherStore(),
                env.getVaporStore()
        };
    }

    private static double computeTotalMoles(Store o2Store, Store co2Store, SimEnvironment env) {
        return (double) o2Store.getCurrentLevel()
                + (double) co2Store.getCurrentLevel()
                + (double) env.getTotalMoles();
    }
}
