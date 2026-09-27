# BioSim
BioSim is a research project developed at NASA Johnson Space Center. The objective is to create a portable simulation of an integrated advanced life support system for mission scenarios with malfunctions and perturbations.

The simulation is written in Java. It uses a RESTful API for communication, enabling integration with any HTTP-capable language.

## Building and testing standalone

Use JDK **21** and Maven **3.8.7 or newer** from the repository root. The first
build needs access to Maven Central (or a configured mirror) to download public
dependencies. No other repository or service is required.

```bash
java -version
mvn -version
mvn -B clean verify
```

`verify` compiles the simulator, runs both unit tests and `*IT` integration tests,
and produces `target/biosim-2.0.0.jar` with its runtime dependencies in `target/lib/`,
plus the convenience `target/biosim-2.0.0-jar-with-dependencies.jar`. Keep the thin
JAR and `lib/` together when distributing them; dependency JARs retain their own
license and notice files. Both BioSim JAR forms embed the GPL text at
`META-INF/biosim/LICENSE` and retain bundled dependency license/notice resources
under `META-INF/dependency-notices/`, separated by artifact to avoid name collisions.

All regression fixtures are inline in tests or under `configuration/test/`.
The suite includes six 7,200-tick crew-transfer runs, a 1,440-tick closed-loop mass
check, and the existing humans/crops ledger validation. Lifecycle regressions use
real driver threads and a temporary loopback HTTP server to check pause, stop,
restart, looping, and terminal acknowledgement/snapshot consistency. Missing
fixtures fail; no external XML environment variable or system property is needed. Surefire
reports are in `target/surefire-reports/`; mass ledgers are in `target/mass-*/`.
To run just the transfer and mass checks:

```bash
mvn -B -Dtest=CrewTransferAtomicityIT,ClosedLoopMassIT,MassConservationE2ETest,MassValidationScenarioIT test
```

See [simulator changes and validation limits](doc/simulator_changes.md) for the
behavior changes and the optional physical laws. The Java simulator and its
standalone fixtures are independent of external controllers.

## Running BioSim

### Using the Scripts in the `bin` Directory
The `bin` directory contains scripts to launch the simulation:

- **`start-biosim-server`**: Starts the BioSim server with the following options:
  - `--host` - Bind host (default: `0.0.0.0`)
  - `-p, --port` - Port number (default: `8009`)
  - `-t, --writeTicks` - Enable tick logging to disk in `logs/` directory (default: `false`)

  **Usage examples:**
  ```bash
  bin/start-biosim-server                           # Use defaults
  bin/start-biosim-server --host 127.0.0.1 -p 9000  # Custom host and port
  bin/start-biosim-server --writeTicks               # Enable tick logging
  ```

- **`run-simulation`**: Launches a simulation using the default configuration. Other configurations can be specified (see the `configuration` directory) with the `--config` option. Run using `--help` for more options.

### Environment Variables
You can set defaults using environment variables; explicit CLI options take precedence:

| Variable | Description | Default |
|----------|-------------|---------|
| `BIOSIM_HOST` | Default bind host (CLI `--host` takes precedence) | `0.0.0.0` |
| `BIOSIM_PORT` | Default port (CLI `--port` takes precedence) | `8009` |
| `BIOSIM_WRITE_TICKS` | Default tick logging (CLI `--writeTicks` takes precedence) | `false` |

**Example:**
```bash
export BIOSIM_PORT=9000
export BIOSIM_WRITE_TICKS=true
bin/start-biosim-server
```

### Local smoke run

Start the server on loopback (stop it with Ctrl-C):

```bash
java -jar target/biosim-2.0.0.jar --host 127.0.0.1 --port 8009
```

In a second terminal, submit a bundled, paused simulator-only fixture:

```bash
bin/run-simulation --config configuration/test/ClosedLoopMassInit.xml --url http://127.0.0.1:8009
curl --fail http://127.0.0.1:8009/api/simulation
```

