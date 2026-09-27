package com.traclabs.biosim.server.framework;

import io.javalin.Javalin;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import picocli.CommandLine;
import picocli.CommandLine.Command;
import picocli.CommandLine.Option;

/**
 * Main class for the BioSim server.
 * Starts the Javalin REST API server.
 */
public class BiosimServer {
    private static final Logger logger = LoggerFactory.getLogger(BiosimServer.class);

    @Command(name = "biosim", mixinStandardHelpOptions = true, version = "BioSim 2.0.0",
             description = "Starts the BioSim server with REST API and WebSocket support.")
    static class BiosimOptions {
        @Option(names = {"--host"}, 
                description = "Bind host (default: ${DEFAULT-VALUE})",
                defaultValue = "${ENV:BIOSIM_HOST:-0.0.0.0}")
        String host;

        @Option(names = {"-p", "--port"}, 
                description = "Port number (default: ${DEFAULT-VALUE})",
                defaultValue = "${ENV:BIOSIM_PORT:-8009}")
        int port;

        @Option(names = {"-t", "--writeTicks"}, 
                description = "Enable tick logging to disk in logs/ (default: ${DEFAULT-VALUE})",
                defaultValue = "${ENV:BIOSIM_WRITE_TICKS:-false}")
        boolean writeTicks;
    }

    public static void main(String[] args) {
        BiosimOptions options = new BiosimOptions();
        CommandLine cmd = new CommandLine(options);
        try {
            CommandLine.ParseResult parseResult = cmd.parseArgs(args);
            if (cmd.isUsageHelpRequested()) {
                cmd.usage(System.out);
                return;
            }
            if (cmd.isVersionHelpRequested()) {
                cmd.printVersionHelp(System.out);
                return;
            }
        } catch (Exception e) {
            logger.error("Failed to parse command line arguments: {}", e.getMessage());
            cmd.usage(System.err);
            System.exit(1);
            return;
        }

        // Test XML configuration for errors
        BiosimInitializer.testConfiguration();

        // Start the Javalin server
        Javalin app = Javalin.create(config -> {
            // Using Javalin 6.0.0's bundledPlugins method:
            config.bundledPlugins.enableCors(cors -> cors.addRule(it -> it.anyHost()));
            config.http.defaultContentType = "application/json";
        });

        // Create controller and WebSocket handler
        SimulationController simulationController = new SimulationController();
        simulationController.setWriteTicks(options.writeTicks);

        // Register REST endpoints
        simulationController.registerEndpoints(app);

        // Bind to the host and port provided
        app.start(options.host, options.port);
        logger.info("🌎 BioSim server started 🌎 on {}:{} with WebSocket support", options.host, options.port);

        // Add shutdown hook to stop the server gracefully
        Runtime.getRuntime().addShutdownHook(new Thread(app::stop));
    }
}
