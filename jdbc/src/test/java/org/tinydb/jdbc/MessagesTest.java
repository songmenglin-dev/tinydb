package org.tinydb.jdbc;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.tinydb.jdbc.protocol.Codec;
import org.tinydb.jdbc.protocol.Frame;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Comprehensive test of all 12 wire protocol messages.
 * Confirms byte format is wire-compatible with Python tinydb-server.
 */
class MessagesTest {

    @Test
    @DisplayName("HELLO (0x01): client_id is UTF-8 in payload")
    void testHello() throws Exception {
        Frame f = Codec.encodeHello("py-tinydb-1.0");
        assertEquals(Codec.TYPE_HELLO, f.getType());
        byte[] payload = f.getPayload();
        assertEquals("py-tinydb-1.0", new String(payload, "UTF-8"));
    }

    @Test
    @DisplayName("OK (0x02): server version in payload")
    void testOk() throws Exception {
        byte[] version = "tinydb-0.3.1".getBytes("UTF-8");
        Frame f = new Frame(version.length, Codec.TYPE_OK, (byte) 0, version);
        assertEquals(Codec.TYPE_OK, f.getType());
        assertEquals("tinydb-0.3.1", Codec.decodeOk(f));
    }

    @Test
    @DisplayName("ERR (0x03): code(5 ASCII) + msg_len(2 BE) + msg")
    void testErr() throws Exception {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        dos.write("08000".getBytes("UTF-8"));
        byte[] msg = "HELLO required".getBytes("UTF-8");
        dos.writeShort(msg.length);
        dos.write(msg);
        byte[] payload = baos.toByteArray();
        Frame f = new Frame(payload.length, Codec.TYPE_ERR, (byte) 0, payload);
        assertEquals(Codec.TYPE_ERR, f.getType());
        String s = Codec.decodeErr(f);
        assertTrue(s.startsWith("08000"));
        assertTrue(s.contains("HELLO required"));
    }

    @Test
    @DisplayName("QUERY (0x10): SQL as UTF-8")
    void testQuery() throws Exception {
        Frame f = Codec.encodeQuery("SELECT 1");
        assertEquals(Codec.TYPE_QUERY, f.getType());
        assertEquals("SELECT 1", new String(f.getPayload(), "UTF-8"));
    }

    @Test
    @DisplayName("EXEC (0x11): sql_len(4) + sql + param_count(2) + params")
    void testExec() throws Exception {
        List<Codec.Param> params = new ArrayList<>();
        params.add(Codec.Param.int64(42));
        params.add(Codec.Param.string("hello"));
        Frame f = Codec.encodeExec("SELECT ?", params);
        assertEquals(Codec.TYPE_EXEC, f.getType());
        // Roundtrip through stream
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        f.write(dos);
        DataInputStream dis = new DataInputStream(new ByteArrayInputStream(baos.toByteArray()));
        Frame decoded = Frame.read(dis);
        assertNotNull(decoded);
        assertEquals(Codec.TYPE_EXEC, decoded.getType());
        assertEquals(f.getPayload().length, decoded.getPayload().length);
    }

    @Test
    @DisplayName("RESULT_HEADER (0x20): col_count + name + type per column")
    void testResultHeader() {
        List<Codec.Column> cols = new ArrayList<>();
        cols.add(new Codec.Column("id", Codec.WIRE_INT64));
        cols.add(new Codec.Column("name", Codec.WIRE_STRING));
        // Encode
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        try {
            DataOutputStream dos = new DataOutputStream(baos);
            dos.writeShort(cols.size());
            for (Codec.Column c : cols) {
                byte[] nb = c.name.getBytes("UTF-8");
                dos.writeByte(nb.length);
                dos.write(nb);
                dos.writeByte(c.type);
            }
        } catch (Exception e) { throw new RuntimeException(e); }
        byte[] payload = baos.toByteArray();
        Frame f = new Frame(payload.length, Codec.TYPE_RESULT_HEADER, (byte) 0, payload);
        List<Codec.Column> decoded = Codec.decodeResultHeader(f);
        assertEquals(2, decoded.size());
        assertEquals("id", decoded.get(0).name);
        assertEquals(Codec.WIRE_INT64, decoded.get(0).type);
        assertEquals("name", decoded.get(1).name);
        assertEquals(Codec.WIRE_STRING, decoded.get(1).type);
    }

