package org.tinydb.jdbc;

import java.sql.SQLException;

/**
 * Thin facade to org.tinydb.jdbc.protocol.ErrorCode that exposes
 * SQLException-building helpers for client-side use.
 */
public final class TinySQLException {
    private TinySQLException() {}

    /**
     * Build an SQLException for a server-returned SQLSTATE code.
     */
    public static SQLException fromServer(String sqlState, String msg) {
        return org.tinydb.jdbc.protocol.ErrorCode.toSqlException(sqlState, msg);
    }

    /**
     * Build a constraint violation exception.
     */
    public static SQLException constraintViolation(String msg) {
        return org.tinydb.jdbc.protocol.ErrorCode.constraintViolation(msg);
    }
}
