package org.tinydb.jdbc;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.tinydb.jdbc.protocol.Codec;

import java.sql.Types;

import static org.junit.jupiter.api.Assertions.assertEquals;

class TinyTypesTest {

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