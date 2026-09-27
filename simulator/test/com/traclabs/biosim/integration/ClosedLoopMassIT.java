package com.traclabs.biosim.integration;

import com.traclabs.biosim.server.framework.BioDriver;
import com.traclabs.biosim.server.framework.BiosimInitializer;
import com.traclabs.biosim.server.framework.IBioModule;
import com.traclabs.biosim.server.simulation.air.CO2Store;
import com.traclabs.biosim.server.simulation.air.H2Store;
import com.traclabs.biosim.server.simulation.air.MethaneStore;
import com.traclabs.biosim.server.simulation.air.O2Store;
import com.traclabs.biosim.server.simulation.air.VCCRLangmuir;
import com.traclabs.biosim.server.simulation.environment.SimEnvironment;
import com.traclabs.biosim.server.simulation.framework.Store;
import com.traclabs.biosim.server.simulation.power.PowerStore;
import com.traclabs.biosim.server.simulation.water.WaterStore;
import com.traclabs.biosim.server.util.massvalidation.MassConstants;
import com.traclabs.biosim.server.util.massvalidation.MassLedger;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.DoubleSupplier;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Closed air/water/reaction circuit, including the scrubber's internal CO2 inventory. */
class ClosedLoopMassIT {
    private static final int SIM_ID = 4242;
    private static final Path XML = Path.of("configuration/test/ClosedLoopMassInit.xml");
    private static final int TICKS_24H = 1440;
    private static final double M_H2 = 0.00201588;
    private static final double M_CH4 = 0.0160425;
    private static final double RESIDUAL_BOUND_KG = 1.0e-4;
    // Includes accumulated single-precision store rounding over 1440 ticks.
    private static final double CUMULATIVE_BOUND_KG = 0.01;

    @AfterEach
    void tearDown() {
        BiosimInitializer.deleteInstance(SIM_ID);
    }

    @Test
    void closedLoopMassResidualIsBoundedEveryTick() throws Exception {
        BiosimInitializer initializer = BiosimInitializer.getInstance(SIM_ID);
        initializer.parseXmlConfiguration(Files.readString(XML));
        BioDriver driver = initializer.getBioDriver();
        driver.reset();
        assertEquals(1.0 / 60.0, driver.getTickLength(), 1.0e-8);
        Path out = Path.of("target/mass-closed-loop");
        MassLedger ledger = new MassLedger(out.resolve("ledger.csv"), out.resolve("summary.json"));
        ledger.setScenario("closed_loop_24h");
        ledger.setTickLengthHours(driver.getTickLength());
        ledger.addNote("Closed fixture: no crew, leaks, resupply, or store overflow.");
        ledger.addNote("CO2 held in the Langmuir bed remains inside the mass boundary.");

        Map<String, DoubleSupplier> compartments = new LinkedHashMap<>();
        for (IBioModule module : driver.getModules()) {
            if (module instanceof SimEnvironment env) {
                String name = env.getModuleName();
                compartments.put(name + ".o2",
                        () -> env.getO2Store().getCurrentLevel() * MassConstants.M_O2_KG_PER_MOL);
                compartments.put(name + ".co2",
                        () -> env.getCO2Store().getCurrentLevel() * MassConstants.M_CO2_KG_PER_MOL);
                compartments.put(name + ".n2",
                        () -> env.getNitrogenStore().getCurrentLevel() * MassConstants.M_N2_KG_PER_MOL);
                compartments.put(name + ".vapor",
                        () -> env.getVaporStore().getCurrentLevel() * MassConstants.M_H2O_KG_PER_MOL);
                compartments.put(name + ".other",
                        () -> env.getOtherStore().getCurrentLevel() * MassConstants.M_AR_KG_PER_MOL);
            } else if (module instanceof VCCRLangmuir vccr) {
                compartments.put(vccr.getModuleName() + ".bed",
                        () -> vccr.getBedInventoryMoles() * MassConstants.M_CO2_KG_PER_MOL);
            } else if (module instanceof Store store && !(store instanceof PowerStore)) {
                compartments.put(store.getModuleName(), () -> storeKg(store));
            }
        }
        compartments.forEach((name, snapshot) -> ledger.addCompartment(name, snapshot::getAsDouble));
        double initialKg = totalKg(compartments);
        ledger.recordTick(0);
        VCCRLangmuir scrubber = (VCCRLangmuir) BiosimInitializer.getModule(SIM_ID, "Scrubber");
        double maxBedMoles = 0;
        for (int tick = 1; tick <= TICKS_24H; tick++) {
            driver.advanceOneTick();
            assertEquals(tick, driver.getTicks());
            assertEquals(initialKg, totalKg(compartments), CUMULATIVE_BOUND_KG,
                    "Cumulative mass drift at tick " + tick);
            maxBedMoles = Math.max(maxBedMoles, scrubber.getBedInventoryMoles());
            ledger.setSimulationTicks(driver.getTicks());
            ledger.recordTick(tick);
        }
        MassLedger.ValidationResult result = ledger.validate(RESIDUAL_BOUND_KG);
        assertTrue(result.passed, "Max per-tick residual " + result.maxAbsResidual
                + " kg at tick " + result.worstTick + " (" + result.worstCompartmentDelta + ")");
        assertEquals(TICKS_24H + 1, ledger.getRowCount());
        assertTrue(maxBedMoles > 1, "Scrubber never adsorbed CO2");
        assertTrue(ledger.getCompartmentDelta("Cabin.co2") < -0.01, "Scrubber did not remove CO2");
        assertTrue(ledger.getCompartmentDelta("Methane") > 0.01, "Reactor did not receive desorbed CO2");
        assertTrue(ledger.getCompartmentDelta("Oxygen") > 0.1, "Electrolyzer did not run");
        assertTrue(ledger.getCompartmentDelta("Condensate") > 0.01, "Condenser did not run");
    }

    @Test
    void carbonDioxideUsesItsOwnMolarMass() {
        CO2Store co2 = new CO2Store(SIM_ID, "CarbonDioxide");
        co2.setCurrentLevel(1);
        assertEquals(MassConstants.M_CO2_KG_PER_MOL, storeKg(co2));
    }

    private static double totalKg(Map<String, DoubleSupplier> compartments) {
        double total = 0;
        for (Map.Entry<String, DoubleSupplier> entry : compartments.entrySet()) {
            double kg = entry.getValue().getAsDouble();
            assertTrue(Double.isFinite(kg) && kg >= 0, "Invalid mass in " + entry.getKey());
            total += kg;
        }
        return total;
    }

    private static double storeKg(Store store) {
        float level = store.getCurrentLevel();
        assertTrue(Float.isFinite(level) && level >= 0, "Invalid store " + store.getModuleName());
        assertEquals(0f, store.getOverflow(), "Fixture overflowed " + store.getModuleName());
        if (store instanceof CO2Store)
            return level * MassConstants.M_CO2_KG_PER_MOL;
        if (store instanceof O2Store)
            return level * MassConstants.M_O2_KG_PER_MOL;
        if (store instanceof H2Store)
            return level * M_H2;
        if (store instanceof MethaneStore)
            return level * M_CH4;
        if (store instanceof WaterStore)
            return level * MassConstants.WATER_KG_PER_LITER;
        throw new IllegalArgumentException("Unaccounted store type: " + store.getClass().getSimpleName());
    }
}
