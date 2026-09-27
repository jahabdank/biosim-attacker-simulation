package com.traclabs.biosim.server.util.tickwriter;

import com.traclabs.biosim.server.framework.TickListener;
import com.traclabs.biosim.server.framework.SimulationController;
import java.util.Map;

public class TickWriterAdapter implements TickListener {
    private final TickWriter writer;
    private final SimulationController controller;

    public TickWriterAdapter(TickWriter writer, SimulationController controller) {
        this.writer = writer;
        this.controller = controller;
    }

    @Override
    public void tickOccurred(int simId, int tickNumber) {
        try {
            Map<String, Object> simulationDetails = controller.generateSimulationDetails(simId);
            writer.writeTick(simId, tickNumber, simulationDetails);
        } catch (Exception e) {
            e.printStackTrace();
        }
    }
}
