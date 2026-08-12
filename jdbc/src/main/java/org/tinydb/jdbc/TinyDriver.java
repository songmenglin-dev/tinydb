package org.tinydb.jdbc;

import org.tinydb.jdbc.protocol.Codec;
import org.tinydb.jdbc.protocol.Frame;

import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.sql.Connection;
import java.sql.Driver;
import java.sql.DriverManager;
import java.sql.DriverPropertyInfo;
import java.sql.SQLException;
import java.sql.SQLFeatureNotSupportedException;
import java.util.Properties;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * JDBC Type-4 driver for tinydb. URL format: jdbc:tinydb://host:port/database
 * Register via META-INF/services/java.sql.Driver.
 */
public class TinyDriver implements Driver {
    public static final String URL_PREFIX = "jdbc:tinydb://";
    public static final int DEFAULT_PORT = 8520;
    private static final Pattern URL_PATTERN = Pattern.compile(
            "^jdbc:tinydb://([^:/?]+)(?::(\\d+))?(/[^?]*)?(?:\\?(.*))?$"
    );

    static {
        try {
            DriverManager.registerDriver(new TinyDriver());
        } catch (SQLException e) {
            throw new RuntimeException("Failed to register TinyDriver", e);
        }
    }

    @Override
    public Connection connect(String url, Properties info) throws SQLException {
        if (url == null) return null;
        if (!acceptsURL(url)) return null;
        ParsedUrl p = parseUrl(url);
        Socket sock = null;
        try {
            sock = new Socket();
            sock.connect(new InetSocketAddress(p.host, p.port), 5000);
            sock.setSoTimeout(30000);
            DataOutputStream out = new DataOutputStream(sock.getOutputStream());
            DataInputStream in = new DataInputStream(sock.getInputStream());
            // Send HELLO.  ``Codec.encodeHello`` only fails on a
            // programming error (e.g. client id > MAX_CLIENT_ID), but
            // catching RuntimeException here keeps the socket from
            // leaking if the encoder ever throws.
            Frame hello;
            try {
                hello = Codec.encodeHello("tinydb-jdbc-0.3.1");
            } catch (RuntimeException re) {
                throw new SQLException("handshake encode failed: " + re.getMessage(), "08000", re);
            }
            hello.write(out);
            // Wait for OK
            Frame resp = Frame.read(in);
            if (resp == null) {
                throw new SQLException("connection closed during handshake", "08000");
            }
            if (resp.getType() == Codec.TYPE_ERR) {
                String[] parts = Codec.decodeResultError(resp);
                throw TinySQLException.fromServer(parts[0], parts[1]);
            }
            if (resp.getType() != Codec.TYPE_OK) {
                throw new SQLException("expected OK got 0x" + String.format("%02X", resp.getType() & 0xFF), "08000");
            }
            String version = Codec.decodeOk(resp);
            TinyConnection conn = new TinyConnection(sock, in, out, p.host, p.port, p.database, version);
            // Hand ownership of the socket to the connection; from now
            // on ``conn.close()`` is responsible for releasing it.
            sock = null;
            return conn;
        } catch (IOException e) {
            throw new SQLException("Failed to connect: " + e.getMessage(), "08000", e);
        } finally {
            if (sock != null) {
                try { sock.close(); } catch (IOException ignored) { }
            }
        }
    }

    @Override
    public boolean acceptsURL(String url) throws SQLException {
        return url != null && url.startsWith(URL_PREFIX);
    }

    @Override
    public DriverPropertyInfo[] getPropertyInfo(String url, Properties info) throws SQLException {
        return new DriverPropertyInfo[0];
    }

    @Override
    public int getMajorVersion() { return 0; }

    @Override
    public int getMinorVersion() { return 3; }

    @Override
    public boolean jdbcCompliant() { return false; }

    @Override
    public java.util.logging.Logger getParentLogger() throws SQLFeatureNotSupportedException {
        throw new SQLFeatureNotSupportedException("getParentLogger not supported");
    }

    static ParsedUrl parseUrl(String url) throws SQLException {
        Matcher m = URL_PATTERN.matcher(url);
        if (!m.matches()) {
            throw new SQLException("invalid tinydb URL: " + url, "08000");
        }
        ParsedUrl p = new ParsedUrl();
        p.host = m.group(1);
        String portStr = m.group(2);
        p.port = (portStr != null) ? Integer.parseInt(portStr) : DEFAULT_PORT;
        String dbPart = m.group(3);
        if (dbPart != null && dbPart.length() > 1) {
            p.database = dbPart.substring(1); // strip leading /
        }
        return p;
    }

    static class ParsedUrl {
        String host;
        int port;
        String database;
    }
}
