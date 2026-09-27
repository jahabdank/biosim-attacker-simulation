package com.traclabs.biosim.server.simulation.environment;

import com.traclabs.biosim.server.framework.MalfunctionIntensity;
import com.traclabs.biosim.server.framework.MalfunctionLength;
import com.traclabs.biosim.server.simulation.framework.SimBioModule;
import com.traclabs.biosim.server.simulation.power.PowerConsumer;
import com.traclabs.biosim.server.simulation.power.PowerConsumerDefinition;

/**
 * Opt-in fan (XML command="DAMPER"). Power-port desired is damper u in [0,1].
 * Watts drawn are W_des * u^3. Air uses volumetric Q = u * Q_des.
 */
public class FanDamper extends SimBioModule implements AirConsumer, PowerConsumer, AirProducer {
    static final float W_DES_WATTS = 120f;
    static final float Q_DES_LITERS_PER_HOUR = 108000f;
    private static final float R_KPA_LITERS = 8.314f;

    private final AirConsumerDefinition myAirConsumerDefinition;
    private final PowerConsumerDefinition myPowerConsumerDefinition;
    private final AirProducerDefinition myAirProducerDefinition;
    private float currentPowerConsumed = 0f;

    public FanDamper(int pID, String pName) {
        super(pID, pName);
        myAirConsumerDefinition = new AirConsumerDefinition(this);
        myPowerConsumerDefinition = new PowerConsumerDefinition(this);
        myAirProducerDefinition = new AirProducerDefinition(this);
    }

    public AirConsumerDefinition getAirConsumerDefinition() {
        return myAirConsumerDefinition;
    }

    public AirProducerDefinition getAirProducerDefinition() {
        return myAirProducerDefinition;
    }

    public PowerConsumerDefinition getPowerConsumerDefinition() {
        return myPowerConsumerDefinition;
    }

    public void tick() {
        super.tick();
        getAndPushAir();
    }

    private void getAndPushAir() {
        float uCmd = commandedDamper();
        float wattsNeed = wattsForDamper(uCmd);
        currentPowerConsumed = myPowerConsumerDefinition.takeAmount(wattsNeed);
        float uEff = uCmd;
        if (wattsNeed > 0f && currentPowerConsumed + 1e-6f < wattsNeed)
            uEff = (float) Math.cbrt(Math.max(0f, currentPowerConsumed / W_DES_WATTS));
        SimEnvironment[] sources = myAirConsumerDefinition.getEnvironments();
        if (sources == null || sources.length < 1 || sources[0] == null)
            return;
        SimEnvironment src = sources[0];
        float moles = molesThisTick(uEff, src.getTotalPressure(),
                src.getTemperatureInKelvin(), getTickLength());
        Air air = myAirConsumerDefinition.getAirFromEnvironment(moles, 0);
        myAirProducerDefinition.pushAirToEnvironment(air, 0);
    }

    static float clampDamper(float commanded) {
        if (commanded <= 0f)
            return 0f;
        if (commanded >= 1f)
            return 1f;
        return commanded;
    }

    static float wattsForDamper(float u) {
        if (u <= 0f)
            return 0f;
        float x = clampDamper(u);
        return W_DES_WATTS * x * x * x;
    }

    static float molesThisTick(float damper, float pressureKpa,
                               float temperatureKelvin, float tickLengthHours) {
        float u = clampDamper(damper);
        if (u <= 0f || pressureKpa <= 0f || temperatureKelvin <= 0f
                || tickLengthHours <= 0f)
            return 0f;
        float qLitersPerHour = Q_DES_LITERS_PER_HOUR * u;
        return qLitersPerHour * pressureKpa / (R_KPA_LITERS * temperatureKelvin)
                * tickLengthHours;
    }

    private float commandedDamper() {
        if (myPowerConsumerDefinition.getDesiredFlowRates().length < 1)
            return 0f;
        return clampDamper(myPowerConsumerDefinition.getDesiredFlowRate(0));
    }

    protected String getMalfunctionName(MalfunctionIntensity pIntensity,
                                        MalfunctionLength pLength) {
        return "Fan damper malfunction";
    }

    protected void performMalfunctions() {
    }

    public void reset() {
        super.reset();
        myAirConsumerDefinition.reset();
        myAirProducerDefinition.reset();
        myPowerConsumerDefinition.reset();
        currentPowerConsumed = 0f;
    }
}
