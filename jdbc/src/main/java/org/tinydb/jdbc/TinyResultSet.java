package org.tinydb.jdbc;

import org.tinydb.jdbc.protocol.Codec;

import java.math.BigDecimal;
import java.sql.Date;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Time;
import java.sql.Timestamp;
import java.sql.Types;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class TinyResultSet implements ResultSet {

    @Override
    public void updateBytes(java.lang.String p0, byte[] p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateBytes(int p0, byte[] p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.Array getArray(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.Array getArray(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.net.URL getURL(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.net.URL getURL(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getType() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.Ref getRef(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.Ref getRef(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean previous() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean first() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.io.InputStream getAsciiStream(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.io.InputStream getAsciiStream(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.io.InputStream getUnicodeStream(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.io.InputStream getUnicodeStream(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.io.InputStream getBinaryStream(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.io.InputStream getBinaryStream(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.SQLWarning getWarnings() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void clearWarnings() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.lang.String getCursorName() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.io.Reader getCharacterStream(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.io.Reader getCharacterStream(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void beforeFirst() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void afterLast() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean last() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean absolute(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean relative(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void setFetchDirection(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getFetchDirection() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void setFetchSize(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getFetchSize() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getConcurrency() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean rowUpdated() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean rowInserted() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean rowDeleted() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateNull(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateNull(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateBoolean(java.lang.String p0, boolean p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateBoolean(int p0, boolean p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateByte(int p0, byte p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateByte(java.lang.String p0, byte p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateShort(java.lang.String p0, short p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateShort(int p0, short p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateInt(java.lang.String p0, int p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateInt(int p0, int p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateLong(java.lang.String p0, long p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateLong(int p0, long p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateFloat(java.lang.String p0, float p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateFloat(int p0, float p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateDouble(int p0, double p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateDouble(java.lang.String p0, double p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateBigDecimal(int p0, java.math.BigDecimal p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateBigDecimal(java.lang.String p0, java.math.BigDecimal p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateString(int p0, java.lang.String p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateString(java.lang.String p0, java.lang.String p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateDate(java.lang.String p0, java.sql.Date p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateDate(int p0, java.sql.Date p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateTime(java.lang.String p0, java.sql.Time p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateTime(int p0, java.sql.Time p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateTimestamp(java.lang.String p0, java.sql.Timestamp p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateTimestamp(int p0, java.sql.Timestamp p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateAsciiStream(java.lang.String p0, java.io.InputStream p1, long p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateAsciiStream(java.lang.String p0, java.io.InputStream p1, int p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateAsciiStream(int p0, java.io.InputStream p1, long p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateAsciiStream(int p0, java.io.InputStream p1, int p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateAsciiStream(int p0, java.io.InputStream p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateAsciiStream(java.lang.String p0, java.io.InputStream p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateBinaryStream(int p0, java.io.InputStream p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateBinaryStream(int p0, java.io.InputStream p1, long p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateBinaryStream(int p0, java.io.InputStream p1, int p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateBinaryStream(java.lang.String p0, java.io.InputStream p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateBinaryStream(java.lang.String p0, java.io.InputStream p1, int p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateBinaryStream(java.lang.String p0, java.io.InputStream p1, long p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateCharacterStream(java.lang.String p0, java.io.Reader p1, int p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateCharacterStream(int p0, java.io.Reader p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateCharacterStream(int p0, java.io.Reader p1, long p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateCharacterStream(java.lang.String p0, java.io.Reader p1, long p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateCharacterStream(java.lang.String p0, java.io.Reader p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateCharacterStream(int p0, java.io.Reader p1, int p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateObject(java.lang.String p0, java.lang.Object p1, int p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateObject(int p0, java.lang.Object p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateObject(int p0, java.lang.Object p1, int p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateObject(java.lang.String p0, java.lang.Object p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void insertRow() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateRow() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void deleteRow() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void refreshRow() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void cancelRowUpdates() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void moveToInsertRow() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void moveToCurrentRow() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.Statement getStatement() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.Blob getBlob(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.Blob getBlob(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.Clob getClob(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.Clob getClob(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateRef(int p0, java.sql.Ref p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateRef(java.lang.String p0, java.sql.Ref p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateBlob(java.lang.String p0, java.io.InputStream p1, long p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateBlob(java.lang.String p0, java.io.InputStream p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateBlob(int p0, java.io.InputStream p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateBlob(int p0, java.io.InputStream p1, long p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateBlob(java.lang.String p0, java.sql.Blob p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateBlob(int p0, java.sql.Blob p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateClob(java.lang.String p0, java.sql.Clob p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateClob(int p0, java.sql.Clob p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateClob(int p0, java.io.Reader p1, long p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateClob(int p0, java.io.Reader p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateClob(java.lang.String p0, java.io.Reader p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateClob(java.lang.String p0, java.io.Reader p1, long p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateArray(int p0, java.sql.Array p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateArray(java.lang.String p0, java.sql.Array p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.RowId getRowId(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.RowId getRowId(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateRowId(int p0, java.sql.RowId p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateRowId(java.lang.String p0, java.sql.RowId p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getHoldability() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateNString(java.lang.String p0, java.lang.String p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateNString(int p0, java.lang.String p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateNClob(java.lang.String p0, java.io.Reader p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateNClob(int p0, java.io.Reader p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateNClob(int p0, java.sql.NClob p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateNClob(java.lang.String p0, java.io.Reader p1, long p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateNClob(java.lang.String p0, java.sql.NClob p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateNClob(int p0, java.io.Reader p1, long p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.NClob getNClob(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.NClob getNClob(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.SQLXML getSQLXML(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.SQLXML getSQLXML(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateSQLXML(java.lang.String p0, java.sql.SQLXML p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateSQLXML(int p0, java.sql.SQLXML p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.lang.String getNString(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.lang.String getNString(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.io.Reader getNCharacterStream(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.io.Reader getNCharacterStream(java.lang.String p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateNCharacterStream(int p0, java.io.Reader p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateNCharacterStream(java.lang.String p0, java.io.Reader p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateNCharacterStream(java.lang.String p0, java.io.Reader p1, long p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public void updateNCharacterStream(int p0, java.io.Reader p1, long p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }


    @Override
    public <T> T unwrap(Class<T> iface) throws SQLException {
        if (iface.isInstance(this)) return iface.cast(this);
        throw new SQLException("not a wrapper for " + iface.getName(), "HY000");
    }

    @Override
    public boolean isWrapperFor(Class<?> iface) throws SQLException {
        return iface.isInstance(this);
    }

    private final List<Codec.Column> columns;
    private final List<List<Object>> rows;
    private final Map<String, Integer> columnIndexByName;
    private int currentRow = -1;
    private boolean closed = false;
    private boolean lastWasNull = false;

    public TinyResultSet(List<Codec.Column> columns, List<List<Object>> rows) {
        // Defensive copy: ``columns`` and ``rows`` are both optional in the
        // wire protocol (e.g. an EXEC that returns no result set) and may be
        // null when handed to us.  Normalising here lets every downstream
        // accessor (``getMetaData``, ``findColumn``, etc.) skip its own
        // null check.
        this.columns = columns != null ? columns : java.util.Collections.emptyList();
        this.rows = rows != null ? rows : java.util.Collections.emptyList();
        this.columnIndexByName = new HashMap<>();
        for (int i = 0; i < this.columns.size(); i++) {
            columnIndexByName.put(this.columns.get(i).name.toLowerCase(), i + 1);
        }
    }

    private void checkOpen() throws SQLException {
        if (closed) throw new SQLException("result set is closed", "HY000");
    }

    @Override
    public boolean next() throws SQLException {
        checkOpen();
        if (currentRow + 1 < rows.size()) {
            currentRow++;
            lastWasNull = false;
            return true;
        }
        // Past last row
        currentRow = rows.size();
        return false;
    }

    @Override
    public void close() throws SQLException { closed = true; }

    @Override
    public boolean isClosed() throws SQLException { return closed; }

    @Override
    public boolean wasNull() throws SQLException { return lastWasNull; }

    @Override
    public int findColumn(String columnLabel) throws SQLException {
        checkOpen();
        if (columnLabel == null) {
            throw new SQLException("columnLabel is null", "HY000");
        }
        Integer idx = columnIndexByName.get(columnLabel.toLowerCase());
        if (idx == null) throw new SQLException("column not found: " + columnLabel, "HY000");
        return idx;
    }

    private Object getValue(int columnIndex) throws SQLException {
        checkOpen();
        if (currentRow < 0 || currentRow >= rows.size()) {
            throw new SQLException("no current row", "HY000");
        }
        if (columnIndex < 1 || columnIndex > columns.size()) {
            throw new SQLException("column index out of range: " + columnIndex, "HY000");
        }
        Object v = rows.get(currentRow).get(columnIndex - 1);
        lastWasNull = (v == null);
        return v;
    }

    private Object getValueByName(String columnLabel) throws SQLException {
        return getValue(findColumn(columnLabel));
    }

    @Override
    public String getString(int columnIndex) throws SQLException {
        Object v = getValue(columnIndex);
        if (v == null) return null;
        if (v instanceof String) return (String) v;
        return v.toString();
    }

    @Override
    public String getString(String columnLabel) throws SQLException {
        Object v = getValueByName(columnLabel);
        if (v == null) return null;
        if (v instanceof String) return (String) v;
        return v.toString();
    }

    @Override
    public int getInt(int columnIndex) throws SQLException {
        Object v = getValue(columnIndex);
        if (v == null) return 0;
        if (v instanceof Long) {
            long lv = (Long) v;
            if (lv < Integer.MIN_VALUE || lv > Integer.MAX_VALUE) {
                throw new SQLException("value " + lv + " does not fit in int", "22000");
            }
            return (int) lv;
        }
        if (v instanceof Integer) return (Integer) v;
        if (v instanceof Number) return ((Number) v).intValue();
        try {
            return Integer.parseInt(v.toString());
        } catch (NumberFormatException nfe) {
            throw new SQLException("value not an int: " + v, "22000", nfe);
        }
    }

    @Override
    public int getInt(String columnLabel) throws SQLException {
        Object v = getValueByName(columnLabel);
        if (v == null) return 0;
        if (v instanceof Long) {
            long lv = (Long) v;
            if (lv < Integer.MIN_VALUE || lv > Integer.MAX_VALUE) {
                throw new SQLException("value " + lv + " does not fit in int", "22000");
            }
            return (int) lv;
        }
        if (v instanceof Integer) return (Integer) v;
        if (v instanceof Number) return ((Number) v).intValue();
        try {
            return Integer.parseInt(v.toString());
        } catch (NumberFormatException nfe) {
            throw new SQLException("value not an int: " + v, "22000", nfe);
        }
    }

    @Override
    public long getLong(int columnIndex) throws SQLException {
        Object v = getValue(columnIndex);
        if (v == null) return 0L;
        if (v instanceof Long) return (Long) v;
        if (v instanceof Number) return ((Number) v).longValue();
        return Long.parseLong(v.toString());
    }

    @Override
    public long getLong(String columnLabel) throws SQLException {
        Object v = getValueByName(columnLabel);
        if (v == null) return 0L;
        if (v instanceof Long) return (Long) v;
        if (v instanceof Number) return ((Number) v).longValue();
        return Long.parseLong(v.toString());
    }

    @Override
    public double getDouble(int columnIndex) throws SQLException {
        Object v = getValue(columnIndex);
        if (v == null) return 0.0;
        if (v instanceof Double) return (Double) v;
        if (v instanceof Number) return ((Number) v).doubleValue();
        return Double.parseDouble(v.toString());
    }

    @Override
    public double getDouble(String columnLabel) throws SQLException {
        Object v = getValueByName(columnLabel);
        if (v == null) return 0.0;
        if (v instanceof Double) return (Double) v;
        if (v instanceof Number) return ((Number) v).doubleValue();
        return Double.parseDouble(v.toString());
    }

    @Override
    public boolean getBoolean(int columnIndex) throws SQLException {
        Object v = getValue(columnIndex);
        if (v == null) return false;
        if (v instanceof Boolean) return (Boolean) v;
        if (v instanceof Number) return ((Number) v).intValue() != 0;
        return Boolean.parseBoolean(v.toString());
    }

    @Override
    public boolean getBoolean(String columnLabel) throws SQLException {
        Object v = getValueByName(columnLabel);
        if (v == null) return false;
        if (v instanceof Boolean) return (Boolean) v;
        if (v instanceof Number) return ((Number) v).intValue() != 0;
        return Boolean.parseBoolean(v.toString());
    }

    @Override
    public Object getObject(int columnIndex) throws SQLException { return getValue(columnIndex); }

    @Override
    public Object getObject(String columnLabel) throws SQLException { return getValueByName(columnLabel); }

    @Override
    public <T> T getObject(int columnIndex, Class<T> type) throws SQLException {
        return type.cast(getValue(columnIndex));
    }

    @Override
    public <T> T getObject(String columnLabel, Class<T> type) throws SQLException {
        return type.cast(getValueByName(columnLabel));
    }

    @Override
    public Object getObject(String columnLabel, Map<String, Class<?>> map) throws SQLException {
        return getValueByName(columnLabel);
    }

    @Override
    public Object getObject(int columnIndex, Map<String, Class<?>> map) throws SQLException {
        return getValue(columnIndex);
    }

    @Override
    public ResultSetMetaData getMetaData() throws SQLException {
        checkOpen();
        // If the server returned no columns (e.g. an EXEC that produced
        // no result set), surface an empty metadata object rather than
        // letting ``columns.get(...)`` blow up downstream.
        final List<Codec.Column> safeColumns = columns;
        return new ResultSetMetaData() {
            @Override public int getColumnCount() { return columns.size(); }
            @Override public String getColumnName(int column) { return columns.get(column - 1).name; }
            @Override public String getColumnLabel(int column) { return columns.get(column - 1).name; }
            @Override public int getColumnType(int column) { return TinyTypes.wireCodeToJdbc(columns.get(column - 1).type); }
            @Override public String getColumnTypeName(int column) {
                byte t = columns.get(column - 1).type;
                switch (t) {
                    case Codec.WIRE_NULL: return "NULL";
                    case Codec.WIRE_INT64: return "INT64";
                    case Codec.WIRE_FLOAT64: return "FLOAT64";
                    case Codec.WIRE_STRING: return "STRING";
                    case Codec.WIRE_BOOL: return "BOOL";
                    default: return "UNKNOWN";
                }
            }
            @Override public String getColumnClassName(int column) {
                int jdbcType = getColumnType(column);
                switch (jdbcType) {
                    case Types.BIGINT: return Long.class.getName();
                    case Types.DOUBLE: return Double.class.getName();
                    case Types.VARCHAR: return String.class.getName();
                    case Types.BOOLEAN: return Boolean.class.getName();
                    default: return Object.class.getName();
                }
            }
            @Override public boolean isAutoIncrement(int column) { return false; }
            @Override public boolean isCaseSensitive(int column) { return true; }
            @Override public boolean isSearchable(int column) { return true; }
            @Override public boolean isCurrency(int column) { return false; }
            @Override public int isNullable(int column) { return columnNullable; }
            @Override public boolean isSigned(int column) { return true; }
            @Override public int getColumnDisplaySize(int column) { return 32; }
            @Override public String getSchemaName(int column) { return ""; }
            @Override public int getPrecision(int column) { return 0; }
            @Override public int getScale(int column) { return 0; }
            @Override public String getTableName(int column) { return ""; }
            @Override public String getCatalogName(int column) { return ""; }
            @Override public boolean isReadOnly(int column) { return true; }
            @Override public boolean isWritable(int column) { return false; }
            @Override public boolean isDefinitelyWritable(int column) { return false; }
            @Override public <T> T unwrap(Class<T> iface) throws SQLException {
                if (iface.isInstance(this)) return iface.cast(this);
                throw new SQLException("not a wrapper");
            }
            @Override public boolean isWrapperFor(Class<?> iface) throws SQLException {
                return iface.isInstance(this);
            }
        };
    }

    @Override
    public boolean isBeforeFirst() { return currentRow < 0 && rows.size() > 0; }
    @Override
    public boolean isAfterLast() { return currentRow >= rows.size() && rows.size() > 0; }
    @Override
    public boolean isFirst() { return currentRow == 0; }
    @Override
    public boolean isLast() { return currentRow == rows.size() - 1; }
    @Override
    public int getRow() { return currentRow + 1; }
    @Override
    public byte getByte(int columnIndex) throws SQLException {
        int v = getInt(columnIndex);
        // ``getInt`` already throws on overflow vs Integer; here we additionally
        // surface ``SQLFeatureNotSupportedException``-style narrowing errors
        // when the int itself doesn't fit in a byte.
        if (v < Byte.MIN_VALUE || v > Byte.MAX_VALUE) {
            throw new SQLException("value " + v + " does not fit in byte", "22000");
        }
        return (byte) v;
    }
    @Override
    public byte getByte(String columnLabel) throws SQLException {
        int v = getInt(columnLabel);
        if (v < Byte.MIN_VALUE || v > Byte.MAX_VALUE) {
            throw new SQLException("value " + v + " does not fit in byte", "22000");
        }
        return (byte) v;
    }
    @Override
    public short getShort(int columnIndex) throws SQLException {
        int v = getInt(columnIndex);
        if (v < Short.MIN_VALUE || v > Short.MAX_VALUE) {
            throw new SQLException("value " + v + " does not fit in short", "22000");
        }
        return (short) v;
    }
    @Override
    public short getShort(String columnLabel) throws SQLException {
        int v = getInt(columnLabel);
        if (v < Short.MIN_VALUE || v > Short.MAX_VALUE) {
            throw new SQLException("value " + v + " does not fit in short", "22000");
        }
        return (short) v;
    }
    @Override
    public float getFloat(int columnIndex) throws SQLException { return (float) getDouble(columnIndex); }
    @Override
    public float getFloat(String columnLabel) throws SQLException { return (float) getDouble(columnLabel); }
    @Override
    public BigDecimal getBigDecimal(int columnIndex, int scale) throws SQLException {
        return new BigDecimal(getString(columnIndex));
    }
    @Override
    public BigDecimal getBigDecimal(String columnLabel, int scale) throws SQLException {
        return new BigDecimal(getString(columnLabel));
    }
    @Override
    public BigDecimal getBigDecimal(int columnIndex) throws SQLException {
        String s = getString(columnIndex);
        return s == null ? null : new BigDecimal(s);
    }
    @Override
    public BigDecimal getBigDecimal(String columnLabel) throws SQLException {
        String s = getString(columnLabel);
        return s == null ? null : new BigDecimal(s);
    }
    @Override
    public byte[] getBytes(int columnIndex) throws SQLException {
        String s = getString(columnIndex);
        return s == null ? null : s.getBytes();
    }
    @Override
    public byte[] getBytes(String columnLabel) throws SQLException {
        String s = getString(columnLabel);
        return s == null ? null : s.getBytes();
    }
    @Override
    public Date getDate(int columnIndex) throws SQLException {
        String s = getString(columnIndex);
        return s == null ? null : parseDate(s);
    }
    @Override
    public Date getDate(String columnLabel) throws SQLException {
        String s = getString(columnLabel);
        return s == null ? null : parseDate(s);
    }
    @Override
    public Date getDate(int columnIndex, java.util.Calendar cal) throws SQLException {
        return getDate(columnIndex);
    }
    @Override
    public Date getDate(String columnLabel, java.util.Calendar cal) throws SQLException {
        return getDate(columnLabel);
    }
    @Override
    public Time getTime(int columnIndex) throws SQLException {
        String s = getString(columnIndex);
        return s == null ? null : parseTime(s);
    }
    @Override
    public Time getTime(String columnLabel) throws SQLException {
        String s = getString(columnLabel);
        return s == null ? null : parseTime(s);
    }
    @Override
    public Time getTime(int columnIndex, java.util.Calendar cal) throws SQLException {
        return getTime(columnIndex);
    }
    @Override
    public Time getTime(String columnLabel, java.util.Calendar cal) throws SQLException {
        return getTime(columnLabel);
    }
    @Override
    public Timestamp getTimestamp(int columnIndex) throws SQLException {
        String s = getString(columnIndex);
        return s == null ? null : parseTimestamp(s);
    }
    @Override
    public Timestamp getTimestamp(String columnLabel) throws SQLException {
        String s = getString(columnLabel);
        return s == null ? null : parseTimestamp(s);
    }
    @Override
    public Timestamp getTimestamp(int columnIndex, java.util.Calendar cal) throws SQLException {
        return getTimestamp(columnIndex);
    }
    @Override
    public Timestamp getTimestamp(String columnLabel, java.util.Calendar cal) throws SQLException {
        return getTimestamp(columnLabel);
    }

    /**
     * ``Date.valueOf`` throws ``IllegalArgumentException`` for malformed
     * input; wrap it as a ``SQLDataException`` (SQLSTATE 22000) so JDBC
     * callers can handle it uniformly.
     */
    private static Date parseDate(String s) throws SQLException {
        try {
            return Date.valueOf(s);
        } catch (IllegalArgumentException iae) {
            throw new SQLException("invalid date value: " + s, "22000", iae);
        }
    }

    private static Time parseTime(String s) throws SQLException {
        try {
            return Time.valueOf(s);
        } catch (IllegalArgumentException iae) {
            throw new SQLException("invalid time value: " + s, "22000", iae);
        }
    }

    private static Timestamp parseTimestamp(String s) throws SQLException {
        try {
            return Timestamp.valueOf(s);
        } catch (IllegalArgumentException iae) {
            throw new SQLException("invalid timestamp value: " + s, "22000", iae);
        }
    }
}
