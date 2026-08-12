package org.tinydb.jdbc;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.tinydb.jdbc.protocol.Codec;

import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.net.ServerSocket;
import java.net.Socket;
import java.sql.ResultSet;
import java.sql.SQLException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TinyDatabaseMetaDataTest {

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
                                byte[] ver = "tinydb-0.3.1".getBytes();
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
                                    // Send back fake SHOW TABLES result
                                    String sql = new String(f.getPayload(),
                                            java.nio.charset.StandardCharsets.UTF_8);
                                    boolean isShow = sql.toUpperCase().contains("SHOW");
                                    byte[] payload;
                                    if (isShow) {
                                        ByteArrayOutputStream baos = new ByteArrayOutputStream();
                                        DataOutputStream dos = new DataOutputStream(baos);
                                        dos.writeShort(1);
                                        byte[] n = "name".getBytes();
                                        dos.writeByte(n.length);
                                        dos.write(n);
                                        dos.writeByte(Codec.WIRE_STRING);
                                        payload = baos.toByteArray();
                                    } else {
                                        ByteArrayOutputStream baos = new ByteArrayOutputStream();
                                        DataOutputStream dos = new DataOutputStream(baos);
                                        dos.writeShort(0);
                                        payload = baos.toByteArray();
                                    }
                                    org.tinydb.jdbc.protocol.Frame hdr = new org.tinydb.jdbc.protocol.Frame(
                                            payload.length,
                                            org.tinydb.jdbc.protocol.Codec.TYPE_RESULT_HEADER,
                                            (byte) 0,
                                            payload);
                                    hdr.write(out);

                                    if (isShow) {
                                        ByteArrayOutputStream baos = new ByteArrayOutputStream();
                                        DataOutputStream dos = new DataOutputStream(baos);
                                        dos.writeShort(1);
                                        dos.writeByte(Codec.WIRE_STRING);
                                        dos.writeInt(5);
                                        dos.write("users".getBytes("UTF-8"));
                                        byte[] rowPayload = baos.toByteArray();
                                        org.tinydb.jdbc.protocol.Frame row = new org.tinydb.jdbc.protocol.Frame(
                                                rowPayload.length,
                                                org.tinydb.jdbc.protocol.Codec.TYPE_RESULT_ROW,
                                                (byte) 0,
                                                rowPayload);
                                        row.write(out);
                                    }

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

    private static TinyDatabaseMetaData getMeta() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb");
            return (TinyDatabaseMetaData) conn.getMetaData();
        } finally {
            // socket will stay alive for the test duration
        }
    }

    @Test
    @DisplayName("getURL returns JDBC URL with host, port, and database")
    void testGetURL() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                java.sql.DatabaseMetaData md = conn.getMetaData();
                String url = md.getURL();
                assertTrue(url.startsWith("jdbc:tinydb://"));
                assertTrue(url.contains("testdb"));
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getDatabaseProductName returns 'tinydb'")
    void testGetDatabaseProductName() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                assertEquals("tinydb", conn.getMetaData().getDatabaseProductName());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getDatabaseProductVersion returns server version")
    void testGetDatabaseProductVersion() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                assertEquals("tinydb-0.3.1", conn.getMetaData().getDatabaseProductVersion());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getDriverName returns 'tinydb-jdbc'")
    void testGetDriverName() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                assertEquals("tinydb-jdbc", conn.getMetaData().getDriverName());
                assertEquals("0.3.1", conn.getMetaData().getDriverVersion());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getUserName returns 'tinydb'")
    void testGetUserName() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                assertEquals("tinydb", conn.getMetaData().getUserName());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("supportsTransactions returns true")
    void testSupportsTransactions() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                assertTrue(conn.getMetaData().supportsTransactions());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("isReadOnly returns false")
    void testIsReadOnly() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                assertFalse(conn.getMetaData().isReadOnly());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getSQLStateType returns sqlStateSQL99")
    void testGetSQLStateType() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                assertEquals(java.sql.DatabaseMetaData.sqlStateSQL99,
                        conn.getMetaData().getSQLStateType());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getRowIdLifetime returns ROWID_UNSUPPORTED")
    void testGetRowIdLifetime() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                assertEquals(java.sql.RowIdLifetime.ROWID_UNSUPPORTED,
                        conn.getMetaData().getRowIdLifetime());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getConnection returns the connection")
    void testGetConnection() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                assertEquals(conn, conn.getMetaData().getConnection());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getDriverMajorVersion returns 0, MinorVersion returns 3")
    void testDriverVersions() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                assertEquals(0, conn.getMetaData().getDriverMajorVersion());
                assertEquals(3, conn.getMetaData().getDriverMinorVersion());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getTables sends SHOW TABLES and constructs JDBC result set")
    void testGetTables() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                ResultSet rs = conn.getMetaData().getTables(null, null, "%", null);
                assertNotNull(rs);
                assertTrue(rs.next());
                assertEquals("users", rs.getString("TABLE_NAME"));
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("supportsResultSetConcurrency returns true for FORWARD_ONLY + READ_ONLY")
    void testSupportsResultSetConcurrency() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                assertTrue(conn.getMetaData().supportsResultSetConcurrency(
                        ResultSet.TYPE_FORWARD_ONLY, ResultSet.CONCUR_READ_ONLY));
                assertFalse(conn.getMetaData().supportsResultSetConcurrency(
                        ResultSet.TYPE_SCROLL_INSENSITIVE, ResultSet.CONCUR_READ_ONLY));
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
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                java.sql.DatabaseMetaData md = conn.getMetaData();
                assertTrue(md.isWrapperFor(TinyDatabaseMetaData.class));
                assertNotNull(md.unwrap(TinyDatabaseMetaData.class));
                assertThrows(SQLException.class, () -> md.unwrap(String.class));
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("unsupported methods throw 'not supported in v0.3'")
    void testUnsupportedMethods() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                java.sql.DatabaseMetaData md = conn.getMetaData();
                assertThrows(SQLException.class, () -> md.getProcedures(null, null, null));
                assertThrows(SQLException.class, () -> md.getSchemas("c", "s"));
                assertThrows(SQLException.class, md::getCatalogs);
                assertThrows(SQLException.class, md::getTableTypes);
                assertThrows(SQLException.class, md::getTypeInfo);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("isClosed reflects connection state")
    void testIsClosed() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            java.sql.Connection conn = java.sql.DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb");
            assertFalse(conn.isClosed());
            conn.close();
            assertTrue(conn.isClosed());
        } finally {
            ss.close();
        }
    }
}
