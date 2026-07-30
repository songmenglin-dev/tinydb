package org.tinydb.jdbc;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.tinydb.jdbc.protocol.Codec;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.net.ServerSocket;
import java.net.Socket;
import java.sql.Blob;
import java.sql.Clob;
import java.sql.NClob;
import java.sql.RowId;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;

import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * Sanity test to ensure all "not supported in v0.3" stub methods on
 * the main JDBC classes throw SQLException. This forces JaCoCo to
 * count the stub bodies as covered.
 */
class StubCoverageTest {

    private static ServerSocket startFakeServer() throws IOException {
        ServerSocket ss = new ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1"));
        Thread t = new Thread(() -> {
            try {
                while (!ss.isClosed()) {
                    Socket client = ss.accept();
                    new Thread(() -> {
                        try {
                            java.io.DataInputStream in = new java.io.DataInputStream(client.getInputStream());
                            java.io.DataOutputStream out = new java.io.DataOutputStream(client.getOutputStream());
                            org.tinydb.jdbc.protocol.Frame hello = org.tinydb.jdbc.protocol.Frame.read(in);
                            if (hello != null && hello.getType() == org.tinydb.jdbc.protocol.Codec.TYPE_HELLO) {
                                byte[] ver = "tinydb-0.3.0".getBytes();
                                org.tinydb.jdbc.protocol.Frame okFrame = new org.tinydb.jdbc.protocol.Frame(
                                        ver.length + 2,
                                        org.tinydb.jdbc.protocol.Codec.TYPE_OK,
                                        (byte) 0,
                                        ver);
                                okFrame.write(out);
                                while (true) {
                                    org.tinydb.jdbc.protocol.Frame f = org.tinydb.jdbc.protocol.Frame.read(in);
                                    if (f == null) break;
                                    if (f.getType() == org.tinydb.jdbc.protocol.Codec.TYPE_QUIT) break;
                                    if (f.getType() == org.tinydb.jdbc.protocol.Codec.TYPE_PING) {
                                        org.tinydb.jdbc.protocol.Frame pong = org.tinydb.jdbc.protocol.Codec.encodePong(
                                                org.tinydb.jdbc.protocol.Codec.decodePing(f));
                                        pong.write(out);
                                        continue;
                                    }
                                    ByteArrayOutputStream baos = new ByteArrayOutputStream();
                                    DataOutputStream dos = new DataOutputStream(baos);
                                    dos.writeShort(0);
                                    byte[] payload = baos.toByteArray();
                                    org.tinydb.jdbc.protocol.Frame hdr = new org.tinydb.jdbc.protocol.Frame(
                                            payload.length + 2,
                                            org.tinydb.jdbc.protocol.Codec.TYPE_RESULT_HEADER,
                                            (byte) 0,
                                            payload);
                                    hdr.write(out);

                                    ByteArrayOutputStream doneBaos = new ByteArrayOutputStream();
                                    DataOutputStream doneDos = new DataOutputStream(doneBaos);
                                    doneDos.writeLong(0L);
                                    doneDos.writeLong(0L);
                                    doneDos.writeByte(0);
                                    byte[] donePayload = doneBaos.toByteArray();
                                    org.tinydb.jdbc.protocol.Frame done = new org.tinydb.jdbc.protocol.Frame(
                                            donePayload.length + 2,
                                            org.tinydb.jdbc.protocol.Codec.TYPE_RESULT_DONE,
                                            (byte) 0,
                                            donePayload);
                                    done.write(out);
                                }
                            }
                        } catch (IOException ignored) {
                        } finally {
                            try { client.close(); } catch (IOException ignored) {}
                        }
                    }).start();
                }
            } catch (IOException ignored) {}
        });
        t.setDaemon(true);
        t.start();
        return ss;
    }

    private static java.sql.Connection connect() throws Exception {
        ServerSocket ss = startFakeServer();
        Thread.sleep(50);
        int port = ss.getLocalPort();
        return java.sql.DriverManager.getConnection(
                "jdbc:tinydb://127.0.0.1:" + port + "/db");
    }

