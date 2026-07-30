package org.tinydb.jdbc;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.Properties;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertThrows;

class TinyDriverTest {

    @Test
    @DisplayName("acceptsURL returns true for jdbc:tinydb:// URLs")
    void testAcceptsURLValid() throws SQLException {
        TinyDriver driver = new TinyDriver();
        assertTrue(driver.acceptsURL("jdbc:tinydb://localhost:8520/db"));
        assertTrue(driver.acceptsURL("jdbc:tinydb://localhost/db"));
        assertTrue(driver.acceptsURL("jdbc:tinydb://server.example.com:9999/test"));
    }

    @Test
    @DisplayName("acceptsURL returns false for non-jdbc URLs")
    void testAcceptsURLInvalid() throws SQLException {
        TinyDriver driver = new TinyDriver();
        assertFalse(driver.acceptsURL("jdbc:mysql://localhost/test"));
        assertFalse(driver.acceptsURL("jdbc:postgresql://localhost"));
        assertFalse(driver.acceptsURL("http://example.com"));
        assertFalse(driver.acceptsURL(""));
    }

    @Test
    @DisplayName("acceptsURL returns false for null URL")
    void testAcceptsURLNull() throws SQLException {
        TinyDriver driver = new TinyDriver();
        assertFalse(driver.acceptsURL(null));
    }

    @Test
    @DisplayName("connect returns null for non-matching URL")
    void testConnectNonMatchingURL() throws SQLException {
        TinyDriver driver = new TinyDriver();
        Properties p = new Properties();
        assertNull(driver.connect("jdbc:mysql://localhost/test", p));
        assertNull(driver.connect("invalid://url", p));
        assertNull(driver.connect(null, p));
    }

    @Test
    @DisplayName("connect throws SQLException for invalid tinydb URL format")
    void testConnectInvalidURLFormat() {
        TinyDriver driver = new TinyDriver();
        Properties p = new Properties();
        assertThrows(SQLException.class, () -> driver.connect("jdbc:tinydb://", p));
    }

    @Test
    @DisplayName("getPropertyInfo returns empty array")
    void testGetPropertyInfo() throws SQLException {
        TinyDriver driver = new TinyDriver();
        assertEquals(0, driver.getPropertyInfo("jdbc:tinydb://localhost/db", new Properties()).length);
    }

    @Test
    @DisplayName("getMajorVersion returns 0, getMinorVersion returns 3")
    void testVersion() {
        TinyDriver driver = new TinyDriver();
        assertEquals(0, driver.getMajorVersion());
        assertEquals(3, driver.getMinorVersion());
    }

    @Test
    @DisplayName("jdbcCompliant returns false")
    void testJdbcCompliant() {
        TinyDriver driver = new TinyDriver();
        assertFalse(driver.jdbcCompliant());
    }

    @Test
    @DisplayName("URL parsing: hostname extraction")
    void testParseUrlHostname() throws SQLException {
        TinyDriver.ParsedUrl p = TinyDriver.parseUrl("jdbc:tinydb://myhost:1234/db");
        assertEquals("myhost", p.host);
        assertEquals(1234, p.port);
        assertEquals("db", p.database);
    }

    @Test
    @DisplayName("URL parsing: default port when omitted")
    void testParseUrlDefaultPort() throws SQLException {
        TinyDriver.ParsedUrl p = TinyDriver.parseUrl("jdbc:tinydb://myhost/db");
        assertEquals("myhost", p.host);
        assertEquals(TinyDriver.DEFAULT_PORT, p.port);
        assertEquals("db", p.database);
    }

    @Test
    @DisplayName("URL parsing: no database")
    void testParseUrlNoDatabase() throws SQLException {
        TinyDriver.ParsedUrl p = TinyDriver.parseUrl("jdbc:tinydb://myhost:8520");
        assertEquals("myhost", p.host);
        assertEquals(8520, p.port);
        assertNull(p.database);
    }

    @Test
    @DisplayName("URL parsing: invalid URL throws SQLException")
    void testParseUrlInvalid() {
        assertThrows(SQLException.class, () -> TinyDriver.parseUrl("not-a-url"));
        assertThrows(SQLException.class, () -> TinyDriver.parseUrl("jdbc:other://host"));
    }
}
