package com.traclabs.biosim.integration;

import com.traclabs.biosim.server.framework.BiosimInitializer;
import com.traclabs.biosim.server.simulation.air.CRS;
import com.traclabs.biosim.server.simulation.air.CRSConversion;
import com.traclabs.biosim.server.simulation.air.OGS;
import com.traclabs.biosim.server.simulation.air.OGSFaraday;
import com.traclabs.biosim.server.simulation.air.VCCR;
import com.traclabs.biosim.server.simulation.air.VCCRLangmuir;
import com.traclabs.biosim.server.simulation.air.VCCRLinear;
import com.traclabs.biosim.server.simulation.environment.Fan;
import com.traclabs.biosim.server.simulation.environment.FanDamper;
import com.traclabs.biosim.server.simulation.environment.SimEnvironment;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * XML implementation / thermal / command attributes select the new classes.
 * LANGMUIR must not fall through to DETAILED VCCR (that module moves no air).
 */
public class OptInPathIT {
    private static final int SIM_ID = 78;

    private static final String XML =
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>" +
                    "<biosim xmlns=\"http://www.traclabs.com/biosim\">" +
                    "  <Globals tickLength=\"1\" startPaused=\"true\" runTillN=\"0\" runTillCrewDeath=\"false\"/>" +
                    "  <SimBioModules>" +
                    "    <environment>" +
                    "      <SimEnvironment moduleName=\"Cabin\" thermal=\"ONE_NODE\" initialVolume=\"18000\">" +
                    "        <percentageInitialization waterPercentage=\"0.01\" nitrogenPercentage=\"0.66\"" +
                    "          otherPercentage=\"0.01\" o2Percentage=\"0.31\" totalPressure=\"55\" co2Percentage=\"0.01\"/>" +
                    "      </SimEnvironment>" +
                    "      <Fan command=\"DAMPER\" moduleName=\"LoopFan\">" +
                    "        <airConsumer inputs=\"Cabin\" desiredFlowRates=\"2500\" maxFlowRates=\"2500\"/>" +
                    "        <powerConsumer inputs=\"Bus\" desiredFlowRates=\"1\" maxFlowRates=\"200\"/>" +
                    "        <airProducer outputs=\"Cabin\" desiredFlowRates=\"2500\" maxFlowRates=\"2500\"/>" +
                    "      </Fan>" +
                    "    </environment>" +
                    "    <air>" +
                    "      <VCCR moduleName=\"Scrubber\" implementation=\"LANGMUIR\" ppCo2SetpointMmHg=\"3\">" +
                    "        <powerConsumer inputs=\"Bus\" desiredFlowRates=\"2000\" maxFlowRates=\"2000\"/>" +
                    "        <airConsumer inputs=\"Cabin\" desiredFlowRates=\"10000\" maxFlowRates=\"10000\"/>" +
                    "        <airProducer outputs=\"Cabin\" desiredFlowRates=\"10000\" maxFlowRates=\"10000\"/>" +
                    "        <CO2Producer outputs=\"CO2Tank\" desiredFlowRates=\"10000\" maxFlowRates=\"10000\"/>" +
                    "      </VCCR>" +
                    "      <VCCR moduleName=\"Legacy\" implementation=\"DETAILED\">" +
                    "        <powerConsumer inputs=\"Bus\" desiredFlowRates=\"0\" maxFlowRates=\"2000\"/>" +
                    "        <airConsumer inputs=\"Cabin\" desiredFlowRates=\"10000\" maxFlowRates=\"10000\"/>" +
                    "        <airProducer outputs=\"Cabin\" desiredFlowRates=\"10000\" maxFlowRates=\"10000\"/>" +
                    "        <CO2Producer outputs=\"CO2Tank\" desiredFlowRates=\"10000\" maxFlowRates=\"10000\"/>" +
                    "      </VCCR>" +
                    "      <OGS moduleName=\"OGS\" implementation=\"FARADAY\">" +
                    "        <powerConsumer inputs=\"Bus\" desiredFlowRates=\"0\" maxFlowRates=\"1000\"/>" +
                    "        <potableWaterConsumer inputs=\"Water\" desiredFlowRates=\"0\" maxFlowRates=\"10\"/>" +
                    "        <O2Producer outputs=\"O2Tank\" desiredFlowRates=\"0\" maxFlowRates=\"1000\"/>" +
                    "        <H2Producer outputs=\"H2Tank\" desiredFlowRates=\"0\" maxFlowRates=\"1000\"/>" +
                    "      </OGS>" +
                    "      <CRS moduleName=\"CRS\" implementation=\"CONVERSION\">" +
                    "        <powerConsumer inputs=\"Bus\" desiredFlowRates=\"100\" maxFlowRates=\"100\"/>" +
                    "        <CO2Consumer inputs=\"CO2Tank\" desiredFlowRates=\"100\" maxFlowRates=\"100\"/>" +
                    "        <H2Consumer inputs=\"H2Tank\" desiredFlowRates=\"100\" maxFlowRates=\"100\"/>" +
                    "        <potableWaterProducer outputs=\"Water\" desiredFlowRates=\"100\" maxFlowRates=\"100\"/>" +
                    "        <methaneProducer outputs=\"CH4Tank\" desiredFlowRates=\"100\" maxFlowRates=\"100\"/>" +
                    "      </CRS>" +
                    "      <O2Store moduleName=\"O2Tank\" level=\"10\" capacity=\"100\"/>" +
                    "      <H2Store moduleName=\"H2Tank\" level=\"0\" capacity=\"100\"/>" +
                    "      <CO2Store moduleName=\"CO2Tank\" level=\"0\" capacity=\"1000\"/>" +
                    "      <MethaneStore moduleName=\"CH4Tank\" level=\"0\" capacity=\"100\"/>" +
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
    void optInAttributesSelectNewClassesNotDetailedStub() {
        BiosimInitializer.deleteInstance(SIM_ID);
        BiosimInitializer initializer = BiosimInitializer.getInstance(SIM_ID);
        initializer.parseXmlConfiguration(XML);

        assertInstanceOf(VCCRLangmuir.class, BiosimInitializer.getModule(SIM_ID, "Scrubber"));
        assertFalse(BiosimInitializer.getModule(SIM_ID, "Scrubber") instanceof VCCRLinear);
        assertFalse(BiosimInitializer.getModule(SIM_ID, "Scrubber") instanceof VCCR);
        assertInstanceOf(VCCR.class, BiosimInitializer.getModule(SIM_ID, "Legacy"));
        assertInstanceOf(OGSFaraday.class, BiosimInitializer.getModule(SIM_ID, "OGS"));
        assertFalse(BiosimInitializer.getModule(SIM_ID, "OGS") instanceof OGS);
        assertInstanceOf(CRSConversion.class, BiosimInitializer.getModule(SIM_ID, "CRS"));
        assertFalse(BiosimInitializer.getModule(SIM_ID, "CRS") instanceof CRS);
        assertInstanceOf(FanDamper.class, BiosimInitializer.getModule(SIM_ID, "LoopFan"));
        assertFalse(BiosimInitializer.getModule(SIM_ID, "LoopFan") instanceof Fan);
        SimEnvironment cabin = (SimEnvironment) BiosimInitializer.getModule(SIM_ID, "Cabin");
        assertTrue(cabin.isOneNodeThermal());
    }
}