    @Test
    @DisplayName("Connection stubs throw 'not supported'")
    void testConnectionStubs() throws Exception {
        try (java.sql.Connection conn = connect()) {
            assertThrows(SQLException.class, () -> conn.setReadOnly(true));
            assertThrows(SQLException.class, conn::isReadOnly);
            assertThrows(SQLException.class, () -> conn.prepareCall("CALL x()"));
            assertThrows(SQLException.class, () -> conn.prepareCall("CALL x()", 1, 1, 1));
            assertThrows(SQLException.class, () -> conn.setTransactionIsolation(1));
            assertThrows(SQLException.class, conn::getTransactionIsolation);
            assertThrows(SQLException.class, conn::getWarnings);
            assertThrows(SQLException.class, conn::clearWarnings);
            assertThrows(SQLException.class, conn::getTypeMap);
            assertThrows(SQLException.class, () -> conn.setTypeMap(new HashMap<String, Class<?>>()));
            assertThrows(SQLException.class, () -> conn.setHoldability(1));
            assertThrows(SQLException.class, conn::getHoldability);
            assertThrows(SQLException.class, conn::setSavepoint);
            assertThrows(SQLException.class, () -> conn.setSavepoint("s"));
            assertThrows(SQLException.class, () -> conn.releaseSavepoint(null));
            assertThrows(SQLException.class, conn::createClob);
            assertThrows(SQLException.class, conn::createBlob);
            assertThrows(SQLException.class, conn::createNClob);
            assertThrows(SQLException.class, conn::createSQLXML);
            assertThrows(SQLException.class, conn::getClientInfo);
            assertThrows(SQLException.class, () -> conn.getClientInfo("k"));
            assertThrows(SQLException.class, () -> conn.createArrayOf("t", new Object[0]));
            assertThrows(SQLException.class, () -> conn.createStruct("t", new Object[0]));
            assertThrows(SQLException.class, () -> conn.setSchema("s"));
            assertThrows(SQLException.class, conn::getSchema);
            assertThrows(SQLException.class, () -> conn.setNetworkTimeout(null, 1));
            assertThrows(SQLException.class, conn::getNetworkTimeout);
            assertThrows(SQLException.class, () -> conn.abort(null));
        }
    }

    @Test
    @DisplayName("Statement stubs throw 'not supported'")
    void testStatementStubs() throws Exception {
        try (java.sql.Connection conn = connect();
             java.sql.Statement stmt = conn.createStatement()) {
            assertThrows(SQLException.class, stmt::cancel);
            assertThrows(SQLException.class, () -> stmt.addBatch("INSERT"));
            assertThrows(SQLException.class, stmt::clearBatch);
            assertThrows(SQLException.class, stmt::executeBatch);
            assertThrows(SQLException.class, stmt::getGeneratedKeys);
            assertThrows(SQLException.class, () -> stmt.setCursorName("c"));
            assertThrows(SQLException.class, stmt::getGeneratedKeys);
        }
    }

