package com.example.tinydb.service;

import com.example.tinydb.entity.User;
import com.example.tinydb.mapper.UserMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.concurrent.ThreadLocalRandom;

/**
 * Thin service wrapper around {@link UserMapper} that also owns the
 * random-data factory used by the one-click insert endpoint.
 */
@Service
public class UserService {

    private static final String[] FIRST_NAMES = {
            "alice", "bob", "carol", "dave", "eve", "frank",
            "grace", "heidi", "ivan", "judy", "kim", "leo",
            "mallory", "nina", "oscar", "peggy", "quinn", "ruth",
    };

    private final UserMapper userMapper;

    @Autowired
    public UserService(UserMapper userMapper) {
        this.userMapper = userMapper;
    }

    /**
     * Drop the existing {@code users} table (if any) and recreate it
     * with the schema this mapper declares.  Use this when the server's
     * table definition has drifted — e.g. after a column-add experiment
     * — and you want the next INSERT to line up with the JDBC side.
     */
    public void resetSchema() {
        userMapper.dropTable();
        userMapper.createTable();
    }

    public int insert(User u) { return userMapper.insert(u); }
    public List<User> findAll() { return userMapper.findAll(); }
    public int countAll() { return userMapper.countAll(); }

    /** Next id = MAX(id) + 1, or 1 when the table is empty. */
    public int nextId() {
        Integer max = userMapper.maxId();
        return (max == null ? 0 : max) + 1;
    }

    /**
     * Build a {@link User} with random {@code name}/{@code age}.  Each
     * insertion asks the service for the next id so the {@code id}
     * PRIMARY KEY never collides.
     */
    public User randomUser() {
        ThreadLocalRandom r = ThreadLocalRandom.current();
        String first = FIRST_NAMES[r.nextInt(FIRST_NAMES.length)];
        int suffix = r.nextInt(1000, 10_000);
        return new User(nextId(), first + "_" + suffix, r.nextInt(1, 100));
    }
}
