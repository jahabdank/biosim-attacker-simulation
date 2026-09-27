package com.traclabs.biosim.server.simulation.air;

import com.traclabs.biosim.server.framework.MalfunctionIntensity;
import com.traclabs.biosim.server.framework.MalfunctionLength;
import com.traclabs.biosim.server.simulation.framework.SimBioModule;
import com.traclabs.biosim.server.simulation.power.PowerConsumer;
import com.traclabs.biosim.server.simulation.power.PowerConsumerDefinition;
import com.traclabs.biosim.server.simulation.water.PotableWaterProducer;
import com.traclabs.biosim.server.simulation.water.PotableWaterProducerDefinition;

/**
 * Opt-in Sabatier (XML implementation="CONVERSION").
 * Converts η of the stoichiometric min of CO2 and H2. Power 0 ⇒ off.
 * Starves without H2. Not a W/36 CO2 demand.
 */
public class CRSConversion extends SimBioModule implements PowerConsumer, PotableWaterProducer, CO2Consumer, H2Consumer, MethaneProducer {
    static final float CONVERSION_ETA = 0.85f;

    private final PowerConsumerDefinition myPowerConsumerDefinition;
    private final PotableWaterProducerDefinition myPotableWaterProducerDefinition;
    private final O2ProducerDefinition myO2ProducerDefinition;
    private final CO2ConsumerDefinition myCO2ConsumerDefinition;
    private final H2ConsumerDefinition myH2ConsumerDefinition;
    private final MethaneProducerDefinition myMethaneProducerDefinition;
    private float currentPowerConsumed = 0f;
    private float currentCO2Consumed;
    private float currentH2Consumed;
    private float currentH2OProduced;
    private float currentCH4Produced;

    public CRSConversion(int pID, String pName) {
        super(pID, pName);
        myPowerConsumerDefinition = new PowerConsumerDefinition(this);
        myPotableWaterProducerDefinition = new PotableWaterProducerDefinition(this);
        myO2ProducerDefinition = new O2ProducerDefinition(this);
        myCO2ConsumerDefinition = new CO2ConsumerDefinition(this);
        myH2ConsumerDefinition = new H2ConsumerDefinition(this);
        myMethaneProducerDefinition = new MethaneProducerDefinition(this);
    }

    static float convertedMoles(float co2Moles, float h2Moles) {
        if (co2Moles <= 0f || h2Moles <= 0f)
            return 0f;
        return CONVERSION_ETA * Math.min(co2Moles, h2Moles / 4f);
    }

    public PowerConsumerDefinition getPowerConsumerDefinition() {
        return myPowerConsumerDefinition;
    }

    public PotableWaterProducerDefinition getPotableWaterProducerDefinition() {
        return myPotableWaterProducerDefinition;
    }

    public CO2ConsumerDefinition getCO2ConsumerDefinition() {
        return myCO2ConsumerDefinition;
    }

    public O2ProducerDefinition getO2ProducerDefinition() {
        return myO2ProducerDefinition;
    }

    public H2ConsumerDefinition getH2ConsumerDefinition() {
        return myH2ConsumerDefinition;
    }

    public MethaneProducerDefinition getMethaneProducerDefinition() {
        return myMethaneProducerDefinition;
    }

    public void tick() {
        super.tick();
        currentPowerConsumed = myPowerConsumerDefinition.getMostResourceFromStores();
        if (currentPowerConsumed <= 0f) {
            currentCO2Consumed = 0f;
            currentH2Consumed = 0f;
            currentH2OProduced = 0f;
            currentCH4Produced = 0f;
            return;
        }
        float tick = getTickLength();
        float co2Cap = 0f;
        float h2Cap = 0f;
        if (myCO2ConsumerDefinition.getDesiredFlowRates().length > 0)
            co2Cap = Math.min(myCO2ConsumerDefinition.getMaxFlowRate(0),
                    myCO2ConsumerDefinition.getDesiredFlowRate(0)) * tick;
        if (myH2ConsumerDefinition.getDesiredFlowRates().length > 0)
            h2Cap = Math.min(myH2ConsumerDefinition.getMaxFlowRate(0),
                    myH2ConsumerDefinition.getDesiredFlowRate(0)) * tick;
        currentCO2Consumed = myCO2ConsumerDefinition.getResourceFromStores(co2Cap);
        currentH2Consumed = myH2ConsumerDefinition.getResourceFromStores(h2Cap);
        if (currentH2Consumed <= 0f || currentCO2Consumed <= 0f) {
            currentH2OProduced = 0f;
            currentCH4Produced = 0f;
            myH2ConsumerDefinition.pushResourceToStores(currentH2Consumed);
            myCO2ConsumerDefinition.pushResourceToStores(currentCO2Consumed);
        } else {
            float converted = convertedMoles(currentCO2Consumed, currentH2Consumed);
            myCO2ConsumerDefinition.pushResourceToStores(currentCO2Consumed - converted);
            myH2ConsumerDefinition.pushResourceToStores(currentH2Consumed - 4f * converted);
            currentH2OProduced = (2f * converted * 18.01524f) / 1000f;
            currentCH4Produced = converted;
        }
        myPotableWaterProducerDefinition.pushResourceToStores(currentH2OProduced);
        myMethaneProducerDefinition.pushResourceToStores(currentCH4Produced);
    }

    protected String getMalfunctionName(MalfunctionIntensity pIntensity,
                                        MalfunctionLength pLength) {
        return "None";
    }

    protected void performMalfunctions() {
    }

    public void reset() {
        super.reset();
        myPowerConsumerDefinition.reset();
        myPotableWaterProducerDefinition.reset();
        myO2ProducerDefinition.reset();
        myCO2ConsumerDefinition.reset();
        myH2ConsumerDefinition.reset();
        myMethaneProducerDefinition.reset();
    }
}
