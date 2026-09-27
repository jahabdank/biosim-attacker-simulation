package com.traclabs.biosim.server.simulation.air;

import com.traclabs.biosim.server.framework.Malfunction;
import com.traclabs.biosim.server.simulation.framework.SimBioModule;
import com.traclabs.biosim.server.simulation.power.PowerConsumer;
import com.traclabs.biosim.server.simulation.power.PowerConsumerDefinition;
import com.traclabs.biosim.server.simulation.water.PotableWaterConsumer;
import com.traclabs.biosim.server.simulation.water.PotableWaterConsumerDefinition;

/**
 * Opt-in electrolysis (XML implementation="FARADAY").
 * n_O2 = min(n_H2O/2, η W Δt / E) with E at thermoneutral 1.48 V, 4 e− per O2.
 * Zero potable ⇒ zero O2.
 */
public class OGSFaraday extends SimBioModule implements PowerConsumer, PotableWaterConsumer, O2Producer, H2Producer {
    static final float FARADAY_C_PER_MOL = 96485f;
    static final float THERMONEUTRAL_VOLTS = 1.48f;
    static final float E_O2_J_PER_MOL = 4f * FARADAY_C_PER_MOL * THERMONEUTRAL_VOLTS;
    static final float ETA = 0.70f;
    static final float WATER_G_PER_MOL = 18.01524f;

    private final PowerConsumerDefinition myPowerConsumerDefinition;
    private final PotableWaterConsumerDefinition myPotableWaterConsumerDefinition;
    private final O2ProducerDefinition myO2ProducerDefinition;
    private final H2ProducerDefinition myH2ProducerDefinition;
    private float currentH2OConsumed = 0;
    private float currentO2Produced = 0;
    private float currentH2Produced = 0;
    private float currentPowerConsumed = 0f;

    public OGSFaraday(int pID, String pName) {
        super(pID, pName);
        myPowerConsumerDefinition = new PowerConsumerDefinition(this);
        myPotableWaterConsumerDefinition = new PotableWaterConsumerDefinition(this);
        myO2ProducerDefinition = new O2ProducerDefinition(this);
        myH2ProducerDefinition = new H2ProducerDefinition(this);
    }

    static float oxygenMolesFromPower(float watts, float tickLengthHours) {
        if (watts <= 0f || tickLengthHours <= 0f)
            return 0f;
        return ETA * watts * tickLengthHours * 3600f / E_O2_J_PER_MOL;
    }

    static float litersWaterForOxygenMoles(float o2Moles) {
        return (2f * o2Moles * WATER_G_PER_MOL) / 1000f;
    }

    @Override
    protected void performMalfunctions() {
        for (Malfunction malfunction : myMalfunctions.values()) {
            malfunction.setPerformed(true);
        }
        if (!myMalfunctions.isEmpty()) {
            myPowerConsumerDefinition.malfunction();
            myPotableWaterConsumerDefinition.malfunction();
            myO2ProducerDefinition.malfunction();
            myH2ProducerDefinition.malfunction();
        }
    }

    public PowerConsumerDefinition getPowerConsumerDefinition() {
        return myPowerConsumerDefinition;
    }

    public PotableWaterConsumerDefinition getPotableWaterConsumerDefinition() {
        return myPotableWaterConsumerDefinition;
    }

    public O2ProducerDefinition getO2ProducerDefinition() {
        return myO2ProducerDefinition;
    }

    public H2ProducerDefinition getH2ProducerDefinition() {
        return myH2ProducerDefinition;
    }

    public void reset() {
        super.reset();
        currentH2OConsumed = 0;
        currentO2Produced = 0;
        currentH2Produced = 0;
        currentPowerConsumed = 0;
        myPowerConsumerDefinition.reset();
        myPotableWaterConsumerDefinition.reset();
        myO2ProducerDefinition.reset();
        myH2ProducerDefinition.reset();
    }

    public void tick() {
        super.tick();
        currentPowerConsumed = myPowerConsumerDefinition.getMostResourceFromStores();
        float o2FromPower = oxygenMolesFromPower(currentPowerConsumed, getTickLength());
        currentH2OConsumed = myPotableWaterConsumerDefinition
                .getResourceFromStores(litersWaterForOxygenMoles(o2FromPower));
        float molesOfWater = (currentH2OConsumed * 1000f) / WATER_G_PER_MOL;
        currentO2Produced = Math.min(molesOfWater / 2f, o2FromPower);
        currentH2Produced = currentO2Produced * 2f;
        myO2ProducerDefinition.pushResourceToStores(currentO2Produced);
        myH2ProducerDefinition.pushResourceToStores(currentH2Produced);
    }
}