    @Test
    @DisplayName("PreparedStatement stubs throw 'not supported'")
    void testPreparedStatementStubs() throws Exception {
        try (java.sql.Connection conn = connect();
             java.sql.PreparedStatement ps = conn.prepareStatement("SELECT 1")) {
            assertThrows(SQLException.class, ps::getParameterMetaData);
            assertThrows(SQLException.class, () -> ps.setRowId(1, (RowId) null));
            assertThrows(SQLException.class, () -> ps.setNCharacterStream(1, null, 1L));
            assertThrows(SQLException.class, () -> ps.setNClob(1, (java.sql.NClob) null));
            assertThrows(SQLException.class, () -> ps.setClob(1, new java.io.StringReader("x"), 1L));
            assertThrows(SQLException.class, () -> ps.setBlob(1, new ByteArrayInputStream(new byte[0]), 1L));
            assertThrows(SQLException.class, () -> ps.setNClob(1, new java.io.StringReader("x"), 1L));
            assertThrows(SQLException.class, () -> ps.setSQLXML(1, null));
            assertThrows(SQLException.class, () -> ps.setAsciiStream(1, new ByteArrayInputStream(new byte[0]), 1L));
            assertThrows(SQLException.class, () -> ps.setBinaryStream(1, new ByteArrayInputStream(new byte[0]), 1L));
            assertThrows(SQLException.class, () -> ps.setCharacterStream(1, new java.io.StringReader("x"), 1L));
            assertThrows(SQLException.class, () -> ps.setAsciiStream(1, new ByteArrayInputStream(new byte[0])));
            assertThrows(SQLException.class, () -> ps.setBinaryStream(1, new ByteArrayInputStream(new byte[0])));
            assertThrows(SQLException.class, () -> ps.setCharacterStream(1, new java.io.StringReader("x")));
            assertThrows(SQLException.class, () -> ps.setNCharacterStream(1, new java.io.StringReader("x")));
            assertThrows(SQLException.class, () -> ps.setClob(1, new java.io.StringReader("x")));
            assertThrows(SQLException.class, () -> ps.setBlob(1, new ByteArrayInputStream(new byte[0])));
            assertThrows(SQLException.class, () -> ps.setNClob(1, new java.io.StringReader("x")));
            assertThrows(SQLException.class, () -> ps.setAsciiStream(1, new ByteArrayInputStream(new byte[0]), 1));
            assertThrows(SQLException.class, () -> ps.setBinaryStream(1, new ByteArrayInputStream(new byte[0]), 1));
            assertThrows(SQLException.class, () -> ps.setUnicodeStream(1, new ByteArrayInputStream(new byte[0]), 1));
            assertThrows(SQLException.class, () -> ps.setBinaryStream(1, new ByteArrayInputStream(new byte[0]), 1));
            assertThrows(SQLException.class, () -> ps.setCharacterStream(1, new java.io.StringReader("x"), 1));
            assertThrows(SQLException.class, () -> ps.setRef(1, null));
            assertThrows(SQLException.class, () -> ps.setBlob(1, (java.sql.Blob) null));
            assertThrows(SQLException.class, () -> ps.setClob(1, (java.sql.Clob) null));
            assertThrows(SQLException.class, () -> ps.setArray(1, null));
            assertThrows(SQLException.class, ps::addBatch);
        }
    }

