package org.tinydb.jdbc.protocol;

import java.sql.SQLDataException;
import java.sql.SQLException;
import java.sql.SQLIntegrityConstraintViolationException;
import java.sql.SQLNonTransientConnectionException;
import java.sql.SQLSyntaxErrorException;
import java.sql.SQLTransactionRollbackException;

/**
 * Maps SQLSTATE 5-class codes to JDBC exception subclasses.
 * See REQ-PROTO-7 and REQ-JDBC-7.
 */
public final class ErrorCode {
    public static final String CONNECTION_EXCEPTION = "08000";
    public static final String DATA_EXCEPTION = "22000";
    public static final String TRANSACTION_STATE_INVALID = "25000";
    public static final String SYNTAX_ERROR = "42000";
    public static final String GENERAL_ERROR = "HY000";

    private ErrorCode() {}

    /**
     * Build an SQLException subclass instance for the given SQLSTATE code.
     * Returns SQLException for unknown codes.
     */
    public static SQLException toSqlException(String code, String msg) {
        if (code == null) {
            return new SQLException(msg, GENERAL_ERROR);
        }
        if (CONNECTION_EXCEPTION.equals(code)) {
            return new SQLNonTransientConnectionException(msg, code);
        }
        if (DATA_EXCEPTION.equals(code)) {
            // We can't reliably distinguish constraint violations from data exceptions
            // at this level - return SQLDataException as the broader type.
            return new SQLDataException(msg, code);
        }
        if (TRANSACTION_STATE_INVALID.equals(code)) {
            // SQLInvalidTransactionStateException was added in Java 9 / JDBC 4.3.
            // Java 8 / JDBC 4.2 doesn't have it, so use SQLTransactionRollbackException
            // (or fall back to plain SQLException).
            return new SQLTransactionRollbackException(msg, code);
        }
        if (SYNTAX_ERROR.equals(code)) {
            return new SQLSyntaxErrorException(msg, code);
        }
        // HY000 and unknowns
        return new SQLException(msg, code);
    }

    /**
     * Helper for constraint violations (more specific than DATA_EXCEPTION).
     */
    public static SQLException constraintViolation(String msg) {
        return new SQLIntegrityConstraintViolationException(msg, DATA_EXCEPTION);
    }

    /**
     * Helper for transaction rollback.
     */
    public static SQLException transactionRollback(String msg) {
        return new SQLTransactionRollbackException(msg, TRANSACTION_STATE_INVALID);
    }
}
