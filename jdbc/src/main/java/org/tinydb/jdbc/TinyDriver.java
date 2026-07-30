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
        try {
            Socket sock = new Socket();
            sock.connect(new InetSocketAddress(p.host, p.port), 5000);
            sock.setSoTimeout(30000);
            DataOutputStream out = new DataOutputStream(sock.getOutputStream());
            DataInputStream in = new DataInputStream(sock.getInputStream());
            // Send HELLO
            Frame hello = Codec.encodeHello("tinydb-jdbc-0.3.0");
            hello.write(out);
            // Wait for OK
            Frame resp = Frame.read(in);
            if (resp == null) {
                sock.close();
                throw new SQLException("connection closed during handshake", "08000");
            }
            if (resp.getType() == Codec.TYPE_ERR) {
                String[] parts = Codec.decodeResultError(resp);
                sock.close();
                throw TinySQLException.fromServer(parts[0], parts[1]);
            }
            if (resp.getType() != Codec.TYPE_OK) {
                sock.close();
                throw new SQLException("expected OK got 0x" + String.format("%02X", resp.getType() & 0xFF), "08000");
            }
            String version = Codec.decodeOk(resp);
            return new TinyConnection(sock, in, out, p.host, p.port, p.database, version);
        } catch (IOException e) {
            throw new SQLException("Failed to connect: " + e.getMessage(), "08000", e);
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
