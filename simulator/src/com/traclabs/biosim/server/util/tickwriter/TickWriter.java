package com.traclabs.biosim.server.util.tickwriter;

import com.traclabs.biosim.server.framework.BioDriver;
import java.io.IOException;
import java.util.Map;

public interface TickWriter {
    /**
     * Prepares the tick writer for a simulation run.
     * @param simId the simulation ID to use for log directory naming.
     * @throws IOException if an I/O error occurs.
     */
    void open(int simId) throws IOException;

    /**
     * Writes the configuration snapshot used for the simulation.
     * Typically, this writes the full configuration to a separate file.
     * @param simId the simulation ID.
     * @param configText the raw configuration text.
     * @throws IOException if an I/O error occurs.
     */
    void writeConfig(int simId, String configText) throws IOException;

    /**
     * Writes a single tick record to the log.
     * @param simId the simulation ID.
     * @param tickNumber the tick number.
     * @param simulationDetails the full simulation details for this tick.
     * @throws IOException if an I/O error occurs.
     */
    void writeTick(int simId, int tickNumber, Map<String, Object> simulationDetails) throws IOException;

    /**
     * Closes the tick writer and releases any resources.
     * @throws IOException if an I/O error occurs.
     */
    void close() throws IOException;
}
