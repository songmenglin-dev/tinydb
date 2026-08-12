package org.tinydb.jdbc;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.net.ServerSocket;
import java.net.Socket;
import java.sql.PreparedStatement;
import java.sql.SQLException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TinyPreparedStatementTest {

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
                                        ver.length,
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
                                    // Send back fake result with 0 cols + 1 row
                                    ByteArrayOutputStream headerBaos = new ByteArrayOutputStream();
                                    DataOutputStream headerDos = new DataOutputStream(headerBaos);
                                    headerDos.writeShort(1);
                                    byte[] name = "x".getBytes();
                                    headerDos.writeByte(name.length);
                                    headerDos.write(name);
                                    headerDos.writeByte(org.tinydb.jdbc.protocol.Codec.WIRE_INT64);
                                    byte[] headerPayload = headerBaos.toByteArray();
                                    org.tinydb.jdbc.protocol.Frame hdr = new org.tinydb.jdbc.protocol.Frame(
                                            headerPayload.length,
                                            org.tinydb.jdbc.protocol.Codec.TYPE_RESULT_HEADER,
                                            (byte) 0,
                                            headerPayload);
                                    hdr.write(out);

                                    ByteArrayOutputStream doneBaos = new ByteArrayOutputStream();
                                    DataOutputStream doneDos = new DataOutputStream(doneBaos);
                                    doneDos.writeLong(1L);
                                    doneDos.writeLong(0L);
                                    doneDos.writeByte(0);
                                    byte[] donePayload = doneBaos.toByteArray();
                                    org.tinydb.jdbc.protocol.Frame done = new org.tinydb.jdbc.protocol.Frame(
                                            donePayload.length,
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
    @DisplayName("setString binds string parameter")
    void testSetString() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 PreparedStatement ps = conn.prepareStatement("SELECT ?")) {
                ps.setString(1, "hello");
                // Verify parameter is bound
                TinyPreparedStatement tps = (TinyPreparedStatement) ps;
                assertEquals(1, tps.getParameterCount());
                org.tinydb.jdbc.protocol.Codec.Param p = tps.getParameters().get(0);
                assertEquals(org.tinydb.jdbc.protocol.Codec.WIRE_STRING, p.type);
                assertEquals("hello", p.value);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("setInt binds int parameter")
    void testSetInt() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 PreparedStatement ps = conn.prepareStatement("SELECT ?")) {
                ps.setInt(1, 42);
                TinyPreparedStatement tps = (TinyPreparedStatement) ps;
                org.tinydb.jdbc.protocol.Codec.Param p = tps.getParameters().get(0);
                assertEquals(org.tinydb.jdbc.protocol.Codec.WIRE_INT64, p.type);
                assertEquals(42L, p.value);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("setLong binds long parameter")
    void testSetLong() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 PreparedStatement ps = conn.prepareStatement("SELECT ?")) {
                ps.setLong(1, 1234567890123L);
                TinyPreparedStatement tps = (TinyPreparedStatement) ps;
                org.tinydb.jdbc.protocol.Codec.Param p = tps.getParameters().get(0);
                assertEquals(1234567890123L, p.value);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("setDouble binds double parameter")
    void testSetDouble() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 PreparedStatement ps = conn.prepareStatement("SELECT ?")) {
                ps.setDouble(1, 3.14);
                TinyPreparedStatement tps = (TinyPreparedStatement) ps;
                org.tinydb.jdbc.protocol.Codec.Param p = tps.getParameters().get(0);
                assertEquals(org.tinydb.jdbc.protocol.Codec.WIRE_FLOAT64, p.type);
                assertEquals(3.14, p.value);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("setBoolean binds boolean parameter")
    void testSetBoolean() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 PreparedStatement ps = conn.prepareStatement("SELECT ?")) {
                ps.setBoolean(1, true);
                TinyPreparedStatement tps = (TinyPreparedStatement) ps;
                org.tinydb.jdbc.protocol.Codec.Param p = tps.getParameters().get(0);
                assertEquals(org.tinydb.jdbc.protocol.Codec.WIRE_BOOL, p.type);
                assertEquals(true, p.value);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("setNull binds null parameter")
    void testSetNull() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 PreparedStatement ps = conn.prepareStatement("SELECT ?")) {
                ps.setNull(1, java.sql.Types.VARCHAR);
                TinyPreparedStatement tps = (TinyPreparedStatement) ps;
                org.tinydb.jdbc.protocol.Codec.Param p = tps.getParameters().get(0);
                assertEquals(org.tinydb.jdbc.protocol.Codec.WIRE_NULL, p.type);
                assertEquals(null, p.value);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("clearParameters resets all parameters to null")
    void testClearParameters() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 PreparedStatement ps = conn.prepareStatement("SELECT ?,?,?")) {
                ps.setString(1, "a");
                ps.setInt(2, 1);
                ps.setBoolean(3, true);
                ps.clearParameters();
                TinyPreparedStatement tps = (TinyPreparedStatement) ps;
                for (org.tinydb.jdbc.protocol.Codec.Param p : tps.getParameters()) {
                    assertEquals(org.tinydb.jdbc.protocol.Codec.WIRE_NULL, p.type);
                }
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("setObject dispatches by type")
    void testSetObject() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 PreparedStatement ps = conn.prepareStatement("SELECT ?")) {
                ps.setObject(1, "hi");
                TinyPreparedStatement tps = (TinyPreparedStatement) ps;
                assertEquals(org.tinydb.jdbc.protocol.Codec.WIRE_STRING, tps.getParameters().get(0).type);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("setString out of range throws")
    void testSetStringOutOfRange() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 PreparedStatement ps = conn.prepareStatement("SELECT ?")) {
                assertThrows(SQLException.class, () -> ps.setString(0, "x"));
                assertThrows(SQLException.class, () -> ps.setString(2, "x"));
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("setObject with null binds null")
    void testSetObjectNull() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 PreparedStatement ps = conn.prepareStatement("SELECT ?")) {
                ps.setObject(1, null);
                TinyPreparedStatement tps = (TinyPreparedStatement) ps;
                assertEquals(org.tinydb.jdbc.protocol.Codec.WIRE_NULL, tps.getParameters().get(0).type);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("executeQuery sends EXEC and returns ResultSet")
    void testExecuteQuery() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 PreparedStatement ps = conn.prepareStatement("SELECT ?")) {
                ps.setInt(1, 42);
                assertNotNull(ps.executeQuery());
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
                 PreparedStatement ps = conn.prepareStatement("INSERT INTO x VALUES (?)")) {
                ps.setInt(1, 42);
                assertEquals(1, ps.executeUpdate());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getParameterCount reflects SQL '?' count")
    void testParameterCount() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 PreparedStatement ps = conn.prepareStatement("SELECT ?,?,?")) {
                TinyPreparedStatement tps = (TinyPreparedStatement) ps;
                assertEquals(3, tps.getParameterCount());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("parameters inside string literals are ignored")
    void testParameterCountSkipsStringLiterals() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 PreparedStatement ps = conn.prepareStatement("SELECT '?' WHERE x = ?")) {
                TinyPreparedStatement tps = (TinyPreparedStatement) ps;
                assertEquals(1, tps.getParameterCount());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("setByte / setShort / setFloat delegate to setInt / setDouble")
    void testSetByteShortFloat() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 PreparedStatement ps = conn.prepareStatement("SELECT ?,?,?")) {
                ps.setByte(1, (byte) 5);
                ps.setShort(2, (short) 100);
                ps.setFloat(3, 1.5f);
                TinyPreparedStatement tps = (TinyPreparedStatement) ps;
                assertEquals(5L, tps.getParameters().get(0).value);
                assertEquals(100L, tps.getParameters().get(1).value);
                assertEquals(1.5, (Double) tps.getParameters().get(2).value, 0.001);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("setBigDecimal binds as string")
    void testSetBigDecimal() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 PreparedStatement ps = conn.prepareStatement("SELECT ?")) {
                ps.setBigDecimal(1, new java.math.BigDecimal("123.45"));
                TinyPreparedStatement tps = (TinyPreparedStatement) ps;
                assertEquals(org.tinydb.jdbc.protocol.Codec.WIRE_STRING, tps.getParameters().get(0).type);
                assertEquals("123.45", tps.getParameters().get(0).value);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("setBytes binds as string")
    void testSetBytes() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/db");
                 PreparedStatement ps = conn.prepareStatement("SELECT ?")) {
                ps.setBytes(1, new byte[]{1, 2, 3});
                TinyPreparedStatement tps = (TinyPreparedStatement) ps;
                assertEquals(org.tinydb.jdbc.protocol.Codec.WIRE_STRING, tps.getParameters().get(0).type);
            }
        } finally {
            ss.close();
        }
    }
}
