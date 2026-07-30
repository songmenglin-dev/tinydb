package org.tinydb.jdbc;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.tinydb.jdbc.protocol.ErrorCode;

import java.sql.SQLDataException;
import java.sql.SQLException;
import java.sql.SQLIntegrityConstraintViolationException;

import java.sql.SQLNonTransientConnectionException;
import java.sql.SQLSyntaxErrorException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ErrorCodeTest {

    @Test
    @DisplayName("08000 maps to SQLNonTransientConnectionException")
    void testConnectionException() {
        SQLException e = ErrorCode.toSqlException("08000", "connection lost");
        assertNotNull(e);
        assertTrue(e instanceof SQLNonTransientConnectionException);
        assertEquals("08000", e.getSQLState());
        assertEquals("connection lost", e.getMessage());
    }

    @Test
    @DisplayName("22000 maps to SQLDataException (or SQLIntegrityConstraintViolationException)")
    void testDataException() {
        SQLException e = ErrorCode.toSqlException("22000", "type mismatch");
        assertNotNull(e);
        assertTrue(e instanceof SQLDataException || e instanceof SQLIntegrityConstraintViolationException);
        assertEquals("22000", e.getSQLState());
    }

    @Test
    @DisplayName("25000 maps to SQLInvalidTransactionStateException")
    void testTransactionState() {
        SQLException e = ErrorCode.toSqlException("25000", "no active transaction");
        assertNotNull(e);
        assertTrue(e instanceof java.sql.SQLTransactionRollbackException);
        assertEquals("25000", e.getSQLState());
    }

    @Test
    @DisplayName("42000 maps to SQLSyntaxErrorException")
    void testSyntaxError() {
        SQLException e = ErrorCode.toSqlException("42000", "syntax error at 'FROM'");
        assertNotNull(e);
        assertTrue(e instanceof SQLSyntaxErrorException);
        assertEquals("42000", e.getSQLState());
    }

    @Test
    @DisplayName("HY000 maps to plain SQLException")
    void testGeneralError() {
        SQLException e = ErrorCode.toSqlException("HY000", "something went wrong");
        assertNotNull(e);
        assertEquals(SQLException.class, e.getClass());
        assertEquals("HY000", e.getSQLState());
    }

    @Test
    @DisplayName("Unknown SQLSTATE falls back to SQLException with HY000")
    void testUnknownCode() {
        SQLException e = ErrorCode.toSqlException("99999", "weird");
        assertNotNull(e);
        assertEquals(SQLException.class, e.getClass());
        assertEquals("99999", e.getSQLState());
    }

    @Test
    @DisplayName("Null SQLSTATE falls back to HY000")
    void testNullCode() {
        SQLException e = ErrorCode.toSqlException(null, "oops");
        assertNotNull(e);
        assertEquals("HY000", e.getSQLState());
    }

    @Test
    @DisplayName("constraintViolation() helper returns SQLIntegrityConstraintViolationException")
    void testConstraintViolation() {
        SQLException e = ErrorCode.constraintViolation("UNIQUE constraint violated");
        assertTrue(e instanceof SQLIntegrityConstraintViolationException);
        assertEquals("22000", e.getSQLState());
    }

    @Test
    @DisplayName("transactionRollback() helper returns SQLTransactionRollbackException")
    void testTransactionRollback() {
        SQLException e = ErrorCode.transactionRollback("deadlock");
        assertTrue(e instanceof java.sql.SQLTransactionRollbackException);
        assertEquals("25000", e.getSQLState());
    }

    @Test
    @DisplayName("TinySQLException.fromServer delegates correctly")
    void testTinySQLExceptionFacade() {
        SQLException e = TinySQLException.fromServer("42000", "bad SQL");
        assertTrue(e instanceof SQLSyntaxErrorException);
        assertEquals("42000", e.getSQLState());
    }
}
