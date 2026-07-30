package org.tinydb.jdbc;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.tinydb.jdbc.protocol.Codec;

import java.math.BigDecimal;
import java.sql.Date;
import java.sql.SQLException;
import java.sql.Time;
import java.sql.Timestamp;
import java.sql.Types;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TinyResultSetTest {

    private static TinyResultSet makeResultSet() {
        List<Codec.Column> cols = new ArrayList<>();
        cols.add(new Codec.Column("id", Codec.WIRE_INT64));
        cols.add(new Codec.Column("name", Codec.WIRE_STRING));
        cols.add(new Codec.Column("val", Codec.WIRE_FLOAT64));
        cols.add(new Codec.Column("flag", Codec.WIRE_BOOL));
        cols.add(new Codec.Column("nullable", Codec.WIRE_STRING));
        List<List<Object>> rows = new ArrayList<>();
        rows.add(Arrays.asList(1L, "alice", 3.14, true, null));
        rows.add(Arrays.asList(2L, "bob", 2.71, false, "x"));
        return new TinyResultSet(cols, rows);
    }

    @Test
    @DisplayName("next advances cursor and returns true while row is available")
    void testNext() throws SQLException {
        TinyResultSet rs = makeResultSet();
        assertTrue(rs.next());
        assertTrue(rs.next());
        assertFalse(rs.next());
    }

    @Test
    @DisplayName("getString returns string value")
    void testGetString() throws SQLException {
        TinyResultSet rs = makeResultSet();
        rs.next();
        assertEquals("alice", rs.getString("name"));
        assertEquals("alice", rs.getString(2));
    }

    @Test
    @DisplayName("getInt returns int value")
    void testGetInt() throws SQLException {
        TinyResultSet rs = makeResultSet();
        rs.next();
        assertEquals(1, rs.getInt("id"));
        assertEquals(1, rs.getInt(1));
    }

    @Test
    @DisplayName("getLong returns long value")
    void testGetLong() throws SQLException {
        TinyResultSet rs = makeResultSet();
        rs.next();
        assertEquals(1L, rs.getLong("id"));
    }

    @Test
    @DisplayName("getDouble returns double value")
    void testGetDouble() throws SQLException {
        TinyResultSet rs = makeResultSet();
        rs.next();
        assertEquals(3.14, rs.getDouble("val"), 0.001);
    }

    @Test
    @DisplayName("getBoolean returns boolean value")
    void testGetBoolean() throws SQLException {
        TinyResultSet rs = makeResultSet();
        rs.next();
        assertTrue(rs.getBoolean("flag"));
        rs.next();
        assertFalse(rs.getBoolean("flag"));
    }

    @Test
    @DisplayName("wasNull returns true after accessing null column")
    void testWasNull() throws SQLException {
        TinyResultSet rs = makeResultSet();
        rs.next();
        assertNull(rs.getString("nullable"));
        assertTrue(rs.wasNull());
        rs.next();
        assertEquals("x", rs.getString("nullable"));
        assertFalse(rs.wasNull());
    }

    @Test
    @DisplayName("findColumn is case-insensitive")
    void testFindColumnCaseInsensitive() throws SQLException {
        TinyResultSet rs = makeResultSet();
        assertEquals(1, rs.findColumn("ID"));
        assertEquals(1, rs.findColumn("id"));
        assertEquals(2, rs.findColumn("NAME"));
        assertEquals(5, rs.findColumn("Nullable"));
    }

    @Test
    @DisplayName("findColumn throws if column not found")
    void testFindColumnNotFound() {
        TinyResultSet rs = makeResultSet();
        assertThrows(SQLException.class, () -> rs.findColumn("nope"));
    }

    @Test
    @DisplayName("getMetaData returns column metadata")
    void testGetMetaData() throws SQLException {
        TinyResultSet rs = makeResultSet();
        java.sql.ResultSetMetaData md = rs.getMetaData();
        assertNotNull(md);
        assertEquals(5, md.getColumnCount());
        assertEquals("id", md.getColumnName(1));
        assertEquals("name", md.getColumnName(2));
        assertEquals(Types.BIGINT, md.getColumnType(1));
        assertEquals(Types.VARCHAR, md.getColumnType(2));
        assertEquals(Types.DOUBLE, md.getColumnType(3));
        assertEquals(Types.BOOLEAN, md.getColumnType(4));
        assertEquals(Long.class.getName(), md.getColumnClassName(1));
        assertEquals(String.class.getName(), md.getColumnClassName(2));
    }

    @Test
    @DisplayName("getByte / getShort / getFloat coerce from int / double")
    void testCoercions() throws SQLException {
        TinyResultSet rs = makeResultSet();
        rs.next();
        assertEquals((byte) 1, rs.getByte("id"));
        assertEquals((short) 1, rs.getShort("id"));
        assertEquals(3.14f, rs.getFloat("val"), 0.001);
    }

    @Test
    @DisplayName("getBigDecimal returns BigDecimal")
    void testGetBigDecimal() throws SQLException {
        TinyResultSet rs = makeResultSet();
        rs.next();
        assertEquals(new BigDecimal("3.14"), rs.getBigDecimal("val"));
    }

    @Test
    @DisplayName("getBytes returns string bytes")
    void testGetBytes() throws SQLException {
        TinyResultSet rs = makeResultSet();
        rs.next();
        assertArrayEqualsEquals("alice".getBytes(), rs.getBytes("name"));
    }

    @Test
    @DisplayName("getDate / getTime / getTimestamp parse from string")
    void testDateTimeGetters() throws SQLException {
        List<Codec.Column> cols = new ArrayList<>();
        cols.add(new Codec.Column("d", Codec.WIRE_STRING));
        cols.add(new Codec.Column("t", Codec.WIRE_STRING));
        cols.add(new Codec.Column("ts", Codec.WIRE_STRING));
        List<List<Object>> rows = new ArrayList<>();
        rows.add(Arrays.asList("2024-01-01", "12:30:00", "2024-01-01 12:30:00.0"));
        TinyResultSet rs = new TinyResultSet(cols, rows);
        rs.next();
        assertEquals(Date.valueOf("2024-01-01"), rs.getDate("d"));
        assertEquals(Time.valueOf("12:30:00"), rs.getTime("t"));
        assertEquals(Timestamp.valueOf("2024-01-01 12:30:00.0"), rs.getTimestamp("ts"));
    }

    @Test
    @DisplayName("getObject(int) returns the raw value")
    void testGetObject() throws SQLException {
        TinyResultSet rs = makeResultSet();
        rs.next();
        assertEquals(1L, rs.getObject(1));
        assertEquals("alice", rs.getObject(2));
    }

    @Test
    @DisplayName("getObject(int, Class) returns cast value")
    void testGetObjectTyped() throws SQLException {
        TinyResultSet rs = makeResultSet();
        rs.next();
        assertEquals(Long.valueOf(1L), rs.getObject(1, Long.class));
        assertEquals("alice", rs.getObject(2, String.class));
    }

    @Test
    @DisplayName("getObject with map returns the raw value")
    void testGetObjectWithMap() throws SQLException {
        TinyResultSet rs = makeResultSet();
        rs.next();
        Map<String, Class<?>> m = new HashMap<>();
        assertEquals(1L, rs.getObject(1, m));
        assertEquals("alice", rs.getObject("name", m));
    }

    @Test
    @DisplayName("close marks result set as closed")
    void testClose() throws SQLException {
        TinyResultSet rs = makeResultSet();
        assertFalse(rs.isClosed());
        rs.close();
        assertTrue(rs.isClosed());
    }

    @Test
    @DisplayName("Operations on closed result set throw")
    void testClosedOperations() throws SQLException {
        TinyResultSet rs = makeResultSet();
        rs.close();
        assertThrows(SQLException.class, rs::next);
        assertThrows(SQLException.class, () -> rs.getString(1));
    }

    @Test
    @DisplayName("Row position tracking")
    void testRowPosition() throws SQLException {
        TinyResultSet rs = makeResultSet();
        assertEquals(0, rs.getRow()); // Before first row
        rs.next();
        assertEquals(1, rs.getRow());
        assertTrue(rs.isFirst());
        assertFalse(rs.isLast());
        rs.next();
        assertEquals(2, rs.getRow());
        assertTrue(rs.isLast());
        assertFalse(rs.next());
        assertTrue(rs.isAfterLast());
    }

    @Test
    @DisplayName("getXxx with out-of-range column throws")
    void testOutOfRangeColumn() throws SQLException {
        TinyResultSet rs = makeResultSet();
        rs.next();
        assertThrows(SQLException.class, () -> rs.getString(0));
        assertThrows(SQLException.class, () -> rs.getString(99));
    }

    @Test
    @DisplayName("getXxx before next() throws")
    void testNoCurrentRow() {
        TinyResultSet rs = makeResultSet();
        assertThrows(SQLException.class, () -> rs.getString(1));
    }

    @Test
    @DisplayName("unwrap / isWrapperFor")
    void testUnwrap() throws SQLException {
        TinyResultSet rs = makeResultSet();
        assertTrue(rs.isWrapperFor(TinyResultSet.class));
        assertNotNull(rs.unwrap(TinyResultSet.class));
        assertThrows(SQLException.class, () -> rs.unwrap(String.class));
    }

    private static void assertArrayEqualsEquals(byte[] a, byte[] b) {
        assertEquals(a.length, b.length);
        for (int i = 0; i < a.length; i++) {
            assertEquals(a[i], b[i]);
        }
    }
}
