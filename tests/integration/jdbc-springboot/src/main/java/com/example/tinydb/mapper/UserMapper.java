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
 * Every SQL statement is dispatched through the tinydb JDBC driver
 * ({@code jdbc:tinydb://...}) and round-trips to a running
 * {@code tinydb-server} process.
 *
 * <p>The v0.3 driver returns placeholder column names
 * ({@code col0}, {@code col1}, …) for SELECT lists, so each read
 * query carries an explicit {@link Results} mapping that lines
 * {@code col0..col2} up with the {@link User} bean properties.
 */
@Mapper
public interface UserMapper {

    /** Drop the {@code users} table if it exists. */
    @Update("DROP TABLE IF EXISTS users")
    void dropTable();

    /**
     * Create the {@code users} table.  The v0.3 parser does not
     * support {@code IF NOT EXISTS} so a duplicate table raises an
     * error — the controller catches that and surfaces "exists".
     */
    @Update("CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL, age INT)")
    void createTable();

    @Insert("INSERT INTO users VALUES (#{id}, #{name}, #{age})")
    int insert(User user);

    @Results({
            @Result(column = "col0", property = "id"),
            @Result(column = "col1", property = "name"),
            @Result(column = "col2", property = "age"),
    })
    @Select("SELECT id, name, age FROM users ORDER BY id")
    List<User> findAll();

    @Select("SELECT COUNT(*) FROM users")
    int countAll();

    /** {@code null} when the table is empty. */
    @Select("SELECT MAX(id) FROM users")
    Integer maxId();

    @Delete("DELETE FROM users WHERE id = #{id}")
    int deleteById(@Param("id") Integer id);
}
