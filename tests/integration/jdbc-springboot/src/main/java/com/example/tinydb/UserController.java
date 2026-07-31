package com.example.tinydb;

import com.example.tinydb.entity.User;
import com.example.tinydb.service.UserService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Minimal HTTP surface for verifying the tinydb-jdbc connection end-to-end
 * from a running Spring Boot app.  Without the web starter, Spring's main
 * thread has no listener and exits immediately after context startup.
 */
@RestController
@RequestMapping("/api/users")
public class UserController {

    private final UserService userService;

    @Autowired
    public UserController(UserService userService) {
        this.userService = userService;
    }

    /** Health check — exercises the JDBC connection via SELECT 1-equivalent. */
    @GetMapping("/health")
    public Map<String, Object> health() {
        Map<String, Object> r = new HashMap<>();
        r.put("status", "UP");
        try {
            userService.resetSchema();
            int count = userService.countAll();
            r.put("jdbc", "OK");
            r.put("table_count", count);
        } catch (Exception e) {
            r.put("status", "DOWN");
            r.put("error", e.getMessage());
        }
        return r;
    }

    @PostMapping
    public Map<String, Object> create(@RequestBody User user) {
        userService.resetSchema();
        int affected = userService.insert(user);
        Map<String, Object> r = new HashMap<>();
        r.put("inserted", affected);
        r.put("user", user);
        return r;
    }

    @GetMapping
    public List<User> list() {
        return userService.findAll();
    }

    @GetMapping("/{id}")
    public User get(@PathVariable Integer id) {
        return userService.findById(id);
    }
}