FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY pom.xml LICENSE ./
COPY src/ src/
COPY test/ test/
COPY etc/ etc/
COPY configuration/ configuration/
RUN mvn -B clean verify

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /build/target/biosim-2.0.0.jar target/
COPY --from=build /build/target/lib/ target/lib/
COPY configuration/ configuration/
COPY LICENSE ./
RUN mkdir logs && chown 10001:10001 logs
USER 10001:10001
EXPOSE 8009
ENTRYPOINT ["java", "-jar", "target/biosim-2.0.0.jar"]
