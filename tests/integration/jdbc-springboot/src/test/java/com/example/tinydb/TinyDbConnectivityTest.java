package com.example.tinydb;

import com.example.tinydb.entity.User;
import com.example.tinydb.service.UserService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * End-to-end connectivity test: load a Spring context, inject the
 * MyBatis-driven {@link UserService}, and exercise the full CRUD
 * surface against a live {@code tinydb-server} reachable via
 * {@code jdbc:tinydb://...}.
 *
 * <p>The server is expected to already be listening on
 * {@code TINYDB_JDBC_URL} (see {@code scripts/start-tinydb-server.sh}).
 *
 * <p>Uses JUnit 5 (Jupiter) — Spring Boot 2.7 ships JUnit 5 as the
 * default test framework; {@code @SpringBootTest} auto-registers
 * {@code SpringExtension} so no explicit {@code @ExtendWith} is needed.
 */
@SpringBootTest
public class TinyDbConnectivityTest {

    @Autowired
    private UserService userService;

    @Test
    void springContextLoads() {
        // Smoke test: if the context fails to wire up, this test fails
        // before any of the JDBC assertions below.
        assertNotNull(userService);
    }

    @Test
    void crudRoundTrip() {
        // Reset to a known state — DROP + CREATE so each run is independent.
        userService.resetSchema();

        // --- INSERT ---
        assertEquals(1, userService.insert(new User(1, "alice", 30)));
        assertEquals(1, userService.insert(new User(2, "bob", 25)));
        assertEquals(1, userService.insert(new User(3, "carol", 35)));

        // --- SELECT ---
        User u1 = userService.findById(1);
        assertNotNull(u1);
        assertEquals(Integer.valueOf(1), u1.getId());
        assertEquals("alice", u1.getName());
        assertEquals(Integer.valueOf(30), u1.getAge());

        List<User> all = userService.findAll();
        assertEquals(3, all.size());

        assertEquals(3, userService.countAll());

        // --- UPDATE ---
        assertEquals(1, userService.updateAge(2, 26));
        User u2 = userService.findById(2);
        assertEquals(Integer.valueOf(26), u2.getAge());

        // --- DELETE ---
        assertEquals(1, userService.deleteById(3));
        assertEquals(2, userService.countAll());
        assertNull(userService.findById(3));
    }

    @Test
    void utf8RoundTrip() {
        userService.resetSchema();
        userService.insert(new User(1, "你好", 18));
        User u = userService.findById(1);
        assertNotNull(u);
        assertEquals("你好", u.getName());
    }
}