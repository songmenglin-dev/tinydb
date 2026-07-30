package org.tinydb.jdbc;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;

import java.io.BufferedReader;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.Statement;
import java.sql.Types;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * End-to-end test that spawns a real tinydb-server subprocess and exercises
 * the full JDBC API: connect, create table, insert, select, update, delete,
 * prepared statements, transactions, and metadata.
 *
 * Activated only when a tinydb-server executable is available on PATH.
 */
@EnabledIf("org.tinydb.jdbc.EndToEndTest#serverAvailable")
class EndToEndTest {

    private static Process serverProcess;
    private static int serverPort;
    private static final String SERVER_CMD = "tinydb-server";

    static boolean serverAvailable() {
        try {
            Process p = new ProcessBuilder(SERVER_CMD, "--help").redirectErrorStream(true).start();
            boolean finished = p.waitFor(3, TimeUnit.SECONDS);
            if (finished) {
                return p.exitValue() == 0 || p.exitValue() == 1;
            }
            p.destroyForcibly();
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    private static void waitForServer(int port, int timeoutSec) throws Exception {
        long deadline = System.currentTimeMillis() + timeoutSec * 1000L;
        while (System.currentTimeMillis() < deadline) {
            try (java.net.Socket s = new java.net.Socket("127.0.0.1", port)) {
                return;
            } catch (IOException ignored) {
                Thread.sleep(200);
            }
        }
        throw new RuntimeException("timed out waiting for server on port " + port);
    }

    @BeforeAll
    static void startServer() throws Exception {
        // Find a free port
        try (java.net.ServerSocket probe = new java.net.ServerSocket(0)) {
            serverPort = probe.getLocalPort();
        }
        // Spawn the server
        ProcessBuilder pb = new ProcessBuilder(SERVER_CMD, "--port", String.valueOf(serverPort));
        pb.redirectErrorStream(true);
        serverProcess = pb.start();
        // Consume server output (avoid blocking)
        Thread t = new Thread(() -> {
            try (BufferedReader r = new BufferedReader(new InputStreamReader(
                    serverProcess.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = r.readLine()) != null) {
                    // discard
                }
            } catch (IOException ignored) {}
        });
        t.setDaemon(true);
        t.start();
        waitForServer(serverPort, 10);
    }

    @AfterAll
    static void stopServer() {
        if (serverProcess != null && serverProcess.isAlive()) {
            serverProcess.destroy();
            try {
                serverProcess.waitFor(3, TimeUnit.SECONDS);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
        }
    }

    private static Connection connect() throws Exception {
        return DriverManager.getConnection("jdbc:tinydb://127.0.0.1:" + serverPort + "/testdb");
    }

    @Test
    @DisplayName("End-to-end: connect, create table, insert, select roundtrip")
    void testCrudRoundtrip() throws Exception {
        try (Connection conn = connect()) {
            try (Statement stmt = conn.createStatement()) {
                stmt.execute("DROP TABLE IF EXISTS users");
                stmt.execute("CREATE TABLE users (id INT, name TEXT)");
                int rc = stmt.executeUpdate("INSERT INTO users VALUES (1, 'alice')");
                assertEquals(1, rc);
                stmt.executeUpdate("INSERT INTO users VALUES (2, 'bob')");

                try (ResultSet rs = stmt.executeQuery("SELECT id, name FROM users ORDER BY id")) {
                    assertTrue(rs.next());
                    ResultSetMetaData md = rs.getMetaData();
                    assertEquals(2, md.getColumnCount());
                    assertEquals(1, rs.getInt("id"));
                    assertEquals("alice", rs.getString("name"));
                    assertTrue(rs.next());
                    assertEquals(2, rs.getInt("id"));
                    assertEquals("bob", rs.getString("name"));
                    assertFalse(rs.next());
                }
            }
        }
    }

    @Test
    @DisplayName("PreparedStatement parameter binding")
    void testPreparedStatement() throws Exception {
        try (Connection conn = connect()) {
            try (Statement s = conn.createStatement()) {
                s.execute("DROP TABLE IF EXISTS t");
                s.execute("CREATE TABLE t (v INT)");
            }
            try (PreparedStatement ps = conn.prepareStatement("INSERT INTO t VALUES (?)")) {
                ps.setInt(1, 100);
                assertEquals(1, ps.executeUpdate());
                ps.setInt(1, 200);
                assertEquals(1, ps.executeUpdate());
            }
            try (PreparedStatement ps = conn.prepareStatement("SELECT v FROM t ORDER BY v")) {
                try (ResultSet rs = ps.executeQuery()) {
                    assertTrue(rs.next());
                    assertEquals(100, rs.getInt(1));
                    assertTrue(rs.next());
                    assertEquals(200, rs.getInt(1));
                }
            }
        }
    }

    @Test
    @DisplayName("Transaction: COMMIT persists changes")
    void testTransactionCommit() throws Exception {
        try (Connection conn = connect()) {
            conn.setAutoCommit(false);
            try (Statement s = conn.createStatement()) {
                s.execute("DROP TABLE IF EXISTS tx");
                s.execute("CREATE TABLE tx (v INT)");
                s.executeUpdate("INSERT INTO tx VALUES (1)");
                conn.commit();
            }
            try (Statement s = conn.createStatement()) {
                try (ResultSet rs = s.executeQuery("SELECT v FROM tx")) {
                    assertTrue(rs.next());
                    assertEquals(1, rs.getInt(1));
                }
            }
            conn.setAutoCommit(true);
        }
    }

    @Test
    @DisplayName("Transaction: ROLLBACK discards changes")
    void testTransactionRollback() throws Exception {
        try (Connection conn = connect()) {
            try (Statement s = conn.createStatement()) {
                s.execute("DROP TABLE IF EXISTS tx2");
                s.execute("CREATE TABLE tx2 (v INT)");
                s.executeUpdate("INSERT INTO tx2 VALUES (1)");
            }
            conn.setAutoCommit(false);
            try (Statement s = conn.createStatement()) {
                s.executeUpdate("INSERT INTO tx2 VALUES (2)");
                conn.rollback();
            }
            try (Statement s = conn.createStatement()) {
                try (ResultSet rs = s.executeQuery("SELECT count(*) FROM tx2")) {
                    assertTrue(rs.next());
                    assertEquals(1, rs.getInt(1));
                }
            }
            conn.setAutoCommit(true);
        }
    }

    @Test
    @DisplayName("update and delete")
    void testUpdateDelete() throws Exception {
        try (Connection conn = connect()) {
            try (Statement s = conn.createStatement()) {
                s.execute("DROP TABLE IF EXISTS u");
                s.execute("CREATE TABLE u (v INT)");
                s.executeUpdate("INSERT INTO u VALUES (1)");
                s.executeUpdate("INSERT INTO u VALUES (2)");
                s.executeUpdate("INSERT INTO u VALUES (3)");
                assertEquals(1, s.executeUpdate("UPDATE u SET v = 99 WHERE v = 1"));
                assertEquals(1, s.executeUpdate("DELETE FROM u WHERE v = 2"));
            }
            try (Statement s = conn.createStatement();
                 ResultSet rs = s.executeQuery("SELECT v FROM u ORDER BY v")) {
                assertTrue(rs.next());
                assertEquals(3, rs.getInt(1));
                assertTrue(rs.next());
                assertEquals(99, rs.getInt(1));
                assertFalse(rs.next());
            }
        }
    }

    @Test
    @DisplayName("DatabaseMetaData.getTables returns tables")
    void testGetTables() throws Exception {
        try (Connection conn = connect()) {
            try (Statement s = conn.createStatement()) {
                s.execute("DROP TABLE IF EXISTS alpha");
                s.execute("CREATE TABLE alpha (v INT)");
            }
            try (ResultSet rs = conn.getMetaData().getTables(null, null, "%", null)) {
                boolean found = false;
                while (rs.next()) {
                    if ("alpha".equals(rs.getString("TABLE_NAME"))) {
                        found = true;
                    }
                }
                assertTrue(found);
            }
        }
    }

    @Test
    @DisplayName("Null parameter binding")
    void testNullParameter() throws Exception {
        try (Connection conn = connect()) {
            try (Statement s = conn.createStatement()) {
                s.execute("DROP TABLE IF EXISTS nullt");
                s.execute("CREATE TABLE nullt (v INT)");
            }
            try (PreparedStatement ps = conn.prepareStatement("INSERT INTO nullt VALUES (?)")) {
                ps.setNull(1, Types.INTEGER);
                assertEquals(1, ps.executeUpdate());
            }
            try (Statement s = conn.createStatement();
                 ResultSet rs = s.executeQuery("SELECT v FROM nullt")) {
                assertTrue(rs.next());
                assertEquals(0, rs.getInt(1));
                assertTrue(rs.wasNull());
            }
        }
    }

    @Test
    @DisplayName("PreparedStatement reused across execute")
    void testPreparedStatementReuse() throws Exception {
        try (Connection conn = connect()) {
            try (Statement s = conn.createStatement()) {
                s.execute("DROP TABLE IF EXISTS r");
                s.execute("CREATE TABLE r (v INT)");
            }
            try (PreparedStatement ps = conn.prepareStatement("INSERT INTO r VALUES (?)")) {
                for (int i = 0; i < 5; i++) {
                    ps.setInt(1, i);
                    assertEquals(1, ps.executeUpdate());
                }
            }
            try (Statement s = conn.createStatement();
                 ResultSet rs = s.executeQuery("SELECT count(*) FROM r")) {
                assertTrue(rs.next());
                assertEquals(5, rs.getInt(1));
            }
        }
    }

    @Test
    @DisplayName("Connection autoCommit default true")
    void testAutoCommitDefault() throws Exception {
        try (Connection conn = connect()) {
            assertTrue(conn.getAutoCommit());
        }
    }

    @Test
    @DisplayName("Connection isValid returns true")
    void testIsValid() throws Exception {
        try (Connection conn = connect()) {
            assertTrue(conn.isValid(5));
        }
    }

    @Test
    @DisplayName("Connection close + reopen")
    void testCloseReopen() throws Exception {
        try (Connection c1 = connect()) {
            assertFalse(c1.isClosed());
            c1.close();
            assertTrue(c1.isClosed());
        }
        try (Connection c2 = connect()) {
            assertFalse(c2.isClosed());
        }
    }
}
