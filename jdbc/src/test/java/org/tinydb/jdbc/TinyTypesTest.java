package org.tinydb.jdbc;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.tinydb.jdbc.protocol.Codec;

import java.sql.Types;

import static org.junit.jupiter.api.Assertions.assertEquals;

class TinyTypesTest {

    @Test
    @DisplayName("Types.INTEGER -> wire INT64 (0x01)")
    void testJdbcToWireInt() {
        assertEquals(Codec.WIRE_INT64, TinyTypes.jdbcToWireCode(Types.INTEGER));
    }

    @Test
    @DisplayName("Types.BIGINT -> wire INT64 (0x01)")
    void testJdbcToWireBigInt() {
        assertEquals(Codec.WIRE_INT64, TinyTypes.jdbcToWireCode(Types.BIGINT));
    }

    @Test
    @DisplayName("Types.DOUBLE -> wire FLOAT64 (0x02)")
    void testJdbcToWireDouble() {
        assertEquals(Codec.WIRE_FLOAT64, TinyTypes.jdbcToWireCode(Types.DOUBLE));
    }

    @Test
    @DisplayName("Types.VARCHAR -> wire STRING (0x03)")
    void testJdbcToWireString() {
        assertEquals(Codec.WIRE_STRING, TinyTypes.jdbcToWireCode(Types.VARCHAR));
    }

    @Test
    @DisplayName("Types.BOOLEAN -> wire BOOL (0x04)")
    void testJdbcToWireBoolean() {
        assertEquals(Codec.WIRE_BOOL, TinyTypes.jdbcToWireCode(Types.BOOLEAN));
    }

    @Test
    @DisplayName("Types.NULL -> wire NULL (0x00)")
    void testJdbcToWireNull() {
        assertEquals(Codec.WIRE_NULL, TinyTypes.jdbcToWireCode(Types.NULL));
    }

    @Test
    @DisplayName("Unknown JDBC type defaults to STRING")
    void testJdbcToWireUnknown() {
        // ARRAY doesn't have a wire mapping
        assertEquals(Codec.WIRE_STRING, TinyTypes.jdbcToWireCode(Types.ARRAY));
    }

    @Test
    @DisplayName("wire INT64 (0x01) -> Types.BIGINT")
    void testWireToJdbcInt64() {
        assertEquals(Types.BIGINT, TinyTypes.wireCodeToJdbc(Codec.WIRE_INT64));
    }

    @Test
    @DisplayName("wire FLOAT64 (0x02) -> Types.DOUBLE")
    void testWireToJdbcFloat64() {
        assertEquals(Types.DOUBLE, TinyTypes.wireCodeToJdbc(Codec.WIRE_FLOAT64));
    }

    @Test
    @DisplayName("wire STRING (0x03) -> Types.VARCHAR")
    void testWireToJdbcString() {
        assertEquals(Types.VARCHAR, TinyTypes.wireCodeToJdbc(Codec.WIRE_STRING));
    }

    @Test
    @DisplayName("wire BOOL (0x04) -> Types.BOOLEAN")
    void testWireToJdbcBool() {
        assertEquals(Types.BOOLEAN, TinyTypes.wireCodeToJdbc(Codec.WIRE_BOOL));
    }

    @Test
    @DisplayName("wire NULL (0x00) -> Types.NULL")
    void testWireToJdbcNull() {
        assertEquals(Types.NULL, TinyTypes.wireCodeToJdbc(Codec.WIRE_NULL));
    }

    @Test
    @DisplayName("unknown wire code -> Types.NULL")
    void testWireToJdbcUnknown() {
        assertEquals(Types.NULL, TinyTypes.wireCodeToJdbc((byte) 0x99));
    }
}
