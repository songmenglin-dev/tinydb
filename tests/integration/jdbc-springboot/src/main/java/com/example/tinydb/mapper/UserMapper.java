package com.example.tinydb.mapper;

import com.example.tinydb.entity.User;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Result;
import org.apache.ibatis.annotations.Results;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/**
 * Annotation-driven MyBatis mapper for the {@code users} table.
 * Every SQL statement here is dispatched through the tinydb JDBC
 * driver ({@code jdbc:tinydb://...}) and round-trips to a running
 * {@code tinydb-server} process.
 *
 * <p>SQL surface intentionally stays inside what the v0.3 SQL parser
 * accepts: no {@code AS} aliases, no FROM-less SELECTs, no multi-
 * statement {@code ;}-separated batches.  The v0.3 driver also
 * returns placeholder column names ({@code col0}, {@code col1}, …)
 * for SELECT lists, so each read query carries an explicit
 * {@link Results} mapping that lines {@code col0/col1/col2} up with
 * the {@link User} bean properties.
 */
@Mapper
public interface UserMapper {

    /** Drop + recreate the schema (idempotent between test runs). */
    @Update("DROP TABLE IF EXISTS users")
    void dropTable();

    @Update("CREATE TABLE users (id INT PRIMARY KEY, name TEXT, age INT)")
    void createTable();

    @Insert("INSERT INTO users VALUES (#{id}, #{name}, #{age})")
    int insert(User user);

    @Results({
            @Result(column = "col0", property = "id"),
            @Result(column = "col1", property = "name"),
            @Result(column = "col2", property = "age"),
    })
    @Select("SELECT id, name, age FROM users WHERE id = #{id}")
    User findById(@Param("id") Integer id);

    @Results({
            @Result(column = "col0", property = "id"),
            @Result(column = "col1", property = "name"),
            @Result(column = "col2", property = "age"),
    })
    @Select("SELECT id, name, age FROM users ORDER BY id")
    List<User> findAll();

    @Update("UPDATE users SET age = #{age} WHERE id = #{id}")
    int updateAge(@Param("id") Integer id, @Param("age") Integer age);

    @Delete("DELETE FROM users WHERE id = #{id}")
    int deleteById(@Param("id") Integer id);

    @Select("SELECT COUNT(*) FROM users")
    int countAll();
}