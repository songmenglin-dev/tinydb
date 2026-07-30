package org.tinydb.jdbc;

import org.tinydb.jdbc.protocol.Codec;

import java.sql.Types;

/**
 * Mapping between JDBC java.sql.Types and tinydb wire protocol type codes.
 *
 * Wire codes:
 *  0x00 NULL
 *  0x01 INT64
 *  0x02 FLOAT64
 *  0x03 STRING
 *  0x04 BOOL
 */
public final class TinyTypes {
    private TinyTypes() {}

    /**
     * Convert JDBC java.sql.Types code to wire protocol type byte.
     * Returns WIRE_NULL for unknown types.
     */
    public static byte jdbcToWireCode(int sqlType) {
        switch (sqlType) {
            case Types.NULL:
                return Codec.WIRE_NULL;
            case Types.BIGINT:
            case Types.INTEGER:
            case Types.SMALLINT:
            case Types.TINYINT:
                return Codec.WIRE_INT64;
            case Types.DOUBLE:
            case Types.FLOAT:
            case Types.REAL:
            case Types.NUMERIC:
            case Types.DECIMAL:
                return Codec.WIRE_FLOAT64;
            case Types.VARCHAR:
            case Types.CHAR:
            case Types.LONGVARCHAR:
            case Types.NCHAR:
            case Types.NVARCHAR:
            case Types.LONGNVARCHAR:
            case Types.CLOB:
            case Types.NCLOB:
                return Codec.WIRE_STRING;
            case Types.BOOLEAN:
            case Types.BIT:
                return Codec.WIRE_BOOL;
            default:
                // unknown -> treat as string (most permissive)
                return Codec.WIRE_STRING;
        }
    }

    /**
     * Convert wire protocol type byte to JDBC java.sql.Types code.
     * Returns Types.NULL for unknown codes.
     */
    public static int wireCodeToJdbc(byte wireCode) {
        switch (wireCode) {
            case Codec.WIRE_NULL:   return Types.NULL;
            case Codec.WIRE_INT64:  return Types.BIGINT;
            case Codec.WIRE_FLOAT64: return Types.DOUBLE;
            case Codec.WIRE_STRING: return Types.VARCHAR;
            case Codec.WIRE_BOOL:   return Types.BOOLEAN;
            default:                return Types.NULL;
        }
    }
}