    @Test
    @DisplayName("ResultSet stubs throw 'not supported'")
    void testResultSetStubs() throws Exception {
        List<Codec.Column> cols = new ArrayList<>();
        cols.add(new Codec.Column("x", Codec.WIRE_INT64));
        List<List<Object>> rows = new ArrayList<>();
        rows.add(new ArrayList<>());
        rows.get(0).add(1L);
        TinyResultSet rs = new TinyResultSet(cols, rows);
        rs.next();
        // Test all the stub methods
        assertThrows(SQLException.class, () -> rs.updateBytes(1, new byte[0]));
        assertThrows(SQLException.class, () -> rs.updateBytes("x", new byte[0]));
        assertThrows(SQLException.class, () -> rs.getArray(1));
        assertThrows(SQLException.class, () -> rs.getArray("x"));
        assertThrows(SQLException.class, () -> rs.getURL(1));
        assertThrows(SQLException.class, () -> rs.getURL("x"));
        assertThrows(SQLException.class, rs::getType);
        assertThrows(SQLException.class, () -> rs.getRef(1));
        assertThrows(SQLException.class, () -> rs.getRef("x"));
        assertThrows(SQLException.class, rs::previous);
        assertThrows(SQLException.class, rs::first);
        assertThrows(SQLException.class, () -> rs.getAsciiStream(1));
        assertThrows(SQLException.class, () -> rs.getAsciiStream("x"));
        assertThrows(SQLException.class, () -> rs.getUnicodeStream(1));
        assertThrows(SQLException.class, () -> rs.getUnicodeStream("x"));
        assertThrows(SQLException.class, () -> rs.getBinaryStream(1));
        assertThrows(SQLException.class, () -> rs.getBinaryStream("x"));
        assertThrows(SQLException.class, rs::getWarnings);
        assertThrows(SQLException.class, rs::clearWarnings);
        assertThrows(SQLException.class, rs::getCursorName);
        assertThrows(SQLException.class, () -> rs.getCharacterStream(1));
        assertThrows(SQLException.class, () -> rs.getCharacterStream("x"));
        assertThrows(SQLException.class, rs::beforeFirst);
        assertThrows(SQLException.class, rs::afterLast);
        assertThrows(SQLException.class, rs::last);
        assertThrows(SQLException.class, () -> rs.absolute(1));
        assertThrows(SQLException.class, () -> rs.relative(1));
        assertThrows(SQLException.class, () -> rs.setFetchDirection(1));
        assertThrows(SQLException.class, rs::getFetchDirection);
        assertThrows(SQLException.class, () -> rs.setFetchSize(1));
        assertThrows(SQLException.class, rs::getFetchSize);
        assertThrows(SQLException.class, rs::getConcurrency);
        assertThrows(SQLException.class, rs::rowUpdated);
        assertThrows(SQLException.class, rs::rowInserted);
        assertThrows(SQLException.class, rs::rowDeleted);
        assertThrows(SQLException.class, () -> rs.updateNull(1));
        assertThrows(SQLException.class, () -> rs.updateNull("x"));
        assertThrows(SQLException.class, () -> rs.updateBoolean(1, true));
        assertThrows(SQLException.class, () -> rs.updateBoolean("x", true));
        assertThrows(SQLException.class, () -> rs.updateByte(1, (byte) 1));
        assertThrows(SQLException.class, () -> rs.updateByte("x", (byte) 1));
        assertThrows(SQLException.class, () -> rs.updateShort(1, (short) 1));
        assertThrows(SQLException.class, () -> rs.updateShort("x", (short) 1));
        assertThrows(SQLException.class, () -> rs.updateInt(1, 1));
        assertThrows(SQLException.class, () -> rs.updateInt("x", 1));
        assertThrows(SQLException.class, () -> rs.updateLong(1, 1L));
        assertThrows(SQLException.class, () -> rs.updateLong("x", 1L));
        assertThrows(SQLException.class, () -> rs.updateFloat(1, 1f));
        assertThrows(SQLException.class, () -> rs.updateFloat("x", 1f));
        assertThrows(SQLException.class, () -> rs.updateDouble(1, 1.0));
        assertThrows(SQLException.class, () -> rs.updateDouble("x", 1.0));
        assertThrows(SQLException.class, () -> rs.updateBigDecimal(1, java.math.BigDecimal.ONE));
        assertThrows(SQLException.class, () -> rs.updateBigDecimal("x", java.math.BigDecimal.ONE));
        assertThrows(SQLException.class, () -> rs.updateString(1, "x"));
        assertThrows(SQLException.class, () -> rs.updateString("x", "x"));
        assertThrows(SQLException.class, () -> rs.updateDate(1, null));
        assertThrows(SQLException.class, () -> rs.updateDate("x", null));
        assertThrows(SQLException.class, () -> rs.updateTime(1, null));
        assertThrows(SQLException.class, () -> rs.updateTime("x", null));
        assertThrows(SQLException.class, () -> rs.updateTimestamp(1, null));
        assertThrows(SQLException.class, () -> rs.updateTimestamp("x", null));
        assertThrows(SQLException.class, () -> rs.updateAsciiStream(1, null));
        assertThrows(SQLException.class, () -> rs.updateAsciiStream("x", null));
        assertThrows(SQLException.class, () -> rs.updateAsciiStream(1, null, 1));
        assertThrows(SQLException.class, () -> rs.updateAsciiStream(1, null, 1L));
        assertThrows(SQLException.class, () -> rs.updateAsciiStream("x", null, 1));
        assertThrows(SQLException.class, () -> rs.updateAsciiStream("x", null, 1L));
        assertThrows(SQLException.class, () -> rs.updateBinaryStream(1, null));
        assertThrows(SQLException.class, () -> rs.updateBinaryStream(1, null, 1));
        assertThrows(SQLException.class, () -> rs.updateBinaryStream(1, null, 1L));
        assertThrows(SQLException.class, () -> rs.updateBinaryStream("x", null));
        assertThrows(SQLException.class, () -> rs.updateBinaryStream("x", null, 1));
        assertThrows(SQLException.class, () -> rs.updateBinaryStream("x", null, 1L));
        assertThrows(SQLException.class, () -> rs.updateCharacterStream(1, null));
        assertThrows(SQLException.class, () -> rs.updateCharacterStream(1, null, 1));
        assertThrows(SQLException.class, () -> rs.updateCharacterStream(1, null, 1L));
        assertThrows(SQLException.class, () -> rs.updateCharacterStream("x", null));
        assertThrows(SQLException.class, () -> rs.updateCharacterStream("x", null, 1));
        assertThrows(SQLException.class, () -> rs.updateCharacterStream("x", null, 1L));
        assertThrows(SQLException.class, () -> rs.updateObject(1, "x"));
        assertThrows(SQLException.class, () -> rs.updateObject(1, "x", 1));
        assertThrows(SQLException.class, () -> rs.updateObject("x", "x"));
        assertThrows(SQLException.class, () -> rs.updateObject("x", "x", 1));
        assertThrows(SQLException.class, rs::insertRow);
        assertThrows(SQLException.class, rs::updateRow);
        assertThrows(SQLException.class, rs::deleteRow);
        assertThrows(SQLException.class, rs::refreshRow);
        assertThrows(SQLException.class, rs::cancelRowUpdates);
        assertThrows(SQLException.class, rs::moveToInsertRow);
        assertThrows(SQLException.class, rs::moveToCurrentRow);
        assertThrows(SQLException.class, rs::getStatement);
        assertThrows(SQLException.class, () -> rs.getBlob(1));
        assertThrows(SQLException.class, () -> rs.getBlob("x"));
        assertThrows(SQLException.class, () -> rs.getClob(1));
        assertThrows(SQLException.class, () -> rs.getClob("x"));
        assertThrows(SQLException.class, () -> rs.updateRef(1, null));
        assertThrows(SQLException.class, () -> rs.updateRef("x", null));
        assertThrows(SQLException.class, () -> rs.updateBlob(1, (Blob) null));
        assertThrows(SQLException.class, () -> rs.updateBlob(1, (java.io.InputStream) null));
        assertThrows(SQLException.class, () -> rs.updateBlob(1, null, 1L));
        assertThrows(SQLException.class, () -> rs.updateBlob("x", (Blob) null));
        assertThrows(SQLException.class, () -> rs.updateBlob("x", (java.io.InputStream) null));
        assertThrows(SQLException.class, () -> rs.updateBlob("x", null, 1L));
        assertThrows(SQLException.class, () -> rs.updateClob(1, (Clob) null));
        assertThrows(SQLException.class, () -> rs.updateClob(1, (java.io.Reader) null));
        assertThrows(SQLException.class, () -> rs.updateClob(1, null, 1L));
        assertThrows(SQLException.class, () -> rs.updateClob("x", (Clob) null));
        assertThrows(SQLException.class, () -> rs.updateClob("x", (java.io.Reader) null));
        assertThrows(SQLException.class, () -> rs.updateClob("x", null, 1L));
        assertThrows(SQLException.class, () -> rs.updateArray(1, null));
        assertThrows(SQLException.class, () -> rs.updateArray("x", null));
        assertThrows(SQLException.class, () -> rs.getRowId(1));
        assertThrows(SQLException.class, () -> rs.getRowId("x"));
        assertThrows(SQLException.class, () -> rs.updateRowId(1, null));
        assertThrows(SQLException.class, () -> rs.updateRowId("x", null));
        assertThrows(SQLException.class, rs::getHoldability);
        assertThrows(SQLException.class, () -> rs.updateNString(1, "x"));
        assertThrows(SQLException.class, () -> rs.updateNString("x", "x"));
        assertThrows(SQLException.class, () -> rs.updateNClob(1, (NClob) null));
        assertThrows(SQLException.class, () -> rs.updateNClob(1, (java.io.Reader) null));
        assertThrows(SQLException.class, () -> rs.updateNClob(1, null, 1L));
        assertThrows(SQLException.class, () -> rs.updateNClob("x", (NClob) null));
        assertThrows(SQLException.class, () -> rs.updateNClob("x", (java.io.Reader) null));
        assertThrows(SQLException.class, () -> rs.updateNClob("x", null, 1L));
        assertThrows(SQLException.class, () -> rs.getNClob(1));
        assertThrows(SQLException.class, () -> rs.getNClob("x"));
        assertThrows(SQLException.class, () -> rs.getSQLXML(1));
        assertThrows(SQLException.class, () -> rs.getSQLXML("x"));
        assertThrows(SQLException.class, () -> rs.updateSQLXML(1, null));
        assertThrows(SQLException.class, () -> rs.updateSQLXML("x", null));
        assertThrows(SQLException.class, () -> rs.getNString(1));
        assertThrows(SQLException.class, () -> rs.getNString("x"));
        assertThrows(SQLException.class, () -> rs.getNCharacterStream(1));
        assertThrows(SQLException.class, () -> rs.getNCharacterStream("x"));
        assertThrows(SQLException.class, () -> rs.updateNCharacterStream(1, null));
        assertThrows(SQLException.class, () -> rs.updateNCharacterStream(1, null, 1L));
        assertThrows(SQLException.class, () -> rs.updateNCharacterStream("x", null));
        assertThrows(SQLException.class, () -> rs.updateNCharacterStream("x", null, 1L));
    }