    @Test
    @DisplayName("RESULT_ROW (0x21): col_count + type+len+value per column")
    void testResultRow() throws Exception {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        dos.writeShort(2);
        dos.writeByte(Codec.WIRE_INT64);
        dos.writeInt(8);
        dos.writeLong(42);
        dos.writeByte(Codec.WIRE_STRING);
        dos.writeInt(5);
        dos.write("hello".getBytes("UTF-8"));
        byte[] payload = baos.toByteArray();
        Frame f = new Frame(payload.length, Codec.TYPE_RESULT_ROW, (byte) 0, payload);
        List<Object> vals = Codec.decodeResultRow(f);
        assertEquals(2, vals.size());
        assertEquals(42L, vals.get(0));
        assertEquals("hello", vals.get(1));
    }

    @Test
    @DisplayName("RESULT_DONE (0x22): rowcount(8) + last_insert_id(8) + flags(1)")
    void testResultDone() throws Exception {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        dos.writeLong(10);   // rowcount
        dos.writeLong(7);    // last_insert_id
        dos.writeByte(0x05); // AUTOCOMMIT | NO_RESULT
        byte[] payload = baos.toByteArray();
        Frame f = new Frame(payload.length, Codec.TYPE_RESULT_DONE, (byte) 0, payload);
        Codec.DoneInfo info = Codec.decodeResultDone(f);
        assertEquals(10L, info.rowcount);
        assertEquals(7L, info.lastInsertId);
        assertEquals((byte) 0x05, info.flags);
    }

    @Test
    @DisplayName("RESULT_ERROR (0x23): code(5 ASCII) + msg_len(2 BE) + msg")
    void testResultError() throws Exception {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        dos.write("22000".getBytes("UTF-8"));
        byte[] msg = "UNIQUE constraint violated".getBytes("UTF-8");
        dos.writeShort(msg.length);
        dos.write(msg);
        byte[] payload = baos.toByteArray();
        Frame f = new Frame(payload.length, Codec.TYPE_RESULT_ERROR, (byte) 0, payload);
        String[] parts = Codec.decodeResultError(f);
        assertEquals("22000", parts[0]);
        assertEquals("UNIQUE constraint violated", parts[1]);
    }

    @Test
    @DisplayName("PING (0x30): 8-byte timestamp")
    void testPing() throws Exception {
        Frame f = Codec.encodePing(1234567890123L);
        assertEquals(Codec.TYPE_PING, f.getType());
        assertEquals(8, f.getPayload().length);
        assertEquals(1234567890123L, Codec.decodePing(f));
    }

    @Test
    @DisplayName("PONG (0x31): 8-byte timestamp echo")
    void testPong() throws Exception {
        Frame f = Codec.encodePong(9876543210L);
        assertEquals(Codec.TYPE_PONG, f.getType());
        assertEquals(9876543210L, Codec.decodePong(f));
    }

    @Test
    @DisplayName("QUIT (0xFE): empty payload")
    void testQuit() {
        Frame f = Codec.encodeQuit();
        assertEquals(Codec.TYPE_QUIT, f.getType());
        assertEquals(0, f.getPayload().length);
        assertEquals(0, f.getLen()); // header-only
    }

    @Test
    @DisplayName("All 12 type constants match spec (REQ-PROTO-2)")
    void testTypeConstants() {
        assertEquals(0x01, Codec.TYPE_HELLO & 0xFF);
        assertEquals(0x02, Codec.TYPE_OK & 0xFF);
        assertEquals(0x03, Codec.TYPE_ERR & 0xFF);
        assertEquals(0x10, Codec.TYPE_QUERY & 0xFF);
        assertEquals(0x11, Codec.TYPE_EXEC & 0xFF);
        assertEquals(0x20, Codec.TYPE_RESULT_HEADER & 0xFF);
        assertEquals(0x21, Codec.TYPE_RESULT_ROW & 0xFF);
        assertEquals(0x22, Codec.TYPE_RESULT_DONE & 0xFF);
        assertEquals(0x23, Codec.TYPE_RESULT_ERROR & 0xFF);
        assertEquals(0x30, Codec.TYPE_PING & 0xFF);
        assertEquals(0x31, Codec.TYPE_PONG & 0xFF);
        assertEquals(0xFE, Codec.TYPE_QUIT & 0xFF);
    }
}
