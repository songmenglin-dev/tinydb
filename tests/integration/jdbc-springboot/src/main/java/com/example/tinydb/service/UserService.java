package com.example.tinydb.service;

import com.example.tinydb.entity.User;
import com.example.tinydb.mapper.UserMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * Thin service wrapper around {@link UserMapper}.  Kept minimal so the
 * integration test can call mapper methods directly or go through this
 * class to verify Spring DI wiring.
 */
@Service
public class UserService {

    private final UserMapper userMapper;

    @Autowired
    public UserService(UserMapper userMapper) {
        this.userMapper = userMapper;
    }

    public void resetSchema() {
        userMapper.dropTable();
        userMapper.createTable();
    }

    public int insert(User u) { return userMapper.insert(u); }
    public User findById(Integer id) { return userMapper.findById(id); }
    public List<User> findAll() { return userMapper.findAll(); }
    public int updateAge(Integer id, Integer age) { return userMapper.updateAge(id, age); }
    public int deleteById(Integer id) { return userMapper.deleteById(id); }
    public int countAll() { return userMapper.countAll(); }
}