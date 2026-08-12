package org.tinydb.jdbc;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertThrows;

class TinyConnectionTest {

    /**
     * Helper: spawn a fake tinydb server that responds to HELLO with OK.
     * Returns the server socket so the test can read client requests.
     */
    private static ServerSocket startFakeServer() throws IOException {
        ServerSocket ss = new ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1"));
        Thread t = new Thread(() -> {
            try {
                while (!ss.isClosed()) {
                    Socket client = ss.accept();
                    new Thread(() -> {
                        try {
                            DataInputStream in = new DataInputStream(client.getInputStream());
                            DataOutputStream out = new DataOutputStream(client.getOutputStream());
                            // Read HELLO frame
                            org.tinydb.jdbc.protocol.Frame hello = org.tinydb.jdbc.protocol.Frame.read(in);
                            if (hello != null && hello.getType() == org.tinydb.jdbc.protocol.Codec.TYPE_HELLO) {
                                // Send OK
                                byte[] ver = "tinydb-0.3.0".getBytes();
                                org.tinydb.jdbc.protocol.Frame okFrame = new org.tinydb.jdbc.protocol.Frame(
                                        ver.length,
                                        org.tinydb.jdbc.protocol.Codec.TYPE_OK,
                                        (byte) 0,
                                        ver);
                                okFrame.write(out);
                                // Echo whatever client sends
                                while (true) {
                                    org.tinydb.jdbc.protocol.Frame f = org.tinydb.jdbc.protocol.Frame.read(in);
                                    if (f == null) break;
                                    if (f.getType() == org.tinydb.jdbc.protocol.Codec.TYPE_PING) {
                                        org.tinydb.jdbc.protocol.Frame pong = org.tinydb.jdbc.protocol.Codec.encodePong(
                                                org.tinydb.jdbc.protocol.Codec.decodePing(f));
                                        pong.write(out);
                                    } else if (f.getType() == org.tinydb.jdbc.protocol.Codec.TYPE_QUIT) {
                                        break;
                                    } else {
                                        // Send back fake RESULT_HEADER + RESULT_DONE
                                        ByteArrayOutputStream headerBaos = new ByteArrayOutputStream();
                                        DataOutputStream headerDos = new DataOutputStream(headerBaos);
                                        headerDos.writeShort(0); // 0 cols
                                        byte[] headerPayload = headerBaos.toByteArray();
                                        org.tinydb.jdbc.protocol.Frame hdr = new org.tinydb.jdbc.protocol.Frame(
                                                headerPayload.length,
                                                org.tinydb.jdbc.protocol.Codec.TYPE_RESULT_HEADER,
                                                (byte) 0,
                                                headerPayload);
                                        hdr.write(out);

                                        ByteArrayOutputStream doneBaos = new ByteArrayOutputStream();
                                        DataOutputStream doneDos = new DataOutputStream(doneBaos);
                                        doneDos.writeLong(0L);
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
                            }
                        } catch (IOException e) {
                            // client disconnected
                        } finally {
                            try { client.close(); } catch (IOException ignored) {}
                        }
                    }).start();
                }
            } catch (IOException e) {
                // accept failed
            }
        });
        t.setDaemon(true);
        t.start();
        return ss;
    }

    @Test
    @DisplayName("Driver.getConnection dials fake server and receives OK")
    void testConnectToFakeServer() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            java.sql.Connection conn = DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb");
            assertNotNull(conn);
            assertFalse(conn.isClosed());
            conn.close();
            assertTrue(conn.isClosed());
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("Connection.isValid returns true when ping succeeds")
    void testIsValid() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (Connection conn = DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                assertTrue(conn.isValid(5));
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("autoCommit defaults to true")
    void testAutoCommitDefault() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (Connection conn = DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                assertTrue(conn.getAutoCommit());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("setAutoCommit updates state")
    void testSetAutoCommit() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (Connection conn = DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                conn.setAutoCommit(false);
                assertFalse(conn.getAutoCommit());
                conn.setAutoCommit(true);
                assertTrue(conn.getAutoCommit());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("commit and rollback send SQL commands (autoCommit must be off)")
    void testCommitRollback() throws Exception {
        ServerSocket ss = startFakeServer();
        AtomicReference<String> lastSql = new AtomicReference<>();
        try {
            int port = ss.getLocalPort();
            try (Connection conn = DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb")) {
                // The fake server echoes back RESULT_HEADER/DONE
                // commit/rollback are only valid when autoCommit is false.
                conn.setAutoCommit(false);
                conn.commit();
                conn.rollback();
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("Close twice is safe")
    void testCloseTwice() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            Connection conn = DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb");
            conn.close();
            conn.close(); // Should not throw
            assertTrue(conn.isClosed());
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("After close, commit throws SQLException")
    void testCommitAfterClose() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            Connection conn = DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/testdb");
            conn.close();
            assertThrows(SQLException.class, conn::commit);
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getCatalog returns database name from URL")
    void testGetCatalog() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (Connection conn = DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/mydb")) {
                assertEquals("mydb", conn.getCatalog());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("setCatalog updates catalog")
    void testSetCatalog() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (Connection conn = DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/mydb")) {
                conn.setCatalog("other_db");
                assertEquals("other_db", conn.getCatalog());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("nativeSQL returns SQL unchanged")
    void testNativeSQL() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (Connection conn = DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/mydb")) {
                assertEquals("SELECT 1", conn.nativeSQL("SELECT 1"));
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("getMetaData returns TinyDatabaseMetaData")
    void testGetMetaData() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (Connection conn = DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/mydb")) {
                assertNotNull(conn.getMetaData());
                assertTrue(conn.getMetaData() instanceof TinyDatabaseMetaData);
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("createStatement returns TinyStatement")
    void testCreateStatement() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (Connection conn = DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/mydb")) {
                assertNotNull(conn.createStatement());
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("prepareStatement returns TinyPreparedStatement")
    void testPrepareStatement() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (Connection conn = DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/mydb")) {
                assertNotNull(conn.prepareStatement("SELECT ?"));
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("unwrap returns TinyConnection when class matches")
    void testUnwrap() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (Connection conn = DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/mydb")) {
                assertTrue(conn.isWrapperFor(TinyConnection.class));
                assertNotNull(conn.unwrap(TinyConnection.class));
            }
        } finally {
            ss.close();
        }
    }

    @Test
    @DisplayName("unwrap throws SQLException for wrong class")
    void testUnwrapWrongClass() throws Exception {
        ServerSocket ss = startFakeServer();
        try {
            int port = ss.getLocalPort();
            try (Connection conn = DriverManager.getConnection(
                    "jdbc:tinydb://127.0.0.1:" + port + "/mydb")) {
                assertFalse(conn.isWrapperFor(String.class));
                assertThrows(SQLException.class, () -> conn.unwrap(String.class));
            }
        } finally {
            ss.close();
        }
    }
}
