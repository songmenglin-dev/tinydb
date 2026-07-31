package com.example.tinydb.entity;

/**
 * Plain POJO mapped from the {@code users} table.  Field names match
 * the column names used by {@code UserMapper} so MyBatis can populate
 * them via reflection without an explicit {@code @Results} mapping.
 */
public class User {
    private Integer id;
    private String name;
    private Integer age;

    public User() {}

    public User(Integer id, String name, Integer age) {
        this.id = id;
        this.name = name;
        this.age = age;
    }

    public Integer getId() { return id; }
    public void setId(Integer id) { this.id = id; }

    public String getName() { return name; }
    public void setName(String name) { this.name = name; }

    public Integer getAge() { return age; }
    public void setAge(Integer age) { this.age = age; }

    @Override
    public String toString() {
        return "User{id=" + id + ", name='" + name + "', age=" + age + "}";
    }
}