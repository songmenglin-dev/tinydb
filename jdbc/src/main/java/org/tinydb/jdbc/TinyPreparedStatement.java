package org.tinydb.jdbc;

import org.tinydb.jdbc.protocol.Codec;

import java.io.InputStream;
import java.io.Reader;
import java.math.BigDecimal;
import java.net.URL;
import java.sql.Array;
import java.sql.Blob;
import java.sql.Clob;
import java.sql.Date;
import java.sql.NClob;
import java.sql.ParameterMetaData;
import java.sql.PreparedStatement;
import java.sql.Ref;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.RowId;
import java.sql.SQLException;
import java.sql.SQLXML;
import java.sql.Time;
import java.sql.Timestamp;
import java.sql.Types;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.List;

/**
 * JDBC PreparedStatement. Binds parameters and sends via EXEC frame.
 */
public class TinyPreparedStatement extends TinyStatement implements PreparedStatement {
    private final String sql;
    private final List<Codec.Param> parameters = new ArrayList<>();
    private int paramCount = -1;

    public TinyPreparedStatement(TinyConnection connection, String sql) {
        super(connection);
        this.sql = sql;
        // Count placeholders, ignoring those inside string literals.
        // SQL standard escapes a single quote inside a string as ``''``
        // (two adjacent apostrophes); we must skip both bytes together
        // so that ``'it''s a ?'`` does not register a phantom parameter.
        int count = 0;
        boolean inLiteral = false;
        for (int i = 0; i < sql.length(); i++) {
            char c = sql.charAt(i);
            if (inLiteral) {
                if (c == '\'') {
                    if (i + 1 < sql.length() && sql.charAt(i + 1) == '\'') {
                        i++; // escaped quote: skip the second one
                    } else {
                        inLiteral = false;
                    }
                }
                continue;
            }
            if (c == '\'') {
                inLiteral = true;
            } else if (c == '?') {
                count++;
            }
        }
        paramCount = count;
        for (int i = 0; i < count; i++) {
            parameters.add(Codec.Param.nullParam());
        }
    }

    @Override
    public void clearParameters() throws SQLException {
        for (int i = 0; i < parameters.size(); i++) {
            parameters.set(i, Codec.Param.nullParam());
        }
    }

    private void ensureIndex(int parameterIndex) throws SQLException {
        if (parameterIndex < 1 || parameterIndex > parameters.size()) {
            throw new SQLException("parameter index out of range: " + parameterIndex, "HY000");
        }
    }

    @Override
    public void setNull(int parameterIndex, int sqlType) throws SQLException {
        ensureIndex(parameterIndex);
        parameters.set(parameterIndex - 1, Codec.Param.nullParam());
    }

    @Override
    public void setBoolean(int parameterIndex, boolean x) throws SQLException {
        ensureIndex(parameterIndex);
        parameters.set(parameterIndex - 1, Codec.Param.bool(x));
    }

    @Override
    public void setByte(int parameterIndex, byte x) throws SQLException {
        setInt(parameterIndex, x);
    }

    @Override
    public void setShort(int parameterIndex, short x) throws SQLException {
        setInt(parameterIndex, x);
    }

    @Override
    public void setInt(int parameterIndex, int x) throws SQLException {
        ensureIndex(parameterIndex);
        parameters.set(parameterIndex - 1, Codec.Param.int64(x));
    }

    @Override
    public void setLong(int parameterIndex, long x) throws SQLException {
        ensureIndex(parameterIndex);
        parameters.set(parameterIndex - 1, Codec.Param.int64(x));
    }

    @Override
    public void setFloat(int parameterIndex, float x) throws SQLException {
        setDouble(parameterIndex, x);
    }

    @Override
    public void setDouble(int parameterIndex, double x) throws SQLException {
        ensureIndex(parameterIndex);
        parameters.set(parameterIndex - 1, Codec.Param.float64(x));
    }

    @Override
    public void setBigDecimal(int parameterIndex, BigDecimal x) throws SQLException {
        if (x == null) setNull(parameterIndex, Types.DECIMAL);
        else setString(parameterIndex, x.toPlainString());
    }

    @Override
    public void setString(int parameterIndex, String x) throws SQLException {
        ensureIndex(parameterIndex);
        parameters.set(parameterIndex - 1, Codec.Param.string(x));
    }

    @Override
    public void setBytes(int parameterIndex, byte[] x) throws SQLException {
        if (x == null) setNull(parameterIndex, Types.BINARY);
        else setString(parameterIndex, new String(x));
    }

    @Override
    public void setDate(int parameterIndex, Date x) throws SQLException {
        if (x == null) setNull(parameterIndex, Types.DATE);
        else setString(parameterIndex, x.toString());
    }

    @Override
    public void setTime(int parameterIndex, Time x) throws SQLException {
        if (x == null) setNull(parameterIndex, Types.TIME);
        else setString(parameterIndex, x.toString());
    }

    @Override
    public void setTimestamp(int parameterIndex, Timestamp x) throws SQLException {
        if (x == null) setNull(parameterIndex, Types.TIMESTAMP);
        else setString(parameterIndex, x.toString());
    }

    @Override
    public void setAsciiStream(int parameterIndex, InputStream x, int length) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setUnicodeStream(int parameterIndex, InputStream x, int length) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setBinaryStream(int parameterIndex, InputStream x, int length) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setObject(int parameterIndex, Object x, int targetSqlType) throws SQLException {
        setObject(parameterIndex, x);
    }

