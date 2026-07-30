package org.tinydb.jdbc;

import org.tinydb.jdbc.protocol.Codec;
import org.tinydb.jdbc.protocol.Frame;

import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.net.Socket;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.Properties;

public class TinyConnection implements Connection {

    @Override
    public void setReadOnly(boolean p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean isReadOnly() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.CallableStatement prepareCall(java.lang.String p0, int p1, int p2, int p3) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.CallableStatement prepareCall(java.lang.String p0, int p1, int p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.CallableStatement prepareCall(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void setTransactionIsolation(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getTransactionIsolation() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.SQLWarning getWarnings() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void clearWarnings() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.util.Map getTypeMap() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void setTypeMap(java.util.Map p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void setHoldability(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getHoldability() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.Savepoint setSavepoint() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.Savepoint setSavepoint(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void releaseSavepoint(java.sql.Savepoint p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.Clob createClob() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.Blob createBlob() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.NClob createNClob() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.SQLXML createSQLXML() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void setClientInfo(java.util.Properties p0) throws java.sql.SQLClientInfoException { throw new java.sql.SQLClientInfoException(); }

    @Override
    public void setClientInfo(java.lang.String p0, java.lang.String p1) throws java.sql.SQLClientInfoException { throw new java.sql.SQLClientInfoException(); }

    @Override
    public java.util.Properties getClientInfo() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.lang.String getClientInfo(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.Array createArrayOf(java.lang.String p0, java.lang.Object[] p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.Struct createStruct(java.lang.String p0, java.lang.Object[] p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void setSchema(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.lang.String getSchema() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void setNetworkTimeout(java.util.concurrent.Executor p0, int p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getNetworkTimeout() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void abort(java.util.concurrent.Executor p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public <T> T unwrap(Class<T> iface) throws SQLException {
        if (iface.isInstance(this)) return iface.cast(this);
        throw new SQLException("not a wrapper for " + iface.getName(), "HY000");
    }

    @Override
    public boolean isWrapperFor(Class<?> iface) throws SQLException {
        return iface.isInstance(this);
    }

    // ===== Custom implementation of spec methods =====

    private final Socket socket;
    private final DataInputStream in;
    private final DataOutputStream out;
    private final String host;
    private final int port;
    private final String database;
    private final String serverVersion;
    private boolean closed = false;
    private boolean autoCommit = true;
    private String catalog;
    private final Object sendLock = new Object();

    TinyConnection(Socket socket, DataInputStream in, DataOutputStream out,
                   String host, int port, String database, String serverVersion) {
        this.socket = socket;
        this.in = in;
        this.out = out;
        this.host = host;
        this.port = port;
        this.database = database;
        this.serverVersion = serverVersion;
        this.catalog = database;
    }

    DataInputStream getInputStream() { return in; }
    DataOutputStream getOutputStream() { return out; }
    String getServerVersion() { return serverVersion; }
    Object getSendLock() { return sendLock; }
    String getHost() { return host; }
    int getPort() { return port; }

    QueryResult sendQuery(String sql) throws SQLException {
        synchronized (sendLock) {
            try {
                Frame f = Codec.encodeQuery(sql);
                f.write(out);
                return readResultSequence();
            } catch (IOException e) {
                throw new SQLException("communication error: " + e.getMessage(), "08000", e);
            }
        }
    }

    QueryResult sendExec(String sql, java.util.List<Codec.Param> params) throws SQLException {
        synchronized (sendLock) {
            try {
                Frame f = Codec.encodeExec(sql, params);
                f.write(out);
                return readResultSequence();
            } catch (IOException e) {
                throw new SQLException("communication error: " + e.getMessage(), "08000", e);
            }
        }
    }

    private QueryResult readResultSequence() throws IOException, SQLException {
        java.util.List<Codec.Column> columns = null;
        java.util.List<java.util.List<Object>> rows = new java.util.ArrayList<>();
        long rowcount = 0;
        long lastInsertId = 0;
        byte flags = 0;
        boolean headerSeen = false;
        boolean doneSeen = false;
        while (!doneSeen) {
            Frame f = Frame.read(in);
            if (f == null) throw new SQLException("connection closed by server", "08000");
            if (f.getType() == Codec.TYPE_RESULT_ERROR || f.getType() == Codec.TYPE_ERR) {
                String[] parts = Codec.decodeResultError(f);
                throw TinySQLException.fromServer(parts[0], parts[1]);
            }
            if (f.getType() == Codec.TYPE_RESULT_HEADER) {
                columns = Codec.decodeResultHeader(f);
                headerSeen = true;
                continue;
            }
            if (f.getType() == Codec.TYPE_RESULT_ROW) {
                java.util.List<Object> row = Codec.decodeResultRow(f);
                rows.add(row);
                continue;
            }
            if (f.getType() == Codec.TYPE_RESULT_DONE) {
                Codec.DoneInfo info = Codec.decodeResultDone(f);
                rowcount = info.rowcount;
                lastInsertId = info.lastInsertId;
                flags = info.flags;
                doneSeen = true;
                continue;
            }
            throw new SQLException("unexpected frame type 0x" +
                    String.format("%02X", f.getType() & 0xFF), "08000");
        }
        QueryResult result = new QueryResult();
        result.columns = columns;
        result.rows = rows;
        result.rowcount = rowcount;
        result.lastInsertId = lastInsertId;
        result.flags = flags;
        result.hasHeader = headerSeen;
        return result;
    }

    static class QueryResult {
        java.util.List<Codec.Column> columns;
        java.util.List<java.util.List<Object>> rows;
        long rowcount;
        long lastInsertId;
        byte flags;
        boolean hasHeader;
    }

    @Override
    public Statement createStatement() throws SQLException {
        checkOpen();
        return new TinyStatement(this);
    }

    @Override
    public Statement createStatement(int resultSetType, int resultSetConcurrency) throws SQLException {
        checkOpen();
        return new TinyStatement(this);
    }

    @Override
    public Statement createStatement(int resultSetType, int resultSetConcurrency, int resultSetHoldability) throws SQLException {
        checkOpen();
        return new TinyStatement(this);
    }

    @Override
    public PreparedStatement prepareStatement(String sql) throws SQLException {
        checkOpen();
        return new TinyPreparedStatement(this, sql);
    }

    @Override
    public PreparedStatement prepareStatement(String sql, int autoGeneratedKeys) throws SQLException {
        checkOpen();
        return new TinyPreparedStatement(this, sql);
    }

    @Override
    public PreparedStatement prepareStatement(String sql, int[] columnIndexes) throws SQLException {
        checkOpen();
        return new TinyPreparedStatement(this, sql);
    }

    @Override
    public PreparedStatement prepareStatement(String sql, String[] columnNames) throws SQLException {
        checkOpen();
        return new TinyPreparedStatement(this, sql);
    }

    @Override
    public PreparedStatement prepareStatement(String sql, int resultSetType, int resultSetConcurrency) throws SQLException {
        checkOpen();
        return new TinyPreparedStatement(this, sql);
    }

    @Override
    public PreparedStatement prepareStatement(String sql, int resultSetType, int resultSetConcurrency, int resultSetHoldability) throws SQLException {
        checkOpen();
        return new TinyPreparedStatement(this, sql);
    }

    @Override
    public String nativeSQL(String sql) throws SQLException {
        return sql;
    }

    @Override
    public void setAutoCommit(boolean autoCommit) throws SQLException {
        checkOpen();
        this.autoCommit = autoCommit;
    }

    @Override
    public boolean getAutoCommit() throws SQLException {
        checkOpen();
        return autoCommit;
    }

    @Override
    public void commit() throws SQLException {
        checkOpen();
        sendQuery("COMMIT");
    }

    @Override
    public void rollback() throws SQLException {
        checkOpen();
        sendQuery("ROLLBACK");
    }

    @Override
    public void rollback(java.sql.Savepoint savepoint) throws SQLException {
        checkOpen();
        throw new SQLException("savepoints not supported in v0.3", "HY000");
    }

    @Override
    public void close() throws SQLException {
        if (closed) return;
        closed = true;
        try {
            Frame quit = Codec.encodeQuit();
            quit.write(out);
        } catch (IOException ignored) { }
        try {
            socket.close();
        } catch (IOException ignored) { }
    }

    @Override
    public boolean isClosed() throws SQLException {
        return closed;
    }

    @Override
    public boolean isValid(int timeout) throws SQLException {
        if (closed) return false;
        synchronized (sendLock) {
            try {
                Frame ping = Codec.encodePing(System.nanoTime());
                ping.write(out);
                Frame resp = Frame.read(in);
                return resp != null && resp.getType() == Codec.TYPE_PONG;
            } catch (IOException e) {
                return false;
            }
        }
    }

    @Override
    public DatabaseMetaData getMetaData() throws SQLException {
        checkOpen();
        return new TinyDatabaseMetaData(this);
    }

    @Override
    public void setCatalog(String catalog) throws SQLException {
        checkOpen();
        this.catalog = catalog;
    }

    @Override
    public String getCatalog() throws SQLException {
        return catalog;
    }

    void checkOpen() throws SQLException {
        if (closed) throw new SQLException("connection is closed", "08000");
    }
}
