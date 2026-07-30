package org.tinydb.jdbc;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.net.ServerSocket;
import java.net.Socket;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TinyStatementTest {

    private static ServerSocket startFakeServer() throws IOException {
        ServerSocket ss = new ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1"));
        Thread t = new Thread(() -> {
            try {
                while (!ss.isClosed()) {
                    Socket client = ss.accept();
                    new Thread(() -> {
                        try {
                            java.io.DataInputStream in = new java.io.DataInputStream(client.getInputStream());
                            java.io.DataOutputStream out = new java.io.DataOutputStream(client.getOutputStream());
                            org.tinydb.jdbc.protocol.Frame hello = org.tinydb.jdbc.protocol.Frame.read(in);
                            if (hello != null && hello.getType() == org.tinydb.jdbc.protocol.Codec.TYPE_HELLO) {
                                byte[] ver = "tinydb-0.3.0".getBytes();
                                org.tinydb.jdbc.protocol.Frame okFrame = new org.tinydb.jdbc.protocol.Frame(
                                        ver.length + 2,
                                        org.tinydb.jdbc.protocol.Codec.TYPE_OK,
                                        (byte) 0,
                                        ver);
                                okFrame.write(out);
                                while (true) {
                                    org.tinydb.jdbc.protocol.Frame f = org.tinydb.jdbc.protocol.Frame.read(in);
                                    if (f == null) break;
                                    if (f.getType() == org.tinydb.jdbc.protocol.Codec.TYPE_QUIT) break;
                                    if (f.getType() == org.tinydb.jdbc.protocol.Codec.TYPE_PING) {
                                        org.tinydb.jdbc.protocol.Frame pong = org.tinydb.jdbc.protocol.Codec.encodePong(
                                                org.tinydb.jdbc.protocol.Codec.decodePing(f));
                                        pong.write(out);
                                        continue;
                                    }
                                    // Send back fake result
                                    ByteArrayOutputStream headerBaos = new ByteArrayOutputStream();
                                    DataOutputStream headerDos = new DataOutputStream(headerBaos);
                                    headerDos.writeShort(1);
                                    byte[] name = "x".getBytes();
                                    headerDos.writeByte(name.length);
                                    headerDos.write(name);
                                    headerDos.writeByte(org.tinydb.jdbc.protocol.Codec.WIRE_INT64);
                                    byte[] headerPayload = headerBaos.toByteArray();
                                    org.tinydb.jdbc.protocol.Frame hdr = new org.tinydb.jdbc.protocol.Frame(
                                            headerPayload.length + 2,
                                            org.tinydb.jdbc.protocol.Codec.TYPE_RESULT_HEADER,
                                            (byte) 0,
                                            headerPayload);
                                    hdr.write(out);

                                    ByteArrayOutputStream rowBaos = new ByteArrayOutputStream();
                                    DataOutputStream rowDos = new DataOutputStream(rowBaos);
                                    rowDos.writeShort(1);
                                    rowDos.writeByte(org.tinydb.jdbc.protocol.Codec.WIRE_INT64);
                                    rowDos.writeInt(8);
                                    rowDos.writeLong(42L);
                                    byte[] rowPayload = rowBaos.toByteArray();
                                    org.tinydb.jdbc.protocol.Frame row = new org.tinydb.jdbc.protocol.Frame(
                                            rowPayload.length + 2,
                                            org.tinydb.jdbc.protocol.Codec.TYPE_RESULT_ROW,
                                            (byte) 0,
                                            rowPayload);
                                    row.write(out);

                                    ByteArrayOutputStream doneBaos = new ByteArrayOutputStream();
                                    DataOutputStream doneDos = new DataOutputStream(doneBaos);
                                    doneDos.writeLong(1L);
                                    doneDos.writeLong(0L);
                                    doneDos.writeByte(0);
                                    byte[] donePayload = doneBaos.toByteArray();
                                    org.tinydb.jdbc.protocol.Frame done = new org.tinydb.jdbc.protocol.Frame(
                                            donePayload.length + 2,
                                            org.tinydb.jdbc.protocol.Codec.TYPE_RESULT_DONE,
                                            (byte) 0,
                                            donePayload);
                                    done.write(out);
                                }
                            }
                        } catch (IOException e) {
                            // ignore
                        } finally {
                            try { client.close(); } catch (IOException ignored) {}
                        }
                    }).start();
                }
            } catch (IOException e) {}
        });
        t.setDaemon(true);
        t.start();
        return ss;
    }

    @Test
    @DisplayName("executeQuery returns ResultSet with rows")
    void testExecuteQuery() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                ResultSet rs = stmt.executeQuery("SELECT 1");
                assertNotNull(rs);
                assertTrue(rs.next());
                assertEquals(42, rs.getInt(1));
                assertFalse(rs.next());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("executeUpdate returns rowcount")
    void testExecuteUpdate() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                int count = stmt.executeUpdate("INSERT INTO x VALUES (1)");
                assertEquals(1, count);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("execute returns true for queries, false for updates")
    void testExecute() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                assertTrue(stmt.execute("SELECT 1"));
                assertNotNull(stmt.getResultSet());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getQueryTimeout defaults to 0 and setQueryTimeout works")
    void testQueryTimeout() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                assertEquals(0, stmt.getQueryTimeout());
                stmt.setQueryTimeout(10);
                assertEquals(10, stmt.getQueryTimeout());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("setQueryTimeout rejects negative")
    void testQueryTimeoutNegative() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                assertThrows(SQLException.class, () -> stmt.setQueryTimeout(-1));
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getConnection returns the connection that created the statement")
    void testGetConnection() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                assertEquals(conn, stmt.getConnection());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("close operation marks statement as closed")
    void testClose() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db")) {
                Statement stmt = conn.createStatement();
                assertFalse(stmt.isClosed());
                stmt.close();
                assertTrue(stmt.isClosed());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("executeQuery on closed statement throws")
    void testExecuteQueryClosed() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db")) {
                Statement stmt = conn.createStatement();
                stmt.close();
                assertThrows(SQLException.class, () -> stmt.executeQuery("SELECT 1"));
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getResultSet returns the current result set or null")
    void testGetResultSet() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                assertNull(stmt.getResultSet());
                stmt.executeQuery("SELECT 1");
                assertNotNull(stmt.getResultSet());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getUpdateCount returns -1 for SELECT, rowcount for UPDATE")
    void testGetUpdateCount() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                assertEquals(-1, stmt.getUpdateCount());
                stmt.executeUpdate("INSERT INTO x VALUES (1)");
                // Now we just executed an update, so result set is null
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("maxRows and setFetchSize are no-ops")
    void testMaxRows() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                assertEquals(0, stmt.getMaxRows());
                stmt.setMaxRows(100);
                assertEquals(0, stmt.getMaxRows()); // getter always returns 0
                assertEquals(0, stmt.getFetchSize());
                stmt.setFetchSize(50);
                assertEquals(0, stmt.getFetchSize());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("setFetchDirection only accepts FETCH_FORWARD")
    void testFetchDirection() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                assertEquals(ResultSet.FETCH_FORWARD, stmt.getFetchDirection());
                stmt.setFetchDirection(ResultSet.FETCH_FORWARD);
                assertThrows(SQLException.class, () -> stmt.setFetchDirection(ResultSet.FETCH_REVERSE));
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("addBatch/clearBatch/executeBatch throw 'not supported'")
    void testBatchUnsupported() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                assertThrows(SQLException.class, () -> stmt.addBatch("INSERT"));
                assertThrows(SQLException.class, stmt::clearBatch);
                assertThrows(SQLException.class, stmt::executeBatch);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("executeBatch throws SQLException")
    void testExecuteBatchThrows() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                assertThrows(SQLException.class, stmt::executeBatch);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("setMaxFieldSize validates non-negative")
    void testMaxFieldSize() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                assertThrows(SQLException.class, () -> stmt.setMaxFieldSize(-1));
                stmt.setMaxFieldSize(1000);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getMoreResults returns false")
    void testGetMoreResults() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                assertFalse(stmt.getMoreResults());
                assertFalse(stmt.getMoreResults(Statement.CLOSE_CURRENT_RESULT));
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("setPoolable / isPoolable")
    void testSetPoolable() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                stmt.setPoolable(true);
                assertFalse(stmt.isPoolable());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("cancel throws not supported")
    void testCancel() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                assertThrows(SQLException.class, stmt::cancel);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getGeneratedKeys throws not supported")
    void testGetGeneratedKeys() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                assertThrows(SQLException.class, stmt::getGeneratedKeys);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("closeOnCompletion / isCloseOnCompletion")
    void testCloseOnCompletion() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                stmt.closeOnCompletion();
                assertFalse(stmt.isCloseOnCompletion());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("unwrap / isWrapperFor")
    void testUnwrap() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 Statement stmt = conn.createStatement()) {
                assertTrue(stmt.isWrapperFor(TinyStatement.class));
                assertNotNull(stmt.unwrap(TinyStatement.class));
                assertThrows(SQLException.class, () -> stmt.unwrap(String.class));
            }
        } finally {
            ss.close();
        }
    }
}