    @Test
    @DisplayName("DatabaseMetaData stubs throw 'not supported'")
    void testDatabaseMetaDataStubs() throws Exception {
        try (java.sql.Connection conn = connect()) {
            java.sql.DatabaseMetaData md = conn.getMetaData();
            assertThrows(SQLException.class, () -> md.getAttributes(null, null, null, null));
            assertThrows(SQLException.class, md::allProceduresAreCallable);
            assertThrows(SQLException.class, md::allTablesAreSelectable);
            assertThrows(SQLException.class, md::nullsAreSortedHigh);
            assertThrows(SQLException.class, md::nullsAreSortedLow);
            assertThrows(SQLException.class, md::nullsAreSortedAtStart);
            assertThrows(SQLException.class, md::nullsAreSortedAtEnd);
            assertThrows(SQLException.class, md::usesLocalFiles);
            assertThrows(SQLException.class, md::usesLocalFilePerTable);
            assertThrows(SQLException.class, md::supportsMixedCaseIdentifiers);
            assertThrows(SQLException.class, md::storesUpperCaseIdentifiers);
            assertThrows(SQLException.class, md::storesLowerCaseIdentifiers);
            assertThrows(SQLException.class, md::storesMixedCaseIdentifiers);
            assertThrows(SQLException.class, md::supportsMixedCaseQuotedIdentifiers);
            assertThrows(SQLException.class, md::storesUpperCaseQuotedIdentifiers);
            assertThrows(SQLException.class, md::storesLowerCaseQuotedIdentifiers);
            assertThrows(SQLException.class, md::storesMixedCaseQuotedIdentifiers);
            assertThrows(SQLException.class, md::getIdentifierQuoteString);
            assertThrows(SQLException.class, md::getSQLKeywords);
            assertThrows(SQLException.class, md::getNumericFunctions);
            assertThrows(SQLException.class, md::getStringFunctions);
            assertThrows(SQLException.class, md::getSystemFunctions);
            assertThrows(SQLException.class, md::getTimeDateFunctions);
            assertThrows(SQLException.class, md::getSearchStringEscape);
            assertThrows(SQLException.class, md::getExtraNameCharacters);
            assertThrows(SQLException.class, md::supportsAlterTableWithAddColumn);
            assertThrows(SQLException.class, md::supportsAlterTableWithDropColumn);
            assertThrows(SQLException.class, md::supportsColumnAliasing);
            assertThrows(SQLException.class, md::nullPlusNonNullIsNull);
            assertThrows(SQLException.class, md::supportsConvert);
            assertThrows(SQLException.class, () -> md.supportsConvert(1, 2));
            assertThrows(SQLException.class, md::supportsTableCorrelationNames);
            assertThrows(SQLException.class, md::supportsDifferentTableCorrelationNames);
            assertThrows(SQLException.class, md::supportsExpressionsInOrderBy);
            assertThrows(SQLException.class, md::supportsOrderByUnrelated);
            assertThrows(SQLException.class, md::supportsGroupBy);
            assertThrows(SQLException.class, md::supportsGroupByUnrelated);
            assertThrows(SQLException.class, md::supportsGroupByBeyondSelect);
            assertThrows(SQLException.class, md::supportsLikeEscapeClause);
            assertThrows(SQLException.class, md::supportsMultipleResultSets);
            assertThrows(SQLException.class, md::supportsMultipleTransactions);
            assertThrows(SQLException.class, md::supportsNonNullableColumns);
            assertThrows(SQLException.class, md::supportsMinimumSQLGrammar);
            assertThrows(SQLException.class, md::supportsCoreSQLGrammar);
            assertThrows(SQLException.class, md::supportsExtendedSQLGrammar);
            assertThrows(SQLException.class, md::supportsANSI92EntryLevelSQL);
            assertThrows(SQLException.class, md::supportsANSI92IntermediateSQL);
            assertThrows(SQLException.class, md::supportsANSI92FullSQL);
            assertThrows(SQLException.class, md::supportsIntegrityEnhancementFacility);
            assertThrows(SQLException.class, md::supportsOuterJoins);
            assertThrows(SQLException.class, md::supportsFullOuterJoins);
            assertThrows(SQLException.class, md::supportsLimitedOuterJoins);
            assertThrows(SQLException.class, md::getSchemaTerm);
            assertThrows(SQLException.class, md::getProcedureTerm);
            assertThrows(SQLException.class, md::getCatalogTerm);
            assertThrows(SQLException.class, md::isCatalogAtStart);
            assertThrows(SQLException.class, md::getCatalogSeparator);
            assertThrows(SQLException.class, md::supportsSchemasInDataManipulation);
            assertThrows(SQLException.class, md::supportsSchemasInProcedureCalls);
            assertThrows(SQLException.class, md::supportsSchemasInTableDefinitions);
            assertThrows(SQLException.class, md::supportsSchemasInIndexDefinitions);
            assertThrows(SQLException.class, md::supportsSchemasInPrivilegeDefinitions);
            assertThrows(SQLException.class, md::supportsCatalogsInDataManipulation);
            assertThrows(SQLException.class, md::supportsCatalogsInProcedureCalls);
            assertThrows(SQLException.class, md::supportsCatalogsInTableDefinitions);
            assertThrows(SQLException.class, md::supportsCatalogsInIndexDefinitions);
            assertThrows(SQLException.class, md::supportsCatalogsInPrivilegeDefinitions);
            assertThrows(SQLException.class, md::supportsPositionedDelete);
            assertThrows(SQLException.class, md::supportsPositionedUpdate);
            assertThrows(SQLException.class, md::supportsSelectForUpdate);
            assertThrows(SQLException.class, md::supportsStoredProcedures);
            assertThrows(SQLException.class, md::supportsSubqueriesInComparisons);
            assertThrows(SQLException.class, md::supportsSubqueriesInExists);
            assertThrows(SQLException.class, md::supportsSubqueriesInIns);
            assertThrows(SQLException.class, md::supportsSubqueriesInQuantifieds);
            assertThrows(SQLException.class, md::supportsCorrelatedSubqueries);
            assertThrows(SQLException.class, md::supportsUnion);
            assertThrows(SQLException.class, md::supportsUnionAll);
            assertThrows(SQLException.class, md::supportsOpenCursorsAcrossCommit);
            assertThrows(SQLException.class, md::supportsOpenCursorsAcrossRollback);
            assertThrows(SQLException.class, md::supportsOpenStatementsAcrossCommit);
            assertThrows(SQLException.class, md::supportsOpenStatementsAcrossRollback);
            assertThrows(SQLException.class, md::getMaxBinaryLiteralLength);
            assertThrows(SQLException.class, md::getMaxCharLiteralLength);
            assertThrows(SQLException.class, md::getMaxColumnNameLength);
            assertThrows(SQLException.class, md::getMaxColumnsInGroupBy);
            assertThrows(SQLException.class, md::getMaxColumnsInIndex);
            assertThrows(SQLException.class, md::getMaxColumnsInOrderBy);
            assertThrows(SQLException.class, md::getMaxColumnsInSelect);
            assertThrows(SQLException.class, md::getMaxColumnsInTable);
            assertThrows(SQLException.class, md::getMaxConnections);
            assertThrows(SQLException.class, md::getMaxCursorNameLength);
            assertThrows(SQLException.class, md::getMaxIndexLength);
            assertThrows(SQLException.class, md::getMaxSchemaNameLength);
            assertThrows(SQLException.class, md::getMaxProcedureNameLength);
            assertThrows(SQLException.class, md::getMaxCatalogNameLength);
            assertThrows(SQLException.class, md::getMaxRowSize);
            assertThrows(SQLException.class, md::doesMaxRowSizeIncludeBlobs);
            assertThrows(SQLException.class, md::getMaxStatementLength);
            assertThrows(SQLException.class, md::getMaxStatements);
            assertThrows(SQLException.class, md::getMaxTableNameLength);
            assertThrows(SQLException.class, md::getMaxTablesInSelect);
            assertThrows(SQLException.class, md::getMaxUserNameLength);
            assertThrows(SQLException.class, md::getDefaultTransactionIsolation);
            assertThrows(SQLException.class, () -> md.supportsTransactionIsolationLevel(1));
            assertThrows(SQLException.class, md::supportsDataDefinitionAndDataManipulationTransactions);
            assertThrows(SQLException.class, md::supportsDataManipulationTransactionsOnly);
            assertThrows(SQLException.class, md::dataDefinitionCausesTransactionCommit);
            assertThrows(SQLException.class, md::dataDefinitionIgnoredInTransactions);
            assertThrows(SQLException.class, () -> md.getProcedureColumns(null, null, null, null));
            assertThrows(SQLException.class, md::getSchemas);
            assertThrows(SQLException.class, () -> md.getColumnPrivileges(null, null, null, null));
            assertThrows(SQLException.class, () -> md.getTablePrivileges(null, null, null));
            assertThrows(SQLException.class, () -> md.getBestRowIdentifier(null, null, null, 1, true));
            assertThrows(SQLException.class, () -> md.getVersionColumns(null, null, null));
            assertThrows(SQLException.class, () -> md.getPrimaryKeys(null, null, null));
            assertThrows(SQLException.class, () -> md.getImportedKeys(null, null, null));
            assertThrows(SQLException.class, () -> md.getExportedKeys(null, null, null));
            assertThrows(SQLException.class, () -> md.getCrossReference(null, null, null, null, null, null));
            assertThrows(SQLException.class, () -> md.getIndexInfo(null, null, null, true, true));
            assertThrows(SQLException.class, () -> md.supportsResultSetType(1));
            assertThrows(SQLException.class, () -> md.ownUpdatesAreVisible(1));
            assertThrows(SQLException.class, () -> md.ownDeletesAreVisible(1));
            assertThrows(SQLException.class, () -> md.ownInsertsAreVisible(1));
            assertThrows(SQLException.class, () -> md.othersUpdatesAreVisible(1));
            assertThrows(SQLException.class, () -> md.othersDeletesAreVisible(1));
            assertThrows(SQLException.class, () -> md.othersInsertsAreVisible(1));
            assertThrows(SQLException.class, () -> md.updatesAreDetected(1));
            assertThrows(SQLException.class, () -> md.deletesAreDetected(1));
            assertThrows(SQLException.class, () -> md.insertsAreDetected(1));
            assertThrows(SQLException.class, md::supportsBatchUpdates);
            assertThrows(SQLException.class, () -> md.getUDTs(null, null, null, new int[0]));
            assertThrows(SQLException.class, md::supportsSavepoints);
            assertThrows(SQLException.class, md::supportsNamedParameters);
            assertThrows(SQLException.class, md::supportsMultipleOpenResults);
            assertThrows(SQLException.class, md::supportsGetGeneratedKeys);
            assertThrows(SQLException.class, () -> md.getSuperTypes(null, null, null));
            assertThrows(SQLException.class, () -> md.getSuperTables(null, null, null));
            assertThrows(SQLException.class, () -> md.supportsResultSetHoldability(1));
            assertThrows(SQLException.class, md::getResultSetHoldability);
            assertThrows(SQLException.class, md::getDatabaseMajorVersion);
            assertThrows(SQLException.class, md::getDatabaseMinorVersion);
            assertThrows(SQLException.class, md::getJDBCMajorVersion);
            assertThrows(SQLException.class, md::getJDBCMinorVersion);
            assertThrows(SQLException.class, md::locatorsUpdateCopy);
            assertThrows(SQLException.class, md::supportsStatementPooling);
            assertThrows(SQLException.class, md::supportsStoredFunctionsUsingCallSyntax);
            assertThrows(SQLException.class, md::autoCommitFailureClosesAllResultSets);
            assertThrows(SQLException.class, md::getClientInfoProperties);
            assertThrows(SQLException.class, () -> md.getFunctions(null, null, null));
            assertThrows(SQLException.class, () -> md.getFunctionColumns(null, null, null, null));
            assertThrows(SQLException.class, () -> md.getPseudoColumns(null, null, null, null));
            assertThrows(SQLException.class, md::generatedKeyAlwaysReturned);
        }
    }
}
