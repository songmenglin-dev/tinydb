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
 *
 * Only the wire -> JDBC direction is used at the moment (by
 * :class:`TinyResultSet`'s metadata).  The reverse mapping was
 * originally planned for ``setObject(int, Object, int)`` but v0.3
 * falls back on string conversion for unknown types — see
 * ``TinyPreparedStatement.setObject`` for the heuristic.
 */
public final class TinyTypes {
    private TinyTypes() {}

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