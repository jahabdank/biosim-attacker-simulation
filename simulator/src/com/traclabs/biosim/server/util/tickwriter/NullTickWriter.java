package com.traclabs.biosim.server.util.tickwriter;

import java.io.IOException;
import java.util.Map;

public class NullTickWriter implements TickWriter {

    @Override
    public void open(int simId) throws IOException {
        // No operation implementation.
    }

    @Override
    public void writeConfig(int simId, String configText) throws IOException {
        // No operation implementation.
    }

    @Override
    public void writeTick(int simId, int tickNumber, Map<String, Object> simulationDetails) throws IOException {
        // No operation implementation.
    }

    @Override
    public void close() throws IOException {
        // No operation implementation.
    }
}
