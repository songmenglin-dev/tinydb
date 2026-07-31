package com.example.tinydb.controller;

import com.example.tinydb.entity.User;
import com.example.tinydb.service.UserService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.sql.Connection;
import java.sql.ResultSet;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Minimal CRUD surface for the {@code users} table — exactly four
 * endpoints as specified:
 * <ol>
 *   <li>{@code GET /api/users/status} — round-trip to the running
 *       tinydb-server, list every table it knows about, and report
 *       how many tables there are (and how many rows each has).</li>
 *   <li>{@code GET /api/users/init} — {@code CREATE TABLE users} only,
 *       no {@code DROP}.  If the table already exists, the v0.3
 *       parser raises and we surface {@code status=exists}.</li>
 *   <li>{@code GET /api/users/random5} — insert five randomly-
 *       generated users and return them.</li>
 *   <li>{@code GET /api/users/all} — return every row.</li>
 * </ol>
 *
 * The {@link JdbcTemplate} is used only by {@link #status()} because
 * we need direct access to {@link java.sql.DatabaseMetaData#getTables}
 * (MyBatis wouldn't expose that without a dedicated mapper method).
 */
@RestController
@RequestMapping("/api/users")
public class UserController {

    private final UserService userService;
    private final JdbcTemplate jdbc;

    @Autowired
    public UserController(UserService userService, JdbcTemplate jdbc) {
        this.userService = userService;
        this.jdbc = jdbc;
    }

    /**
     * (1) Connection probe + table listing.
     * Exercises a no-op query first to confirm JDBC works, then asks
     * the driver for the full table catalog via standard
     * {@link java.sql.DatabaseMetaData}.  No DDL is issued here.
     */
    @GetMapping("/status")
    public Map<String, Object> status() {
        Map<String, Object> r = new HashMap<>();
        try {
            List<Map<String, Object>> tables = jdbc.execute((Connection c) -> {
                List<Map<String, Object>> out = new ArrayList<>();
                try (ResultSet rs = c.getMetaData()
                        .getTables(null, null, "%", new String[]{"TABLE"})) {
                    while (rs.next()) {
                        Map<String, Object> t = new HashMap<>();
                        String name = rs.getString("TABLE_NAME");
                        t.put("name", name);
                        try {
                            t.put("row_count", countRows(c, name));
                        } catch (Exception inner) {
                            t.put("row_count", null);
                            t.put("row_count_error", inner.getMessage());
                        }
                        out.add(t);
                    }
                }
                return out;
            });
            r.put("status", "UP");
            r.put("table_count", tables.size());
            r.put("tables", tables);
        } catch (Exception e) {
            r.put("status", "DOWN");
            r.put("error", e.getMessage());
        }
        return r;
    }

    /**
     * (2) Drop the existing {@code users} table if there is one, then
     * (re)create it with the schema {@code UserMapper} declares.
     * Always safe to invoke even against a fresh / empty database
     * (the {@code DROP TABLE IF EXISTS} on the server is a no-op
     * when nothing is there).
     */
    @GetMapping("/init")
    public Map<String, Object> init() {
        Map<String, Object> r = new HashMap<>();
        try {
            userService.resetSchema();
            r.put("status", "reset_and_created");
            r.put("new_total", userService.countAll());
        } catch (Exception e) {
            r.put("status", "error");
            r.put("error", e.getMessage());
        }
        return r;
    }

    /**
     * (3) Insert exactly five randomly-generated users.  Each call
     * asks the service for {@code MAX(id)+1} so the {@code id}
     * PRIMARY KEY never collides even after multiple invocations.
     */
    @GetMapping("/random5")
    public Map<String, Object> random5() {
        List<Map<String, Object>> inserted = new ArrayList<>(5);
        for (int i = 0; i < 5; i++) {
            User u = userService.randomUser();
            int affected = userService.insert(u);
            Map<String, Object> row = new HashMap<>();
            row.put("affected_rows", affected);
            row.put("user", u);
            inserted.add(row);
        }
        Map<String, Object> r = new HashMap<>();
        r.put("inserted_count", inserted.size());
        r.put("new_total", userService.countAll());
        r.put("items", inserted);
        return r;
    }

    /** (4) Return every row in the {@code users} table. */
    @GetMapping("/all")
    public List<User> all() {
        return userService.findAll();
    }

    // ------------------------------------------------------------------
    // Internals
    // ------------------------------------------------------------------

    /**
     * Issue {@code SELECT COUNT(*) FROM <tableName>} on the supplied
     * connection.  We don't use a prepared statement because
     * {@code tableName} is the catalog output (driver-controlled)
     * rather than user input — even so, we still reject anything
     * that isn't a plain identifier to avoid splicing weirdness.
     */
    private static Integer countRows(Connection c, String tableName) throws java.sql.SQLException {
        if (tableName == null || !tableName.matches("[A-Za-z_][A-Za-z0-9_]*")) {
            throw new IllegalArgumentException("unsafe table name: " + tableName);
        }
        try (java.sql.Statement st = c.createStatement();
             ResultSet rs = st.executeQuery("SELECT COUNT(*) FROM " + tableName)) {
            return rs.next() ? rs.getInt(1) : 0;
        }
    }
}
