package org.tinydb.jdbc;

import org.tinydb.jdbc.protocol.Codec;

import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.ResultSet;
import java.sql.RowIdLifetime;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;

public class TinyDatabaseMetaData implements DatabaseMetaData {

    @Override
    public java.sql.ResultSet getAttributes(java.lang.String p0, java.lang.String p1, java.lang.String p2, java.lang.String p3) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean allProceduresAreCallable() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean allTablesAreSelectable() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean nullsAreSortedHigh() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean nullsAreSortedLow() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean nullsAreSortedAtStart() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean nullsAreSortedAtEnd() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean usesLocalFiles() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean usesLocalFilePerTable() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsMixedCaseIdentifiers() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean storesUpperCaseIdentifiers() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean storesLowerCaseIdentifiers() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean storesMixedCaseIdentifiers() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsMixedCaseQuotedIdentifiers() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean storesUpperCaseQuotedIdentifiers() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean storesLowerCaseQuotedIdentifiers() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean storesMixedCaseQuotedIdentifiers() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.lang.String getIdentifierQuoteString() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.lang.String getSQLKeywords() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.lang.String getNumericFunctions() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.lang.String getStringFunctions() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.lang.String getSystemFunctions() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.lang.String getTimeDateFunctions() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.lang.String getSearchStringEscape() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.lang.String getExtraNameCharacters() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsAlterTableWithAddColumn() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsAlterTableWithDropColumn() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsColumnAliasing() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean nullPlusNonNullIsNull() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsConvert() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsConvert(int p0, int p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsTableCorrelationNames() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsDifferentTableCorrelationNames() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsExpressionsInOrderBy() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsOrderByUnrelated() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsGroupBy() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsGroupByUnrelated() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsGroupByBeyondSelect() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsLikeEscapeClause() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsMultipleResultSets() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsMultipleTransactions() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsNonNullableColumns() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsMinimumSQLGrammar() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsCoreSQLGrammar() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsExtendedSQLGrammar() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsANSI92EntryLevelSQL() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsANSI92IntermediateSQL() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsANSI92FullSQL() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsIntegrityEnhancementFacility() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsOuterJoins() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsFullOuterJoins() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsLimitedOuterJoins() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.lang.String getSchemaTerm() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.lang.String getProcedureTerm() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.lang.String getCatalogTerm() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean isCatalogAtStart() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.lang.String getCatalogSeparator() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsSchemasInDataManipulation() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsSchemasInProcedureCalls() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsSchemasInTableDefinitions() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsSchemasInIndexDefinitions() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsSchemasInPrivilegeDefinitions() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsCatalogsInDataManipulation() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsCatalogsInProcedureCalls() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsCatalogsInTableDefinitions() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsCatalogsInIndexDefinitions() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsCatalogsInPrivilegeDefinitions() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsPositionedDelete() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsPositionedUpdate() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsSelectForUpdate() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsStoredProcedures() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsSubqueriesInComparisons() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsSubqueriesInExists() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsSubqueriesInIns() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsSubqueriesInQuantifieds() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsCorrelatedSubqueries() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsUnion() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsUnionAll() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsOpenCursorsAcrossCommit() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsOpenCursorsAcrossRollback() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsOpenStatementsAcrossCommit() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsOpenStatementsAcrossRollback() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxBinaryLiteralLength() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxCharLiteralLength() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxColumnNameLength() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxColumnsInGroupBy() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxColumnsInIndex() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxColumnsInOrderBy() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxColumnsInSelect() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxColumnsInTable() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxConnections() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxCursorNameLength() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxIndexLength() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxSchemaNameLength() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxProcedureNameLength() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxCatalogNameLength() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxRowSize() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean doesMaxRowSizeIncludeBlobs() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxStatementLength() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxStatements() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxTableNameLength() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxTablesInSelect() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getMaxUserNameLength() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getDefaultTransactionIsolation() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsTransactionIsolationLevel(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsDataDefinitionAndDataManipulationTransactions() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsDataManipulationTransactionsOnly() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean dataDefinitionCausesTransactionCommit() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean dataDefinitionIgnoredInTransactions() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getProcedures(java.lang.String p0, java.lang.String p1, java.lang.String p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getProcedureColumns(java.lang.String p0, java.lang.String p1, java.lang.String p2, java.lang.String p3) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getSchemas(java.lang.String p0, java.lang.String p1) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getSchemas() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getCatalogs() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getTableTypes() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getColumnPrivileges(java.lang.String p0, java.lang.String p1, java.lang.String p2, java.lang.String p3) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getTablePrivileges(java.lang.String p0, java.lang.String p1, java.lang.String p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getBestRowIdentifier(java.lang.String p0, java.lang.String p1, java.lang.String p2, int p3, boolean p4) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getVersionColumns(java.lang.String p0, java.lang.String p1, java.lang.String p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getPrimaryKeys(java.lang.String p0, java.lang.String p1, java.lang.String p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getImportedKeys(java.lang.String p0, java.lang.String p1, java.lang.String p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getExportedKeys(java.lang.String p0, java.lang.String p1, java.lang.String p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getCrossReference(java.lang.String p0, java.lang.String p1, java.lang.String p2, java.lang.String p3, java.lang.String p4, java.lang.String p5) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getTypeInfo() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getIndexInfo(java.lang.String p0, java.lang.String p1, java.lang.String p2, boolean p3, boolean p4) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsResultSetType(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean ownUpdatesAreVisible(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean ownDeletesAreVisible(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean ownInsertsAreVisible(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean othersUpdatesAreVisible(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean othersDeletesAreVisible(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean othersInsertsAreVisible(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean updatesAreDetected(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean deletesAreDetected(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean insertsAreDetected(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsBatchUpdates() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getUDTs(java.lang.String p0, java.lang.String p1, java.lang.String p2, int[] p3) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsSavepoints() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsNamedParameters() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsMultipleOpenResults() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsGetGeneratedKeys() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getSuperTypes(java.lang.String p0, java.lang.String p1, java.lang.String p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getSuperTables(java.lang.String p0, java.lang.String p1, java.lang.String p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsResultSetHoldability(int p0) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getResultSetHoldability() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getDatabaseMajorVersion() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getDatabaseMinorVersion() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getJDBCMajorVersion() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public int getJDBCMinorVersion() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean locatorsUpdateCopy() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsStatementPooling() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean supportsStoredFunctionsUsingCallSyntax() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean autoCommitFailureClosesAllResultSets() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getClientInfoProperties() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getFunctions(java.lang.String p0, java.lang.String p1, java.lang.String p2) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getFunctionColumns(java.lang.String p0, java.lang.String p1, java.lang.String p2, java.lang.String p3) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public java.sql.ResultSet getPseudoColumns(java.lang.String p0, java.lang.String p1, java.lang.String p2, java.lang.String p3) throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }

    @Override
    public boolean generatedKeyAlwaysReturned() throws java.sql.SQLException { throw new SQLException("not supported in v0.3", "HY000"); }


    @Override
    public <T> T unwrap(Class<T> iface) throws SQLException {
        if (iface.isInstance(this)) return iface.cast(this);
        throw new SQLException("not a wrapper for " + iface.getName(), "HY000");
    }

    @Override
    public boolean isWrapperFor(Class<?> iface) throws SQLException {
        return iface.isInstance(this);
    }

    private final TinyConnection connection;

    public TinyDatabaseMetaData(TinyConnection connection) {
        this.connection = connection;
    }

    @Override
    public String getURL() throws SQLException {
        return "jdbc:tinydb://" + connection.getHost() + ":" + connection.getPort() + "/" +
               (connection.getCatalog() == null ? "" : connection.getCatalog());
    }

    @Override
    public String getUserName() throws SQLException {
        return "tinydb";
    }

    @Override
    public String getDatabaseProductName() throws SQLException {
        return "tinydb";
    }

    @Override
    public String getDatabaseProductVersion() throws SQLException {
        return connection.getServerVersion();
    }

    @Override
    public String getDriverName() throws SQLException {
        return "tinydb-jdbc";
    }

    @Override
    public String getDriverVersion() throws SQLException {
        return "0.3.0";
    }

    @Override
    public int getDriverMajorVersion() { return 0; }

    @Override
    public int getDriverMinorVersion() { return 3; }

    @Override
    public boolean supportsTransactions() throws SQLException {
        return true;
    }

    @Override
    public boolean supportsResultSetConcurrency(int type, int concurrency) throws SQLException {
        return type == ResultSet.TYPE_FORWARD_ONLY && concurrency == ResultSet.CONCUR_READ_ONLY;
    }

    @Override
    public ResultSet getTables(String catalog, String schemaPattern, String tableNamePattern, String[] types) throws SQLException {
        TinyConnection.QueryResult qr = connection.sendQuery("SHOW TABLES");
        List<Codec.Column> cols = qr.columns;
        List<List<Object>> rows = qr.rows;
        List<Codec.Column> outCols = new ArrayList<>();
        outCols.add(new Codec.Column("TABLE_CAT", Codec.WIRE_STRING));
        outCols.add(new Codec.Column("TABLE_SCHEM", Codec.WIRE_STRING));
        outCols.add(new Codec.Column("TABLE_NAME", Codec.WIRE_STRING));
        outCols.add(new Codec.Column("TABLE_TYPE", Codec.WIRE_STRING));
        outCols.add(new Codec.Column("REMARKS", Codec.WIRE_STRING));
        List<List<Object>> outRows = new ArrayList<>();
        for (List<Object> row : rows) {
            Object tableName = row.get(0);
            if (tableName == null) continue;
            String tn = tableName.toString();
            if (tableNamePattern != null && !matchesLike(tn, tableNamePattern)) continue;
            List<Object> out = new ArrayList<>();
            out.add(connection.getCatalog()); out.add(null); out.add(tn);
            out.add("TABLE"); out.add(null);
            outRows.add(out);
        }
        return new TinyResultSet(outCols, outRows);
    }

    @Override
    public ResultSet getColumns(String catalog, String schemaPattern, String tableNamePattern, String columnNamePattern) throws SQLException {
        TinyConnection.QueryResult tables = connection.sendQuery("SHOW TABLES");
        List<Codec.Column> cols = new ArrayList<>();
        cols.add(new Codec.Column("TABLE_CAT", Codec.WIRE_STRING));
        cols.add(new Codec.Column("TABLE_SCHEM", Codec.WIRE_STRING));
        cols.add(new Codec.Column("TABLE_NAME", Codec.WIRE_STRING));
        cols.add(new Codec.Column("COLUMN_NAME", Codec.WIRE_STRING));
        cols.add(new Codec.Column("TYPE_NAME", Codec.WIRE_STRING));
        cols.add(new Codec.Column("DATA_TYPE", Codec.WIRE_INT64));
        List<List<Object>> rows = new ArrayList<>();
        for (List<Object> trow : tables.rows) {
            Object tn = trow.get(0);
            if (tn == null) continue;
            String tableName = tn.toString();
            if (tableNamePattern != null && !matchesLike(tableName, tableNamePattern)) continue;
            try {
                TinyConnection.QueryResult qr = connection.sendQuery("DESCRIBE " + tableName);
                for (List<Object> crow : qr.rows) {
                    String colName = crow.get(0) == null ? "" : crow.get(0).toString();
                    if (columnNamePattern != null && !matchesLike(colName, columnNamePattern)) continue;
                    List<Object> out = new ArrayList<>();
                    out.add(connection.getCatalog()); out.add(null);
                    out.add(tableName); out.add(colName);
                    out.add(crow.size() > 1 && crow.get(1) != null ? crow.get(1).toString() : "STRING");
                    out.add(0L);
                    rows.add(out);
                }
            } catch (SQLException e) {
                // skip
            }
        }
        return new TinyResultSet(cols, rows);
    }

    private boolean matchesLike(String s, String pattern) {
        StringBuilder regex = new StringBuilder();
        for (int i = 0; i < pattern.length(); i++) {
            char c = pattern.charAt(i);
            if (c == '%') regex.append(".*");
            else if (c == '_') regex.append(".");
            else if ("\\.[]{}()*+-?^$|".indexOf(c) >= 0) regex.append("\\").append(c);
            else regex.append(c);
        }
        return s.matches(regex.toString());
    }

    @Override
    public Connection getConnection() throws SQLException { return connection; }
    @Override
    public boolean isReadOnly() throws SQLException { return false; }
    @Override
    public int getSQLStateType() throws SQLException { return sqlStateSQL99; }
    @Override
    public RowIdLifetime getRowIdLifetime() throws SQLException { return RowIdLifetime.ROWID_UNSUPPORTED; }

    public boolean isClosed() throws SQLException { return connection.isClosed(); }
}
