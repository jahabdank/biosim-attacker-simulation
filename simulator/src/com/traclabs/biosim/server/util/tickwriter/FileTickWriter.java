package com.traclabs.biosim.server.util.tickwriter;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.Map;

public class FileTickWriter implements TickWriter {
    private BufferedWriter ticksWriter;
    private Path simDirectory;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Override
    public void open(int simId) throws IOException {
        // Create logs/sim_<simId> directory if it doesn't exist
        simDirectory = Paths.get("logs", "sim_" + simId);
        if (!Files.exists(simDirectory)) {
            Files.createDirectories(simDirectory);
        }
        // Open the ticks file in append mode (or create if missing)
        Path ticksFile = simDirectory.resolve("ticks.jsonl");
        ticksWriter = Files.newBufferedWriter(ticksFile, StandardOpenOption.CREATE, StandardOpenOption.APPEND);
    }

    @Override
    public void writeConfig(int simId, String configText) throws IOException {
        // Ensure simDirectory exists (should be created in open(), but double-check)
        if (simDirectory == null) {
            simDirectory = Paths.get("logs", "sim_" + simId);
            if (!Files.exists(simDirectory)) {
                Files.createDirectories(simDirectory);
            }
        }
        // Write the configuration snapshot to config.xml (overwrite if exists)
        Path configFile = simDirectory.resolve("config.xml");
        Files.write(configFile, configText.getBytes(), StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
    }

    @Override
    public void writeTick(int simId, int tickNumber, Map<String, Object> simulationDetails) throws IOException {
        if (ticksWriter == null) {
            throw new IOException("Tick writer has not been opened.");
        }
        // Serialize the full simulation details to JSON
        String jsonLine = objectMapper.writeValueAsString(simulationDetails);
        ticksWriter.write(jsonLine);
        ticksWriter.newLine();
        ticksWriter.flush();
    }

    @Override
    public void close() throws IOException {
        if (ticksWriter != null) {
            ticksWriter.close();
        }
    }
}
