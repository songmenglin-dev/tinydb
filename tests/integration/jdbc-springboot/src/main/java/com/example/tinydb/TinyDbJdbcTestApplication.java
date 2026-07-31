package com.example.tinydb;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Spring Boot entry point.  The real verification of tinydb JDBC
 * connectivity happens in {@code TinyDbConnectivityIT} under
 * {@code src/test/java}; this class only exists so the project can
 * also be started as a long-running app if desired.
 */
@SpringBootApplication
public class TinyDbJdbcTestApplication {
    public static void main(String[] args) {
        SpringApplication.run(TinyDbJdbcTestApplication.class, args);
    }
}