Use the returned `simId` for subsequent requests, for example
`POST /api/simulation/1/tick?n=60`. This fixture is a closed air/water/reaction
circuit for regression checks, not a crew habitat or a mission configuration.

### Using Docker

Build from this repository alone. The build stage uses Java 21/Maven and runs the
full test suite, including the bundled XML fixtures. The runtime stage uses Java
21, a non-root UID (10001), and the thin JAR with unmodified dependency JARs.

```bash
docker build -t biosim:local .
docker run --rm -p 127.0.0.1:8009:8009 biosim:local
docker run --rm biosim:local --help
```

The same host-side `bin/run-simulation` command above submits configurations to
the container. For persistent tick logs, mount a directory writable by UID 10001
at `/app/logs` and append `--writeTicks` to `docker run`.

The API has no authentication and permits cross-origin requests. Keep it on a
trusted local interface; do not expose it directly to the public Internet.

The optional `docker-compose.yml` also builds the
[Open MCT](https://github.com/nasa/openmct)
[plugin for BioSim](https://github.com/scottbell/openmct-biosim/) from its separate
public repository. `docker compose up --build biosim-server` selects only the
simulator; `docker compose up --build` additionally starts that UI on port 9091.
Compose publishes port 8009 on all interfaces by default. Its `./logs` bind mount
must be writable by UID 10001 if logging is enabled. The standalone commands above
do not require Open MCT.

<img width="1607" alt="biosim-with-openmct" src="https://github.com/user-attachments/assets/0812e361-6a93-4dd9-8006-8a2b6e21133f" />

## REST API Endpoints

The simulation exposes several REST endpoints:

### Simulation Endpoints

- **GET** `/api/simulation`  
  Retrieves a list of active simulation IDs. E.g.:
  ```json
  {"simulations":[1,2]}
  ```

- **GET** `/api/simulation/{simID}`  
  Retrieves global simulation properties and detailed module information for all modules. E.g.:
  ```json
  {
    "globals": {
      "myID": 1,
      "simulationIsPaused": false,
      "simulationStarted": true,
      "simulationEnded": false,
      "ticksGoneBy": 1367,
      "runTillN": -1,
      "runTillCrewDeath": true,
      "runTillPlantDeath": false,
      "looping": false,
      "driverStutterLength": 500,
      "tickLength": 1
    },
    "modules": {
      "CO2_Store": {
        "moduleName": "Backup_CO2_Store",
        "moduleType": "CO2Store",
        "properties": {
          "currentLevel": 0,
          "currentCapacity": 1000,
          "overflow": 0,
          "isPipe": false
        }
      }
    }
  }
  ```

  **Global Properties:**
  - `simulationStarted`: Boolean indicating if the simulation has been started
  - `simulationEnded`: Boolean indicating if the simulation has ended due to meeting end criteria (crew death, plant death, or tick limit)
  - `simulationIsPaused`: Boolean indicating if the simulation is currently paused
  - `runTillN`: Number of ticks to run until (-1 if not set)
  - `runTillCrewDeath`: Boolean indicating if simulation runs until crew death
  - `runTillPlantDeath`: Boolean indicating if simulation runs until plant death

- **GET** `/api/simulation/{simID}/modules/{moduleName}`  
  Provides detailed information about a specific module, including consumer/producer definitions, flow rate arrays, or store properties if it is a store. E.g.:
  ```json
  {
    "moduleName": "Backup_CO2_Store",
    "moduleType": "CO2Store",
    "properties": {
      "currentLevel": 0,
      "currentCapacity": 1000,
      "overflow": 0,
      "isPipe": false
    }
  }
  ```

- **POST** `/api/simulation/start`  
  Starts a new simulation.  
  **Request Body:**  
  The XML configuration for the simulation should be provided as plain text.  
  **Response:**  
  JSON containing the simulation ID. E.g.:
  ```json
  {"simId":2}
  ```
  **Example:**
  ```
  curl -X POST http://localhost:8009/api/simulation/start \
       -H "Content-Type: text/plain" \
       -d '<xml><configuration>...</configuration></xml>'
  ```

- **POST** `/api/simulation/{simID}/tick`  
  Advances the simulation by one tick, or up to `n` ticks with `?n=60`.
  `n` must be a positive integer; malformed/nonpositive values return HTTP 400.
  Batches stop when a configured end condition is reached. The response contains
  the final `ticks` count and the number actually `advanced` in this request.
  After termination, later tick requests return the same `ticks` and `advanced: 0`;
  the terminal GET snapshot retains that count. A paused worker cannot add a tick
  after termination. Reset/restart is required before further progress. Manual
  batches stop at the boundary even when automatic looping is configured.
  Use a paused simulation and one controlling client for deterministic stepping.
  **Response:**  
  JSON indicating the updated tick count. E.g.:
  ```json
  {"ticks":1597,"advanced":1}
  ```
  **Example:**
  ```
  curl -X POST http://localhost:8009/api/simulation/1/tick
  ```

- **GET** `/api/simulation/{simID}/log`  
  Returns the complete run log for a simulation including configuration, run metadata, and all tick data.  
  **Note:** This endpoint is only available when tick logging is enabled (`--writeTicks`).  
  **Response:**  
  JSON containing the simulation log data. E.g.:
  ```json
  {
    "configXML": "<biosim>...</biosim>",
    "runStarted": "2025-09-02T08:00:00.123456Z",
    "simID": 1,
    "runEnded": false,
    "ticks": [
      {
        "tick": 0,
        "globals": { ... },
        "modules": { ... }
      },
      {
        "tick": 1,
        "globals": { ... },
        "modules": { ... }
      }
    ]
  }
  ```
  
  **Response Fields:**
  - `configXML`: The XML configuration used to start the simulation
  - `runStarted`: Timestamp when the simulation run was started
  - `simID`: The simulation ID
  - `runEnded`: Boolean indicating if the run has ended. `true` if the simulation is not currently in memory (e.g., after server restart) or if the in-memory simulation has met end criteria; `false` if the simulation is still running in memory
  - `ticks`: Array of tick data containing simulation state at each tick

- **POST** `/api/simulation/{simID}/modules/{moduleName}/consumers/{type}`
  Updates the consumer definition for a specified module.  
  **Request Body:**  
  A JSON object with the following keys:
  - `desiredFlowRates`: An array of floats indicating the desired flow rates.
  - `connections`: (Optional) An array of strings representing connection module names; the array length must match that of `desiredFlowRates`.
  
  **Response:**  
  A JSON confirmation message indicating successful update.
  
  **Example:**
  ```
  curl -X POST http://localhost:8009/api/simulation/1/modules/OGS/consumers/potableWater \
       -H "Content-Type: application/json" \
       -d '{"desiredFlowRates": [10.0], "connections": ["Potable_Water_Store"]}'
  ```

- **POST** `/api/simulation/{simID}/modules/{moduleName}/producers/{type}`  
  Updates the producer definition for a specified module.  
  **Request Body:**  
  A JSON object with the following keys:
  - `desiredFlowRates`: An array of floats indicating the desired flow rates.
  - `connections`: (Optional) An array of strings representing connection module names; the array length must match that of `desiredFlowRates`.
  
  **Response:**  
  A JSON confirmation message indicating successful update.
  
  **Example:**
  ```
  curl -X POST http://localhost:8009/api/simulation/1/modules/OGS/producers/H2 \
       -H "Content-Type: application/json" \
       -d '{"desiredFlowRates": [10.0], "connections": ["H2_Store"]}'
  ```

### Malfunction Endpoints

- **GET** /api/simulation/{simID}/modules/{moduleName}/malfunctions

  This endpoint retrieves the list of malfunctions for the specified module. It returns a JSON array where each object represents a malfunction with the following properties:

  - **id**: The unique identifier of the malfunction.
  - **name**: The name of the malfunction.
  - **intensity**: The malfunction intensity (one of `SEVERE_MALF`, `MEDIUM_MALF`, or `LOW_MALF`).
  - **length**: The malfunction length (either `TEMPORARY_MALF` or `PERMANENT_MALF`).
  - **performed**: A boolean indicating whether the malfunction has been executed.
  - **tickToMalfunction**: The simulation tick at which the malfunction is scheduled to occur or did occur.
  - **doneEnoughRepairWork**: A boolean indicating if the required repair work has been completed for the malfunction.

  **Response:**
  ```json
  [
    {
      "id": 2,
      "name": "Temporary Medium Malfunction",
      "intensity": "MEDIUM_MALF",
      "length": "TEMPORARY_MALF",
      "performed": true,
      "tickToMalfunction": 0,
      "doneEnoughRepairWork": false
    }
  ]

- **POST** `/api/simulation/{simID}/modules/{moduleName}/malfunctions`  
  Starts or schedules a malfunction for a specific module.  
  **Request Body:**  
  A JSON object that must include:
  - `intensity`: A string representing the malfunction intensity (`SEVERE_MALF`, `MEDIUM_MALF`, or `LOW_MALF`).
  - `length`: A string representing the malfunction length (`TEMPORARY_MALF` or `PERMANENT_MALF`).
  
  Optionally, you can include:
  - `tickToOccur`: An integer specifying when the malfunction should occur. If provided, the malfunction will be scheduled using `scheduleMalfunction`; otherwise, `startMalfunction` is called.
  
  **Response:**  
  A JSON object containing the `malfunctionID`.
  ```json
  {"malfunctionID":2}
  ```
  **Example:**
  ```
  curl -X POST http://localhost:8009/api/simulation/1/modules/OGS/malfunctions \
       -H "Content-Type: application/json" \
       -d '{"intensity": "MEDIUM_MALF", "length": "TEMPORARY_MALF", "tickToOccur": 3}'
  ```

- **DELETE** `/api/simulation/{simID}/modules/{moduleName}/malfunctions/{malfunctionID}`  
  Clears a specific malfunction from a module.  
  **Response:**  
  A JSON confirmation message.
  ```json
  {"message":"Malfunction 2 cleared."}
  ```  
  **Example:**
  ```
  curl -X DELETE http://localhost:8009/api/simulation/1/modules/OGS/malfunctions/2
  ```

- **DELETE** `/api/simulation/{simID}/modules/{moduleName}/malfunctions`  
  Clears all malfunctions from a specific module.  
  **Response:**  
  A JSON confirmation message.
  ```json
  {"message":"All malfunctions cleared."}
  ```
  **Example:**
  ```
  curl -X DELETE http://localhost:8009/api/simulation/1/modules/OGS/malfunctions
  ```

## WebSocket Interface
In addition to the REST API endpoints, there is a WebSocket interface for real-time simulation updates. To subscribe to live simulation state updates, connect to:  
  ws://<host>:<port>/ws/simulation/{simID}
Upon connection, the server immediately sends the current simulation state and then broadcasts further updates on each tick.

## Configuring BioSim
For more detailed instructions on configuring BioSim, please refer to the [Users Manual](doc/users_manual.md#configuring-the-simulation). This manual documents the full configuration surface: the XML file structure, global run-control settings, units, modules and stores, producer/consumer flow definitions, crew and crop/biomass setup, environment settings, the power/water/air/waste/thermal/life-support equipment types, and reliability/malfunction/stochastic knobs, with complete examples.

## License and attribution

BioSim remains licensed under [GNU GPL version 3](LICENSE). This modified version
retains the upstream NASA Johnson Space Center project attribution and all
embedded author, copyright, and third-party notices. See the dated
[change notice](doc/simulator_changes.md). Dependencies retain their respective
licenses; redistribution must preserve their notices and satisfy applicable
source-distribution obligations.
