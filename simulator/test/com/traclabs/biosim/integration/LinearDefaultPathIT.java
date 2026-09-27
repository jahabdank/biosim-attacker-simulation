package com.traclabs.biosim.integration;

import com.traclabs.biosim.server.framework.BioDriver;
import com.traclabs.biosim.server.framework.BiosimInitializer;
import com.traclabs.biosim.server.simulation.air.OGS;
import com.traclabs.biosim.server.simulation.air.VCCRLinear;
import com.traclabs.biosim.server.simulation.environment.Fan;
import com.traclabs.biosim.server.simulation.environment.SimEnvironment;
import com.traclabs.biosim.server.simulation.framework.Store;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Untouched LINEAR / no-volume / no-thermal XML keeps the stock laws.
 */
public class LinearDefaultPathIT {
    private static final int SIM_ID = 77;
    private static final String XML =
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>" +
                    "<biosim xmlns=\"http://www.traclabs.com/biosim\">" +
                    "  <Globals tickLength=\"1\" startPaused=\"true\" runTillN=\"0\" runTillCrewDeath=\"false\"/>" +
                    "  <SimBioModules>" +
                    "    <environment>" +
                    "      <SimEnvironment moduleName=\"Cabin\" initialVolume=\"18000\">" +
                    "        <percentageInitialization waterPercentage=\"0.01\" nitrogenPercentage=\"0.66\"" +
                    "          otherPercentage=\"0.01\" o2Percentage=\"0.31\" totalPressure=\"55\" co2Percentage=\"0.01\"/>" +
                    "      </SimEnvironment>" +
                    "      <Fan moduleName=\"LoopFan\">" +
                    "        <airConsumer inputs=\"Cabin\" desiredFlowRates=\"804\" maxFlowRates=\"804\"/>" +
                    "        <powerConsumer inputs=\"Bus\" desiredFlowRates=\"50\" maxFlowRates=\"50\"/>" +
                    "        <airProducer outputs=\"Cabin\" desiredFlowRates=\"804\" maxFlowRates=\"804\"/>" +
                    "      </Fan>" +
                    "    </environment>" +
                    "    <air>" +
                    "      <VCCR moduleName=\"Scrubber\" implementation=\"LINEAR\">" +
                    "        <powerConsumer inputs=\"Bus\" desiredFlowRates=\"2000\" maxFlowRates=\"2000\"/>" +
                    "        <airConsumer inputs=\"Cabin\" desiredFlowRates=\"10000\" maxFlowRates=\"10000\"/>" +
                    "        <airProducer outputs=\"Cabin\" desiredFlowRates=\"10000\" maxFlowRates=\"10000\"/>" +
                    "        <CO2Producer outputs=\"CO2Tank\" desiredFlowRates=\"10000\" maxFlowRates=\"10000\"/>" +
                    "      </VCCR>" +
                    "      <OGS moduleName=\"OGS\">" +
                    "        <powerConsumer inputs=\"Bus\" desiredFlowRates=\"0\" maxFlowRates=\"1000\"/>" +
                    "        <potableWaterConsumer inputs=\"Water\" desiredFlowRates=\"0\" maxFlowRates=\"10\"/>" +
                    "        <O2Producer outputs=\"O2Tank\" desiredFlowRates=\"0\" maxFlowRates=\"1000\"/>" +
                    "        <H2Producer outputs=\"H2Tank\" desiredFlowRates=\"0\" maxFlowRates=\"1000\"/>" +
                    "      </OGS>" +
                    "      <O2Store moduleName=\"O2Tank\" level=\"10\" capacity=\"100\"/>" +
                    "      <H2Store moduleName=\"H2Tank\" level=\"0\" capacity=\"100\"/>" +
                    "      <CO2Store moduleName=\"CO2Tank\" level=\"0\" capacity=\"1000\"/>" +
                    "    </air>" +
                    "    <water>" +
                    "      <PotableWaterStore moduleName=\"Water\" level=\"10\" capacity=\"100\"/>" +
                    "    </water>" +
                    "    <power>" +
                    "      <PowerStore moduleName=\"Bus\" level=\"100000\" capacity=\"100000\"/>" +
                    "    </power>" +
                    "  </SimBioModules>" +
                    "</biosim>";

    @AfterEach
    void tearDown() {
        BiosimInitializer.deleteInstance(SIM_ID);
    }

    @Test
    void linearConfigKeepsStockClassesFrozenTAndWattFan() {
        BiosimInitializer.deleteInstance(SIM_ID);
        BiosimInitializer initializer = BiosimInitializer.getInstance(SIM_ID);
        initializer.parseXmlConfiguration(XML);
        BioDriver driver = initializer.getBioDriver();
        driver.reset();

        assertInstanceOf(VCCRLinear.class, BiosimInitializer.getModule(SIM_ID, "Scrubber"));
        assertInstanceOf(OGS.class, BiosimInitializer.getModule(SIM_ID, "OGS"));
        assertInstanceOf(Fan.class, BiosimInitializer.getModule(SIM_ID, "LoopFan"));
        SimEnvironment cabin = (SimEnvironment) BiosimInitializer.getModule(SIM_ID, "Cabin");
        Store o2Tank = (Store) BiosimInitializer.getModule(SIM_ID, "O2Tank");
        assertEquals(23f, cabin.getTemperature(), 0.01f);
        assertFalse(cabin.isOneNodeThermal());
        assertEquals(0f, o2Tank.getTankPressureKpa(), 0f);

        cabin.addHeatJoules(1e6f);
        float t0 = cabin.getTemperature();
        float co2Start = cabin.getCO2Store().getCurrentLevel();
        driver.advanceOneTick();
        assertEquals(t0, cabin.getTemperature(), 0.01f);
        assertEquals(23f, cabin.getTemperature(), 0.01f);
        assertTrue(cabin.getCO2Store().getCurrentLevel() < co2Start,
                "LINEAR VCCR still removes CO2 from the cabin slug");
    }
}