    @Override
    public void setObject(int parameterIndex, Object x) throws SQLException {
        if (x == null) setNull(parameterIndex, Types.NULL);
        else if (x instanceof String) setString(parameterIndex, (String) x);
        else if (x instanceof Integer) setInt(parameterIndex, (Integer) x);
        else if (x instanceof Long) setLong(parameterIndex, (Long) x);
        else if (x instanceof Short) setShort(parameterIndex, (Short) x);
        else if (x instanceof Byte) setByte(parameterIndex, (Byte) x);
        else if (x instanceof Double) setDouble(parameterIndex, (Double) x);
        else if (x instanceof Float) setFloat(parameterIndex, (Float) x);
        else if (x instanceof Boolean) setBoolean(parameterIndex, (Boolean) x);
        else if (x instanceof BigDecimal) setBigDecimal(parameterIndex, (BigDecimal) x);
        else if (x instanceof Date) setDate(parameterIndex, (Date) x);
        else if (x instanceof Time) setTime(parameterIndex, (Time) x);
        else if (x instanceof Timestamp) setTimestamp(parameterIndex, (Timestamp) x);
        else if (x instanceof byte[]) setBytes(parameterIndex, (byte[]) x);
        else setString(parameterIndex, x.toString());
    }

    @Override
    public void setObject(int parameterIndex, Object x, int targetSqlType, int scaleOrLength) throws SQLException {
        setObject(parameterIndex, x);
    }

    @Override
    public ResultSet executeQuery() throws SQLException {
        checkOpen();
        TinyConnection.QueryResult r = connection.sendExec(sql, new ArrayList<>(parameters));
        if (!r.hasHeader) throw new SQLException("query did not return a result set", "HY000");
        currentResultSet = new TinyResultSet(r.columns, r.rows);
        updateCount = -1;
        updateCountOverflow = false;
        return currentResultSet;
    }

    @Override
    public int executeUpdate() throws SQLException {
        checkOpen();
        TinyConnection.QueryResult r = connection.sendExec(sql, new ArrayList<>(parameters));
        currentResultSet = null;
        recordUpdateCount(r.rowcount);
        return (int) updateCount;
    }

    @Override
    public boolean execute() throws SQLException {
        checkOpen();
        TinyConnection.QueryResult r = connection.sendExec(sql, new ArrayList<>(parameters));
        if (r.hasHeader) {
            currentResultSet = new TinyResultSet(r.columns, r.rows);
            updateCount = -1;
            updateCountOverflow = false;
            return true;
        }
        currentResultSet = null;
        recordUpdateCount(r.rowcount);
        return false;
    }

    @Override
    public void addBatch() throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setCharacterStream(int parameterIndex, Reader reader, int length) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setRef(int parameterIndex, Ref x) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setBlob(int parameterIndex, Blob x) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setClob(int parameterIndex, Clob x) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setArray(int parameterIndex, Array x) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public ResultSetMetaData getMetaData() throws SQLException {
        checkOpen();
        if (currentResultSet == null) return null;
        return currentResultSet.getMetaData();
    }

    @Override
    public void setDate(int parameterIndex, Date x, Calendar cal) throws SQLException {
        setDate(parameterIndex, x);
    }

    @Override
    public void setTime(int parameterIndex, Time x, Calendar cal) throws SQLException {
        setTime(parameterIndex, x);
    }

    @Override
    public void setTimestamp(int parameterIndex, Timestamp x, Calendar cal) throws SQLException {
        setTimestamp(parameterIndex, x);
    }

    @Override
    public void setNull(int parameterIndex, int sqlType, String typeName) throws SQLException {
        setNull(parameterIndex, sqlType);
    }

    @Override
    public void setURL(int parameterIndex, URL x) throws SQLException {
        setString(parameterIndex, x == null ? null : x.toString());
    }

    @Override
    public ParameterMetaData getParameterMetaData() throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setRowId(int parameterIndex, RowId x) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setNString(int parameterIndex, String value) throws SQLException {
        setString(parameterIndex, value);
    }

    @Override
    public void setNCharacterStream(int parameterIndex, Reader value, long length) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setNClob(int parameterIndex, NClob value) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setClob(int parameterIndex, Reader reader, long length) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setBlob(int parameterIndex, InputStream inputStream, long length) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setNClob(int parameterIndex, Reader reader, long length) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setSQLXML(int parameterIndex, SQLXML xmlObject) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setAsciiStream(int parameterIndex, InputStream x, long length) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setBinaryStream(int parameterIndex, InputStream x, long length) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setCharacterStream(int parameterIndex, Reader reader, long length) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setAsciiStream(int parameterIndex, InputStream x) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setBinaryStream(int parameterIndex, InputStream x) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setCharacterStream(int parameterIndex, Reader reader) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setNCharacterStream(int parameterIndex, Reader value) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setClob(int parameterIndex, Reader reader) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setBlob(int parameterIndex, InputStream inputStream) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    @Override
    public void setNClob(int parameterIndex, Reader reader) throws SQLException {
        throw new SQLException("not supported in v0.3", "HY000");
    }

    public List<Codec.Param> getParameters() { return parameters; }
    public int getParameterCount() { return paramCount; }
}
